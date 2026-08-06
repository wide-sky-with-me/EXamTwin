from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Protocol

from llama_index.core.llms import LLM
from llama_index.core.schema import NodeWithScore

from examtwin.answering_agent.capabilities import AgentTool, CapabilityRegistry
from examtwin.answering_agent.finalization import FinalAnswerProvider
from examtwin.answering_agent.mcp import MCPServerConfig, MCPToolProvider
from examtwin.answering_agent.react_runner import ReActHarnessRunner, WorkflowRunner
from examtwin.answering_agent.runtime import AnsweringAgentRuntime
from examtwin.answering_agent.tools import (
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
from examtwin.answering_agent.tools.paired_exam import PairedExamReader
from examtwin.answering_agent.tools.question_vision import QUESTION_VISION_CONTRACT_VERSION
from examtwin.config import Settings
from examtwin.schemas.evidence import Citation
from examtwin.services.providers import (
    build_final_answer_provider,
    build_image_generation_provider,
    build_llm,
    build_question_vision_provider,
)
from examtwin.services.source_context import SourceDocumentReader
from examtwin.storage import ManagedObjectStore
from examtwin.subject_packages import SubjectPackage, get_subject_package


def _mcp_providers(settings: Settings) -> tuple[MCPToolProvider, ...]:
    providers: list[MCPToolProvider] = []
    for item in settings.answer_agent_mcp_servers:
        name = str(item.get("name", "")).strip()
        command_or_url = str(item.get("command_or_url", "")).strip()
        allowed = item.get("allowed_tools", [])
        args = item.get("args", [])
        if not name or not command_or_url:
            raise ValueError("Each MCP server requires name and command_or_url")
        if not isinstance(allowed, list) or not all(isinstance(value, str) for value in allowed):
            raise ValueError(f"MCP server {name} allowed_tools must be a string array")
        if not isinstance(args, list) or not all(isinstance(value, str) for value in args):
            raise ValueError(f"MCP server {name} args must be a string array")
        providers.append(
            MCPToolProvider(
                MCPServerConfig(
                    name=name,
                    command_or_url=command_or_url,
                    args=tuple(args),
                    allowed_tools=tuple(allowed),
                    timeout_seconds=float(item.get("timeout_seconds", 30)),
                    max_result_chars=int(item.get("max_result_chars", 16_000)),
                )
            )
        )
    return tuple(providers)


def build_answering_runtime(
    settings: Settings,
    *,
    retriever: Callable[..., list[NodeWithScore]],
    citation_factory: Callable[[NodeWithScore], Citation],
    documents: AnswerEvidenceReader | None = None,
    llm: LLM | None = None,
    vision_llm: LLM | None = None,
    runner: WorkflowRunner | None = None,
    final_answer_provider: FinalAnswerProvider | None = None,
    object_store: ManagedObjectStore | None = None,
    subject_package: SubjectPackage | None = None,
) -> AnsweringAgentRuntime:
    package = subject_package or get_subject_package(
        settings.subject_pack,
        settings.subject_packages_dir,
    )
    question_vision_provider = (
        None if vision_llm is not None else build_question_vision_provider(settings)
    )
    tools: list[AgentTool] = [
        QuestionVisionTool(
            vision_llm,
            timeout_seconds=settings.paper_vision_timeout + 5,
            provider=question_vision_provider,
        ),
        KnowledgeSearchTool(
            retriever,
            citation_factory,
            timeout_seconds=min(settings.answer_agent_timeout / 2, 90),
        ),
        MathCalculateTool(),
        ProbabilityCalculateTool(),
        EconomicsCalculateTool(),
        EconomicsDiagramTool(),
        MathPlotTool(),
        MathDiagramTool(),
    ]
    if settings.image_generation_enabled and settings.image_provider_api_key is not None:
        tools.append(
            ImageGenerationTool(
                build_image_generation_provider(settings),
                AnswerImageStore(
                    object_store or settings.object_store_root / "answer-artifacts",
                    retention_days=settings.answer_artifact_retention_days,
                ),
                timeout_seconds=(
                    settings.image_generation_timeout * settings.image_generation_max_attempts
                    + settings.image_generation_max_attempts
                ),
            )
        )
    if documents is not None:
        tools.extend(
            (
                PairedExamLookupTool(
                    documents,
                    settings,
                    timeout_seconds=min(settings.answer_agent_timeout / 3, 45),
                    vision_provider=question_vision_provider,
                ),
                SourceReadTool(
                    documents,
                    settings,
                    timeout_seconds=min(settings.answer_agent_timeout / 3, 45),
                ),
            )
        )
    registry = CapabilityRegistry(
        tools=tuple(tools),
        providers=_mcp_providers(settings),
    )
    resolved_runner = runner
    if resolved_runner is None:
        resolved_runner = ReActHarnessRunner(
            final_answer_provider=final_answer_provider or build_final_answer_provider(settings)
        )
    question_vision_replay_identity = None
    if vision_llm is None:
        vision_identity = json.dumps(
            {
                "contract": QUESTION_VISION_CONTRACT_VERSION,
                "provider_base_url": settings.llm_provider_base_url,
                "model": settings.paper_vision_model,
                "reasoning_effort": settings.paper_vision_reasoning_effort,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        question_vision_replay_identity = hashlib.sha256(vision_identity.encode()).hexdigest()
    return AnsweringAgentRuntime(
        llm=llm
        or build_llm(
            settings,
            timeout=settings.answer_agent_timeout,
            max_retries=1,
        ),
        skills=(package.require_skill(),),
        registry=registry,
        runner=resolved_runner,
        max_iterations=settings.answer_agent_max_iterations,
        max_tool_calls=settings.answer_agent_max_tool_calls,
        timeout=settings.answer_agent_timeout,
        question_vision_replay_identity=question_vision_replay_identity,
    )


class AnswerEvidenceReader(SourceDocumentReader, PairedExamReader, Protocol):
    """Documents exposed to answer tools through reviewed read-only methods."""
