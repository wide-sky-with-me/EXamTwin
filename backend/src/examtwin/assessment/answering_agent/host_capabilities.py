from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from llama_index.core.schema import NodeWithScore

from examtwin.assessment.answering_agent.capabilities import AgentTool
from examtwin.assessment.answering_agent.factory_contracts import AnswerEvidenceReader
from examtwin.assessment.answering_agent.tools import (
    AnswerImageStore,
    EconomicsCalculateTool,
    EconomicsDiagramTool,
    ImageGenerationTool,
    KnowledgeSearchTool,
    MathCalculateTool,
    MathDiagramTool,
    MathPlotTool,
    PairedExamLookupTool,
    ProbabilityCalculateTool,
    QuestionVisionTool,
    SourceReadTool,
)
from examtwin.contracts.evidence import Citation
from examtwin.platform.config import Settings
from examtwin.platform.storage import ManagedObjectStore

HostToolFactory = Callable[[], AgentTool | None]
AnswerArtifactShape = Literal["diagram", "image"]


@dataclass(frozen=True)
class HostCapabilityMetadata:
    display_label: str
    artifact_shape: AnswerArtifactShape | None = None
    replay_safe: bool = True
    provider_version: str = "v1"


HOST_CAPABILITY_METADATA = MappingProxyType(
    {
        "question_vision": HostCapabilityMetadata("Question vision"),
        "knowledge_search": HostCapabilityMetadata("Knowledge search"),
        "math_calculate": HostCapabilityMetadata("Mathematics calculation"),
        "probability_calculate": HostCapabilityMetadata("Probability calculation"),
        "economics_calculate": HostCapabilityMetadata("Economics calculation"),
        "economics_diagram": HostCapabilityMetadata("Economics diagram", artifact_shape="diagram"),
        "math_plot": HostCapabilityMetadata("Coordinate plot", artifact_shape="diagram"),
        "math_diagram": HostCapabilityMetadata("Vector diagram", artifact_shape="diagram"),
        "image_generate": HostCapabilityMetadata(
            "Generated image", artifact_shape="image", replay_safe=False
        ),
        "paired_exam_lookup": HostCapabilityMetadata("Paired exam lookup"),
        "source_read": HostCapabilityMetadata("Source read"),
    }
)


def answer_artifact_capabilities(
    allowed_names: tuple[str, ...],
) -> tuple[tuple[str, AnswerArtifactShape], ...]:
    return tuple(
        (name, metadata.artifact_shape)
        for name in allowed_names
        if (metadata := HOST_CAPABILITY_METADATA.get(name)) is not None
        and metadata.artifact_shape is not None
    )


def build_host_answering_tools(
    settings: Settings,
    *,
    allowed_names: tuple[str, ...],
    required_names: tuple[str, ...] = (),
    known_external_names: frozenset[str] = frozenset(),
    retriever: Callable[..., list[NodeWithScore]],
    citation_factory: Callable[[NodeWithScore], Citation],
    question_vision_provider: Any | None,
    vision_llm: Any | None,
    image_generation_provider: Any | None,
    documents: AnswerEvidenceReader | None,
    object_store: ManagedObjectStore | None,
) -> tuple[AgentTool, ...]:
    """Instantiate only reviewed host capabilities referenced by a subject package.

    Subject packages remain declarative. Unknown names are not imported or executed here;
    they may only be supplied by separately configured capability providers such as MCP.
    """

    factories: dict[str, HostToolFactory] = {
        "question_vision": lambda: QuestionVisionTool(
            vision_llm,
            timeout_seconds=settings.paper_vision_timeout + 5,
            question_max_chars=settings.question_vision_question_max_chars,
            provider=question_vision_provider,
        ),
        "knowledge_search": lambda: KnowledgeSearchTool(
            retriever,
            citation_factory,
            timeout_seconds=min(settings.answer_agent_timeout / 2, 90),
        ),
        "math_calculate": MathCalculateTool,
        "probability_calculate": ProbabilityCalculateTool,
        "economics_calculate": EconomicsCalculateTool,
        "economics_diagram": EconomicsDiagramTool,
        "math_plot": MathPlotTool,
        "math_diagram": MathDiagramTool,
        "image_generate": lambda: (
            ImageGenerationTool(
                image_generation_provider,
                AnswerImageStore(
                    object_store or settings.object_store_root / "answer-artifacts",
                    retention_days=settings.answer_artifact_retention_days,
                ),
                timeout_seconds=(
                    settings.image_generation_timeout * settings.image_generation_max_attempts
                    + settings.image_generation_max_attempts
                ),
            )
            if image_generation_provider is not None
            else None
        ),
        "paired_exam_lookup": lambda: (
            PairedExamLookupTool(
                documents,
                settings,
                timeout_seconds=min(
                    settings.answer_agent_timeout / 3,
                    settings.answer_agent_tool_timeout,
                ),
                vision_provider=question_vision_provider,
                object_store=object_store,
            )
            if documents is not None
            else None
        ),
        "source_read": lambda: (
            SourceReadTool(
                documents,
                settings,
                timeout_seconds=min(
                    settings.answer_agent_timeout / 3,
                    settings.answer_agent_tool_timeout,
                ),
            )
            if documents is not None
            else None
        ),
    }

    if set(factories) != set(HOST_CAPABILITY_METADATA):
        raise RuntimeError("host capability factories and metadata are out of sync")

    unknown = set(allowed_names) - set(HOST_CAPABILITY_METADATA) - set(known_external_names)
    if unknown:
        raise ValueError(
            "subject package references unknown answering capabilities: "
            + ", ".join(sorted(unknown))
        )

    tools: list[AgentTool] = []
    for name in allowed_names:
        factory = factories.get(name)
        if factory is None:
            continue
        tool = factory()
        if tool is not None:
            tools.append(tool)

    built_names = {tool.name for tool in tools}
    unavailable_required = (set(required_names) & set(factories)) - built_names
    if unavailable_required:
        raise ValueError(
            "required answering capabilities are known but unavailable: "
            + ", ".join(sorted(unavailable_required))
        )
    return tuple(tools)
