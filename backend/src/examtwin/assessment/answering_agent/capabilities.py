from __future__ import annotations

from typing import Protocol

from llama_index.core.tools import BaseTool

from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
    SubjectSkill,
)
from examtwin.assessment.answering_agent.llama_index_adapter import LlamaIndexToolAdapter
from examtwin.platform.agent_runtime.tools import HarnessTool


class AgentTool(Protocol):
    name: str

    def bind(self, context: AgentRunContext) -> BaseTool: ...


class CapabilityProvider(Protocol):
    async def load_tools(self, allowed_names: set[str]) -> list[BaseTool]: ...


class CapabilityRegistry:
    def __init__(
        self,
        tools: tuple[AgentTool, ...] = (),
        providers: tuple[CapabilityProvider, ...] = (),
    ):
        self._tools: dict[str, AgentTool] = {}
        self._providers = providers
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate answering tool: {tool.name}")
            self._tools[tool.name] = tool

    async def resolve(
        self,
        skill: SubjectSkill,
        context: AgentRunContext,
        requested_tool_names: tuple[str, ...] | None = None,
    ) -> list[HarnessTool]:
        allowed = set(skill.tool_names)
        requested = set(requested_tool_names or skill.tool_names)
        forbidden = requested - allowed
        if forbidden:
            raise ValueError(
                "answering policy requested forbidden tools: " + ", ".join(sorted(forbidden))
            )
        resolved: dict[str, BaseTool] = {
            name: tool.bind(context) for name, tool in self._tools.items() if name in requested
        }
        for provider in self._providers:
            for tool in await provider.load_tools(requested - set(resolved)):
                name = tool.metadata.name
                if name not in requested:
                    raise ValueError(f"capability provider exposed forbidden tool: {name}")
                if name in resolved:
                    raise ValueError(f"duplicate answering tool: {name}")
                resolved[name] = tool

        missing = set(skill.required_tool_names) - set(resolved)
        if missing:
            raise ValueError(
                "answering skill is missing required tools: " + ", ".join(sorted(missing))
            )
        return [
            LlamaIndexToolAdapter(resolved[name]) for name in skill.tool_names if name in resolved
        ]
