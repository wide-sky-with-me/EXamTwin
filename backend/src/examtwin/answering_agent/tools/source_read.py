from __future__ import annotations

from llama_index.core.tools import BaseTool, FunctionTool

from examtwin.answering_agent.blocking import run_blocking_bounded
from examtwin.answering_agent.contracts import AgentRunContext
from examtwin.config import Settings
from examtwin.services.source_context import SourceDocumentReader, source_context


class SourceReadTool:
    name = "source_read"

    def __init__(
        self,
        documents: SourceDocumentReader,
        settings: Settings,
        *,
        timeout_seconds: float = 30,
    ):
        self._documents = documents
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def source_read(
            document_id: str,
            page: int | None = None,
            query: str = "",
        ) -> str:
            """Read a full page or section from a document returned by an evidence tool."""
            if document_id not in context.allowed_document_ids:
                raise ValueError("source_read may only open documents returned by evidence tools")
            result = await run_blocking_bounded(
                source_context,
                self._documents,
                self._settings,
                document_id,
                page=page,
                query=query,
                timeout=self._timeout_seconds,
            )
            return f"source={result.source} page={result.page}\n{result.content_markdown[:20_000]}"

        return FunctionTool.from_defaults(
            async_fn=source_read,
            name=self.name,
            description=(
                "Read the complete relevant page or section of a document already returned "
                "by an approved evidence tool. Use it when a short excerpt is insufficient."
            ),
        )
