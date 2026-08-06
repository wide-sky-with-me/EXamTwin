from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from llama_index.core.agent.react.formatter import ReActChatFormatter
from llama_index.core.agent.react.output_parser import ReActOutputParser
from llama_index.core.agent.react.types import (
    ActionReasoningStep,
    BaseReasoningStep,
    ObservationReasoningStep,
    ResponseReasoningStep,
)
from llama_index.core.llms import LLM, ChatMessage, MessageRole
from llama_index.core.tools import AsyncBaseTool, BaseTool

from examtwin.assessment.answering_agent.react_protocol import (
    _ACTION_MARKER,
    _ANSWER_MARKER,
    _compatible_action_step,
    _recovered_plain_answer,
    _validated_final_json,
)
from examtwin.platform.agent_runtime.model import ChatModelPort, HarnessMessage
from examtwin.platform.agent_runtime.protocol import (
    AgentProtocolPort,
    ProtocolEvent,
    ProtocolFinal,
    ProtocolInvalid,
    ProtocolToolCall,
    ProtocolTurn,
    ToolCallEvent,
)
from examtwin.platform.agent_runtime.tools import HarnessTool, ToolCallResult, ToolSpec


class LlamaIndexChatModelAdapter(ChatModelPort):
    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    @property
    def model_name(self) -> str:
        return str(getattr(self.llm.metadata, "model_name", type(self.llm).__name__))

    async def complete(self, messages: Sequence[HarnessMessage]) -> str:
        response = await self.llm.achat(
            [
                ChatMessage(role=MessageRole(message.role), content=message.content)
                for message in messages
            ]
        )
        content = response.message.content
        if not content:
            raise ValueError("answering Agent returned an empty response")
        return content


class LlamaIndexToolAdapter(HarnessTool):
    def __init__(self, tool: BaseTool) -> None:
        if not tool.metadata.name:
            raise ValueError("answering capability is missing a tool name")
        self.native_tool = tool
        schema = tool.metadata.fn_schema
        self._spec = ToolSpec(
            name=tool.metadata.name,
            description=tool.metadata.description or "",
            input_schema={} if schema is None else schema.model_json_schema(),
        )

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolCallResult:
        tool_input = dict(arguments)
        schema = self.native_tool.metadata.fn_schema
        if schema is not None:
            tool_input = schema.model_validate(tool_input).model_dump()
        if not isinstance(self.native_tool, AsyncBaseTool):
            raise TypeError(f"answering tool {self.spec.name} is not asynchronous")
        result = await self.native_tool.acall(**tool_input)
        return ToolCallResult(content=result.content[:24_000], is_error=result.is_error)


def _native_tools(tools: Sequence[HarnessTool]) -> list[BaseTool]:
    native: list[BaseTool] = []
    for tool in tools:
        if not isinstance(tool, LlamaIndexToolAdapter):
            raise TypeError("LlamaIndex ReAct protocol requires a LlamaIndex tool adapter")
        native.append(tool.native_tool)
    return native


class LlamaIndexReActProtocolAdapter(AgentProtocolPort):
    """Keep LlamaIndex protocol details behind the provider-neutral harness port."""

    def format_messages(
        self,
        *,
        system_prompt: str,
        question: str,
        tools: Sequence[HarnessTool],
        events: Sequence[ProtocolEvent],
        corrections: Sequence[HarnessMessage],
    ) -> tuple[HarnessMessage, ...]:
        native_tools = _native_tools(tools)
        reasoning: list[BaseReasoningStep] = []
        for event in events:
            if isinstance(event, ToolCallEvent):
                reasoning.append(
                    ActionReasoningStep(
                        thought=event.thought,
                        action=event.tool_name,
                        action_input=dict(event.arguments),
                    )
                )
            else:
                reasoning.append(ObservationReasoningStep(observation=event.content))
        messages = ReActChatFormatter.from_defaults(context=system_prompt).format(
            native_tools,
            [ChatMessage(role=MessageRole.USER, content=question)],
            current_reasoning=reasoning,
        )
        result = [
            HarnessMessage(
                role=cast(Any, getattr(message.role, "value", message.role)),
                content=message.content or "",
            )
            for message in messages
        ]
        result.extend(corrections)
        return tuple(result)

    def parse(
        self,
        content: str,
        *,
        tools: Sequence[HarnessTool],
        grounded: bool,
    ) -> ProtocolTurn:
        final_json = _validated_final_json(content)
        if final_json is not None:
            return ProtocolFinal(draft=content, output_json=final_json)

        native_tools = _native_tools(tools)
        by_name: dict[str, BaseTool] = {}
        for tool in native_tools:
            if tool.metadata.name:
                by_name[tool.metadata.name] = tool
        parser = ReActOutputParser()
        if len(_ACTION_MARKER.findall(content)) > 1:
            step = _compatible_action_step(content, by_name)
        else:
            try:
                step = parser.parse(content, is_streaming=False)
            except Exception:
                step = _compatible_action_step(content, by_name)
        if isinstance(step, ActionReasoningStep) and step.action not in by_name:
            step = _compatible_action_step(content, by_name) or step
        if isinstance(step, ActionReasoningStep):
            return ProtocolToolCall(
                thought=step.thought,
                tool_name=step.action,
                arguments=step.action_input,
            )
        if isinstance(step, ResponseReasoningStep):
            if not _ANSWER_MARKER.search(content):
                return ProtocolInvalid(reason="missing Answer marker")
            recovered = _recovered_plain_answer(content, step, grounded=grounded)
            return ProtocolFinal(draft=content, output_json=recovered)
        return ProtocolInvalid(reason="unrecognized ReAct response")
