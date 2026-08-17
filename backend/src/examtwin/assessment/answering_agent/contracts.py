from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from examtwin.contracts.evidence import (
    AnswerDiagram,
    AnswerImage,
    Citation,
    SubpartRequirement,
)
from examtwin.subjects.public import SubjectSkill as SubjectSkill


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
class QuestionImage:
    """Trusted paper pixels loaded by PaperWorker, never a caller-supplied path."""

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
    source_booklet_document_id: str | None = None
    source_booklet_checksum: str | None = None
    source_types: tuple[str, ...] = ()
    authority_tiers: tuple[str, ...] = ("official", "licensed_core")
    top_k: int = 6
    question_images: tuple[QuestionImage, ...] = ()
    knowledge_base_version_ids: tuple[str, ...] = ()
    graph_version_id: str | None = None


@dataclass(frozen=True)
class AgentStep:
    sequence: int
    phase: str
    status: str
    message: str
    tool_name: str | None = None


AgentEventSink = Callable[[AgentStep], None]


class ToolReplayPayload(BaseModel):
    """Public tool observation and typed context effects safe to replay."""

    observation: str = Field(max_length=24_000)
    citations: tuple[Citation, ...] = ()
    diagrams: tuple[AnswerDiagram, ...] = ()
    images: tuple[AnswerImage, ...] = ()


class AgentRunLedger(Protocol):
    def start_run(
        self,
        *,
        package_id: str,
        package_version: str,
        package_digest: str,
        skill_digest: str,
        prompt_digest: str,
        model_name: str,
        max_iterations: int,
        max_tool_calls: int,
        knowledge_base_version_ids: tuple[str, ...],
        graph_version_id: str | None,
    ) -> None: ...

    def find_replay(
        self,
        *,
        call_key: str,
        execution_fingerprint: str,
    ) -> ToolReplayPayload | None: ...

    def tool_started(
        self,
        *,
        call_key: str,
        tool_name: str,
        input_digest: str,
        execution_fingerprint: str,
        replay_safe: bool,
    ) -> None: ...

    def tool_finished(
        self,
        *,
        call_key: str,
        status: str,
        result_digest: str | None,
        replay: ToolReplayPayload | None,
        error_type: str | None,
    ) -> None: ...

    def finish_run(self, status: str) -> None: ...


@dataclass
class AgentRunContext:
    task: AnswerTask
    event_sink: AgentEventSink | None = None
    ledger: AgentRunLedger | None = None
    citations: list[Citation] = field(default_factory=list)
    diagrams: list[AnswerDiagram] = field(default_factory=list)
    images: list[AnswerImage] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    prompt_digest: str | None = None
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

    def resolve_artifact_anchor(self, tool_name: str, answer_anchor: str | None) -> str:
        """Validate or infer a semantic answer location before producing an artifact."""

        labelled_subparts = self.task.question_spec.labelled_subparts
        required_anchors = tuple(
            part.label
            for part in self.task.question_spec.subparts
            if part.required_tool == tool_name and part.label in labelled_subparts
        )
        anchor = answer_anchor.strip() if answer_anchor else None
        if anchor is None:
            if len(required_anchors) == 1:
                anchor = required_anchors[0]
            elif not labelled_subparts:
                anchor = "whole"
            else:
                raise ValueError(
                    f"{tool_name} answer_anchor is required; use one exact subpart label: "
                    + ", ".join(labelled_subparts)
                )
        if anchor.lower() in {"whole", "all"}:
            anchor = "whole"
        valid_anchors = labelled_subparts or ("whole",)
        if anchor not in set(valid_anchors):
            raise ValueError(
                f"{tool_name} answer_anchor must be one of: " + ", ".join(valid_anchors)
            )
        return anchor

    def _artifact_metadata(
        self,
        *,
        tool_name: str,
        answer_anchor: str | None,
    ) -> dict[str, str | int]:
        anchor = self.resolve_artifact_anchor(tool_name, answer_anchor)

        existing = [*self.diagrams, *self.images]
        order = len(existing) + 1
        return {
            "artifact_id": f"artifact-{order}",
            "answer_anchor": anchor,
            "answer_order": order,
        }

    def add_diagram(self, diagram: AnswerDiagram) -> AnswerDiagram:
        with self._lock:
            if len(self.diagrams) >= 3:
                raise ValueError("A maximum of three answer diagrams is allowed")
            placed = diagram.model_copy(
                update=self._artifact_metadata(
                    tool_name=diagram.tool_name,
                    answer_anchor=diagram.answer_anchor,
                )
            )
            self.diagrams.append(placed)
        return placed

    def add_image(self, image: AnswerImage) -> AnswerImage:
        with self._lock:
            if len(self.images) >= 3:
                raise ValueError("A maximum of three generated answer images is allowed")
            placed = image.model_copy(
                update=self._artifact_metadata(
                    tool_name=image.tool_name,
                    answer_anchor=image.answer_anchor,
                )
            )
            self.images.append(placed)
        return placed

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
