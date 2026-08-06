from __future__ import annotations

from collections.abc import Callable

from llama_index.core.schema import NodeWithScore
from llama_index.core.tools import BaseTool, FunctionTool

from examtwin.assessment.answering_agent.blocking import run_blocking_bounded
from examtwin.assessment.answering_agent.contracts import AgentRunContext
from examtwin.contracts.evidence import Citation

Retriever = Callable[..., list[NodeWithScore]]
CitationFactory = Callable[[NodeWithScore], Citation]


def _citation_from_evidence(item: dict) -> Citation:
    fields = Citation.model_fields
    return Citation.model_validate({key: value for key, value in item.items() if key in fields})


class KnowledgeSearchTool:
    name = "knowledge_search"

    def __init__(
        self,
        retriever: Retriever,
        citation_factory: CitationFactory,
        *,
        timeout_seconds: float = 90,
    ):
        self._retriever = retriever
        self._citation_factory = citation_factory
        self._timeout_seconds = timeout_seconds

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def knowledge_search(query: str, top_k: int = 6) -> str:
            """Search the approved knowledge base for evidence relevant to the question."""
            safe_top_k = max(1, min(top_k, context.task.top_k, 10))
            nodes = await run_blocking_bounded(
                self._retriever,
                query,
                subject_code=context.task.subject_code,
                unit_code=context.task.unit_code,
                source_types=list(context.task.source_types),
                authority_tiers=list(context.task.authority_tiers),
                top_k=safe_top_k,
                timeout=self._timeout_seconds,
            )
            if not nodes:
                return "No matching knowledge-base evidence was found."
            sections: list[str] = []
            for node in nodes[:safe_top_k]:
                metadata = node.node.metadata
                card = metadata.get("knowledge_card")
                if isinstance(card, dict):
                    evidence_lines: list[str] = []
                    for item in metadata.get("evidence_items") or []:
                        if not isinstance(item, dict):
                            continue
                        citation = _citation_from_evidence(item)
                        source_index = context.add_citation(citation)
                        locator = (
                            f"page={citation.page}"
                            if citation.page is not None
                            else f"section={citation.section or '-'}"
                        )
                        evidence_lines.append(
                            f"[S{source_index}] role={citation.evidence_role or 'explanation'} "
                            f"authority={citation.authority_tier or '-'} {locator} "
                            f"source={citation.source}\n{citation.excerpt[:1600]}"
                        )
                    difficulty = card.get("difficulty") or {}
                    relations = [
                        (
                            f"{relation['relation_type']} {relation['direction']} "
                            f"{relation['code']} {relation['title']}"
                        )
                        for relation in card.get("relations", [])
                        if relation.get("relation_type") != "contains"
                    ]
                    sections.append(
                        "\n".join(
                            [
                                f"[KP {card['code']}] {card['title']}",
                                f"Path: {card.get('breadcrumb') or '-'}",
                                f"Learning objective: {card.get('definition') or '-'}",
                                (
                                    f"Difficulty: {difficulty.get('score', 0):.4f} "
                                    f"({difficulty.get('label', '-')}); "
                                    f"confidence={difficulty.get('confidence', 0):.2f}; "
                                    f"evidence_level={difficulty.get('evidence_level', '-')}"
                                ),
                                f"Difficulty basis: {difficulty.get('rationale') or '-'}",
                                (
                                    "Relations: "
                                    f"{'; '.join(relations) if relations else 'none recorded'}"
                                ),
                                "Evidence:",
                                *(
                                    evidence_lines
                                    or [
                                        "No source excerpt passed the requested source and "
                                        "authority filters."
                                    ]
                                ),
                            ]
                        )
                    )
                    continue
                citation = self._citation_factory(node)
                source_index = context.add_citation(citation)
                sections.append(
                    f"[S{source_index}] Ungrouped source evidence (not a knowledge point): "
                    f"source={citation.source} document_id={citation.document_id or '-'} "
                    f"page={citation.page} section={citation.section or '-'}\n"
                    f"{node.node.get_content().strip()[:4200]}"
                )
            return "\n\n".join(sections)[:24_000]

        return FunctionTool.from_defaults(
            async_fn=knowledge_search,
            name=self.name,
            description=(
                "Search curriculum knowledge-point cards backed only by approved syllabus, "
                "licensed textbook, and supplementary knowledge sources. Assessment and "
                "grading documents are never returned. Each [KP code] is a real curriculum "
                "objective; source chunks are labelled separately. Call this before giving a "
                "grounded answer and use returned [S#] markers in the final answer."
            ),
        )
