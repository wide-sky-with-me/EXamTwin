from __future__ import annotations

import asyncio
import json
from typing import Any

from examtwin.assessment.answering_agent import (
    AgentFinalPayload,
    AnsweringAgentRuntime,
    CapabilityRegistry,
)
from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
)
from examtwin.assessment.answering_agent.tools import (
    KnowledgeSearchTool,
    MathCalculateTool,
    MathDiagramTool,
)
from examtwin.contracts import Citation
from examtwin.platform.agent_runtime import HarnessMessage, HarnessTool
from examtwin.subjects.packages import get_subject_package
from llama_index.core.llms import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    CustomLLM,
    LLMMetadata,
    MessageRole,
    MockLLM,
)
from llama_index.core.schema import NodeWithScore, TextNode
from pydantic import Field

MATHEMATICS_9660 = get_subject_package("oxfordaqa-mathematics-9660").require_skill()


def _nodes(_query: str, **_kwargs: Any) -> list[NodeWithScore]:
    return [
        NodeWithScore(
            node=TextNode(
                text="For a quadratic, the discriminant is b^2 - 4ac.",
                metadata={
                    "source": "textbook.md",
                    "document_id": "doc-1",
                    "page": 12,
                    "source_type": "textbook",
                    "authority_tier": "licensed_core",
                },
            ),
            score=0.92,
        )
    ]


def _citation(node: NodeWithScore) -> Citation:
    return Citation(
        source=str(node.node.metadata["source"]),
        document_id=str(node.node.metadata["document_id"]),
        page=int(node.node.metadata["page"]),
        source_type="textbook",
        authority_tier="licensed_core",
        score=node.score,
        excerpt=node.node.get_content(),
    )


class ToolUsingRunner:
    async def run(
        self,
        *,
        tools: list[HarnessTool],
        context: AgentRunContext,
        **_kwargs: Any,
    ) -> str:
        by_name = {tool.spec.name: tool for tool in tools}
        context.emit("tool", "running", "检索知识库中", tool_name="knowledge_search")
        evidence = await by_name["knowledge_search"].invoke(
            {"query": "quadratic discriminant", "top_k": 3}
        )
        context.emit("tool", "completed", "检索知识库完成", tool_name="knowledge_search")
        calculation = await by_name["math_calculate"].invoke(
            {
                "operation": "solve",
                "expression": "x^2 - 5*x + 6 = 0",
                "variable": "x",
            }
        )
        await by_name["math_diagram"].invoke(
            {
                "title": "Two roots on an axis",
                "elements": [
                    {"kind": "line", "x1": 20, "y1": 60, "x2": 180, "y2": 60},
                    {"kind": "point", "x": 80, "y": 60},
                    {"kind": "point", "x": 120, "y": 60},
                ],
            }
        )
        assert "[S1]" in evidence.content
        assert "[2, 3]" in calculation.content
        return json.dumps(
            {
                "answer_markdown": "The roots are 2 and 3. [S1]",
                "confidence": 0.91,
                "grounded": True,
                "warnings": [],
            }
        )


class NoEvidenceRunner:
    async def run(self, **_kwargs: Any) -> str:
        return json.dumps(
            {
                "answer_markdown": "An unsupported answer.",
                "confidence": 0.8,
                "grounded": True,
                "warnings": [],
            }
        )


class ScriptedReActLLM(CustomLLM):
    calls: int = 0
    responses: tuple[str, ...] = ()
    prompts: list[str] = Field(default_factory=list)

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=8192,
            num_output=1024,
            is_chat_model=True,
            is_function_calling_model=False,
            model_name="scripted-react",
        )

    def complete(
        self,
        _prompt: str,
        formatted: bool = False,
        **_kwargs: Any,
    ) -> CompletionResponse:
        del formatted
        self.prompts.append(_prompt)
        self.calls += 1
        if self.responses:
            text = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        elif self.calls == 1:
            text = (
                "Thought: I need grounded evidence.\n"
                "Action: knowledge_search\n"
                'Action Input: {"query": "quadratic discriminant", "top_k": 3}'
            )
        else:
            text = (
                "Thought: The tool observation supports the answer.\n"
                "Answer: "
                '{"answer_markdown":"The discriminant is $b^2-4ac$. [S1]",'
                '"confidence":0.9,"grounded":true,"warnings":[]}'
            )
        return CompletionResponse(text=text)

    def stream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ):
        response = self.complete(prompt, formatted=formatted, **kwargs)
        yield CompletionResponse(text=response.text, delta=response.text)

    async def acomplete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse:
        return self.complete(prompt, formatted=formatted, **kwargs)

    async def astream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ):
        response = self.complete(prompt, formatted=formatted, **kwargs)
        yield CompletionResponse(text=response.text, delta=response.text)


class CapturingFinalAnswerProvider:
    def __init__(
        self,
        payload: AgentFinalPayload | None = None,
        *,
        error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.payload = payload or AgentFinalPayload(
            answer_markdown="The discriminant is $b^2-4ac$. [S1]",
            citation_ids=["S1"],
            confidence=0.93,
            grounded=True,
            warnings=[],
        )
        self.error = error
        self.delay = delay
        self.calls = 0
        self.messages: list[HarnessMessage] = []
        self.draft: str | None = None
        self.finalize_timeout: float | None = None

    async def finalize(
        self,
        messages: list[HarnessMessage],
        *,
        draft: str | None = None,
        allowed_citation_ids: tuple[str, ...] | None = None,
        timeout: float | None = None,
    ) -> AgentFinalPayload:
        del allowed_citation_ids
        self.calls += 1
        self.messages = messages
        self.draft = draft
        self.finalize_timeout = timeout

        async def complete() -> AgentFinalPayload:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.error is not None:
                raise self.error
            return self.payload

        if timeout is None:
            return await complete()
        async with asyncio.timeout(timeout):
            return await complete()


class CapturingVisionLLM:
    def __init__(
        self,
        observation: str = "The original page shows a labelled curve.",
        *,
        delay: float = 0,
    ) -> None:
        self.observation = observation
        self.delay = delay
        self.calls = 0
        self.messages: list[ChatMessage] = []

    async def achat(self, messages: list[ChatMessage]) -> ChatResponse:
        self.calls += 1
        self.messages = messages
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=json.dumps({"observation": self.observation}),
            )
        )


class FailingVisionLLM:
    calls = 0

    async def achat(self, _messages: list[ChatMessage]) -> ChatResponse:
        self.calls += 1
        raise RuntimeError("vision provider unavailable")


class MustNotRun:
    calls = 0

    async def run(self, **_kwargs: Any) -> str:
        self.calls += 1
        raise AssertionError("main reasoning must not run after vision failure")


def _runtime(runner: Any) -> AnsweringAgentRuntime:
    return AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                KnowledgeSearchTool(_nodes, _citation),
                MathCalculateTool(),
                MathDiagramTool(),
            )
        ),
        runner=runner,
        max_iterations=8,
        max_tool_calls=6,
        timeout=30,
    )
