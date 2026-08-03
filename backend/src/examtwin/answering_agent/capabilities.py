from __future__ import annotations

from llama_index.core.tools import BaseTool

from examtwin.answering_agent.contracts import (
    AgentRunContext,
    AgentTool,
    CapabilityProvider,
    SubjectSkill,
)


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
    ) -> list[BaseTool]:
        allowed = set(skill.tool_names)
        resolved: dict[str, BaseTool] = {
            name: tool.bind(context) for name, tool in self._tools.items() if name in allowed
        }
        for provider in self._providers:
            for tool in await provider.load_tools(allowed - set(resolved)):
                name = tool.metadata.name
                if name not in allowed:
                    raise ValueError(f"capability provider exposed forbidden tool: {name}")
                if name in resolved:
                    raise ValueError(f"duplicate answering tool: {name}")
                resolved[name] = tool

        missing = set(skill.required_tool_names) - set(resolved)
        if missing:
            raise ValueError(
                "answering skill is missing required tools: " + ", ".join(sorted(missing))
            )
        return [resolved[name] for name in skill.tool_names if name in resolved]
