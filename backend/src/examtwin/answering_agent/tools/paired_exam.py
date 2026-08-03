from __future__ import annotations

import re
from typing import Any, Protocol
from urllib.parse import quote

from llama_index.core.tools import BaseTool, FunctionTool

from examtwin.answering_agent.blocking import run_blocking_bounded
from examtwin.answering_agent.contracts import AgentRunContext
from examtwin.config import Settings
from examtwin.schemas.evidence import Citation
from examtwin.services.source_context import source_context


class PairedExamReader(Protocol):
    def exact_pair_documents(self, pair_key: str, limit: int = 3) -> list[dict[str, Any]]: ...


class PairedExamLookupTool:
    """Read evidence from documents with the uploaded paper's exact pair key."""

    name = "paired_exam_lookup"

    def __init__(
        self,
        documents: PairedExamReader,
        settings: Settings,
        *,
        timeout_seconds: float = 30,
    ):
        self._documents = documents
        self._settings = settings
        self._timeout_seconds = timeout_seconds

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def paired_exam_lookup() -> str:
            """Read exact-pair mark-scheme and examiner evidence for this question."""

            pair_key = context.task.pair_key
            if not pair_key:
                return "No exact paper pair key is available for this uploaded paper."
            rows = self._documents.exact_pair_documents(pair_key)
            if not rows:
                return (
                    f"No converted mark scheme or examiner evidence exists for exact pair "
                    f"{pair_key}. Do not infer a pair from another session."
                )

            question_number = (context.task.question_number or "").strip()
            query = " ".join(
                item
                for item in (
                    f"Question {question_number}" if question_number else "",
                    context.task.question[:500],
                )
                if item
            )
            sections: list[str] = []
            for row in rows[:3]:
                try:
                    result = await run_blocking_bounded(
                        source_context,
                        self._documents,
                        self._settings,
                        str(row["id"]),
                        query=query,
                        timeout=self._timeout_seconds,
                    )
                except LookupError:
                    continue
                excerpt = re.sub(r"\s+", " ", result.content_markdown).strip()[:1200]
                citation = Citation(
                    source=str(row["path"]),
                    document_id=str(row["id"]),
                    source_type=str(row["source_type"]),
                    authority_tier=str(row["authority_tier"]),
                    pair_key=str(row["pair_key"]),
                    excerpt=excerpt,
                    section=f"Question {question_number}" if question_number else None,
                    evidence_role=(
                        "marking" if row["source_type"] == "mark_scheme" else "assessment"
                    ),
                    content_url=(
                        f"/sources/{quote(str(row['id']), safe='')}/context?"
                        f"query={quote(query[:160])}"
                    ),
                )
                source_index = context.add_citation(citation)
                sections.append(
                    f"[S{source_index}] exact_pair={pair_key} "
                    f"source_type={row['source_type']} source={row['path']}\n"
                    f"{result.content_markdown[:8000]}"
                )
            if not sections:
                return (
                    f"Exact-pair records exist for {pair_key}, but their converted source "
                    "content is unavailable. Do not substitute another paper."
                )
            return "\n\n".join(sections)[:24_000]

        return FunctionTool.from_defaults(
            async_fn=paired_exam_lookup,
            name=self.name,
            description=(
                "Read the official mark scheme, examiner report and question paper that "
                "match this uploaded paper's exact year/session/unit pair. Never guesses "
                "or substitutes a nearby examination session."
            ),
        )
