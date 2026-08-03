from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from llama_index.core.tools import BaseTool
from pydantic import BaseModel, Field, field_validator

from examtwin.schemas.evidence import AnswerDiagram, AnswerImage, Citation

AnswerKind = Literal[
    "text",
    "numeric",
    "expression",
    "proof",
    "table",
    "math_plot",
    "math_diagram",
    "image",
]
AnswerArtifactTool = Literal["math_plot", "math_diagram", "image_generate"]


class SubpartRequirement(BaseModel):
    """A machine-checkable answer obligation extracted while splitting the paper."""

    label: str = Field(default="whole", max_length=32)
    marks: int | None = Field(default=None, ge=0, le=100)
    answer_kind: AnswerKind = "text"
    accuracy: str | None = Field(default=None, max_length=160)
    units: tuple[str, ...] = Field(default=(), max_length=8)
    required_tool: AnswerArtifactTool | None = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip() or "whole"

    @field_validator("units")
    @classmethod
    def normalize_units(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(unit.strip() for unit in value if unit.strip()))


class QuestionSpec(BaseModel):
    """Structured requirements for one top-level examination question."""

    subparts: tuple[SubpartRequirement, ...] = ()
    total_marks: int | None = Field(default=None, ge=0, le=200)

    @property
    def required_tool_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                part.required_tool for part in self.subparts if part.required_tool is not None
            )
        )

    @property
    def labelled_subparts(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                part.label
                for part in self.subparts
                if part.label.lower() not in {"", "whole", "all"}
            )
        )


def required_answer_artifacts_are_present(
    diagrams: Iterable[AnswerDiagram],
    images: Iterable[AnswerImage],
    required_tools: Iterable[str],
) -> bool:
    diagram_tools = {diagram.tool_name for diagram in diagrams}
    image_tools = {image.tool_name for image in images}
    return all(
        tool in image_tools if tool == "image_generate" else tool in diagram_tools
        for tool in required_tools
    )


def required_diagram_is_present(
    diagrams: Iterable[AnswerDiagram],
    required_tool: str | None,
) -> bool:
    """Compatibility wrapper for callers that still have one vector requirement."""

    return required_answer_artifacts_are_present(
        diagrams,
        (),
        () if required_tool is None else (required_tool,),
    )


@dataclass(frozen=True)
class SubjectSkill:
    """Subject policy and the capabilities an answering Agent may use."""

    name: str
    subject_codes: tuple[str, ...]
    instructions: str
    tool_names: tuple[str, ...]
    required_tool_names: tuple[str, ...] = ()
    mandatory_tool_names: tuple[str, ...] = ()
    visual_tool_selector: Callable[[str], str | None] | None = None

    def required_visual_tool(self, question: str) -> str | None:
        if self.visual_tool_selector is None:
            return None
        tool_name = self.visual_tool_selector(question)
        if tool_name is not None and tool_name not in self.tool_names:
            raise ValueError(
                f"Visual tool selector returned an unregistered capability: {tool_name}"
            )
        return tool_name


@dataclass(frozen=True)
class QuestionImage:
    """Trusted paper page pixels loaded by PaperWorker, never a caller-supplied path."""

    page_number: int
    content: bytes
    media_type: str = "image/jpeg"

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("question image page number must be positive")
        if self.media_type != "image/jpeg":
            raise ValueError("question images must be JPEG")
        if not self.content.startswith(b"\xff\xd8"):
            raise ValueError("question image is not a JPEG payload")


@dataclass(frozen=True)
class AnswerTask:
    question: str
    subject_code: str
    question_number: str | None = None
    question_spec: QuestionSpec = field(default_factory=QuestionSpec)
    visual_request_text: str | None = None
    unit_code: str | None = None
    pair_key: str | None = None
    source_types: tuple[str, ...] = ()
    authority_tiers: tuple[str, ...] = ("official", "licensed_core")
    top_k: int = 6
    question_images: tuple[QuestionImage, ...] = ()


@dataclass(frozen=True)
class AgentStep:
    sequence: int
    phase: str
    status: str
    message: str
    tool_name: str | None = None


AgentEventSink = Callable[[AgentStep], None]


@dataclass
class AgentRunContext:
    task: AnswerTask
    event_sink: AgentEventSink | None = None
    citations: list[Citation] = field(default_factory=list)
    diagrams: list[AnswerDiagram] = field(default_factory=list)
    images: list[AnswerImage] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    _sequence: int = 0
    _artifact_rollbacks: list[Callable[[], None]] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def emit(
        self,
        phase: str,
        status: str,
        message: str,
        *,
        tool_name: str | None = None,
    ) -> AgentStep:
        with self._lock:
            self._sequence += 1
            step = AgentStep(
                sequence=self._sequence,
                phase=phase,
                status=status,
                message=message[:240],
                tool_name=tool_name,
            )
            self.steps.append(step)
        if self.event_sink:
            self.event_sink(step)
        return step

    def add_citation(self, citation: Citation) -> int:
        key = (citation.document_id, citation.source, citation.page, citation.excerpt)
        for index, existing in enumerate(self.citations, start=1):
            existing_key = (
                existing.document_id,
                existing.source,
                existing.page,
                existing.excerpt,
            )
            if existing_key == key:
                return index
        self.citations.append(citation)
        return len(self.citations)

    def add_diagram(self, diagram: AnswerDiagram) -> None:
        if len(self.diagrams) >= 3:
            raise ValueError("A maximum of three answer diagrams is allowed")
        self.diagrams.append(diagram)

    def add_image(self, image: AnswerImage) -> None:
        with self._lock:
            if len(self.images) >= 3:
                raise ValueError("A maximum of three generated answer images is allowed")
            self.images.append(image)

    def ensure_image_capacity(self) -> None:
        """Reject an image request before it can incur provider cost."""

        with self._lock:
            if len(self.images) >= 3:
                raise ValueError("A maximum of three generated answer images is allowed")

    def register_artifact_rollback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._artifact_rollbacks.append(callback)

    def commit_artifacts(self) -> None:
        with self._lock:
            self._artifact_rollbacks.clear()

    def rollback_artifacts(self) -> None:
        with self._lock:
            callbacks = tuple(reversed(self._artifact_rollbacks))
            self._artifact_rollbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except OSError:
                # Cleanup is best effort; the original answering failure remains primary.
                continue

    @property
    def allowed_document_ids(self) -> set[str]:
        return {
            citation.document_id for citation in self.citations if citation.document_id is not None
        }


@dataclass(frozen=True)
class AnswerAgentResult:
    answer_markdown: str
    citations: tuple[Citation, ...]
    diagrams: tuple[AnswerDiagram, ...]
    confidence: float
    grounded: bool
    warnings: tuple[str, ...]
    steps: tuple[AgentStep, ...]
    images: tuple[AnswerImage, ...] = ()


class AgentTool(Protocol):
    name: str

    def bind(self, context: AgentRunContext) -> BaseTool: ...


class CapabilityProvider(Protocol):
    async def load_tools(self, allowed_names: set[str]) -> list[BaseTool]: ...
