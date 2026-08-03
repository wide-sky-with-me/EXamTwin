from __future__ import annotations

import asyncio
from dataclasses import dataclass

from llama_index.core.tools import BaseTool, FunctionTool


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command_or_url: str
    args: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    timeout_seconds: float = 30
    max_result_chars: int = 16_000


class MCPToolProvider:
    """Load an explicitly allowlisted MCP server into the Agent capability registry."""

    def __init__(self, config: MCPServerConfig):
        self.config = config

    async def load_tools(self, allowed_names: set[str]) -> list[BaseTool]:
        selected = allowed_names & set(self.config.allowed_tools)
        if not selected:
            return []
        try:
            from llama_index.tools.mcp import BasicMCPClient, McpToolSpec
        except ImportError as error:
            raise RuntimeError(
                "MCP tools are configured but llama-index-tools-mcp is not installed"
            ) from error

        client = BasicMCPClient(
            self.config.command_or_url,
            args=list(self.config.args),
        )
        tools = await asyncio.wait_for(
            McpToolSpec(
                client,
                allowed_tools=sorted(selected),
                include_resources=False,
            ).to_tool_list_async(),
            timeout=self.config.timeout_seconds,
        )
        return [self._bounded(tool) for tool in tools if tool.metadata.name in selected]

    def _bounded(self, tool: BaseTool) -> BaseTool:
        async def call_mcp_tool(**kwargs: object) -> str:
            result = await asyncio.wait_for(
                tool.acall(**kwargs),
                timeout=self.config.timeout_seconds,
            )
            content = str(result)
            if len(content) > self.config.max_result_chars:
                content = (
                    content[: self.config.max_result_chars].rstrip()
                    + "\n\n[MCP result truncated by ExamTwin]"
                )
            return content

        return FunctionTool.from_defaults(
            async_fn=call_mcp_tool,
            tool_metadata=tool.metadata,
        )
