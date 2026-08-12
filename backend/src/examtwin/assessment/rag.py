from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.core.vector_stores.types import VectorStoreQueryMode
from pypdf import PdfReader

from examtwin.assessment.answering_agent.contracts import (
    AgentEventSink,
    AgentRunLedger,
    AnswerTask,
    QuestionImage,
    QuestionSpec,
)
from examtwin.assessment.answering_agent.factory import (
    AnswerEvidenceReader,
    build_answering_runtime,
)
from examtwin.assessment.answering_agent.finalization import FinalAnswerProvider
from examtwin.assessment.providers import build_final_answer_provider
from examtwin.contracts.evidence import Citation
from examtwin.contracts.knowledge import AskRequest, AskResponse
from examtwin.knowledge.public import (
    DocumentBlockRepository,
    GraphRepository,
    KnowledgeRepository,
    RetrievalTraceRepository,
    build_retrieval_cards,
    knowledge_cards_by_code,
    load_vector_index,
    retrieval_filters,
)
from examtwin.platform.config import Settings
from examtwin.platform.database.session import utcnow
from examtwin.platform.providers import SiliconFlowReranker, build_embedding
from examtwin.platform.storage import ManagedObjectStore
from examtwin.subjects.public import SubjectContext

STOP_WORDS = {
    "about",
    "after",
    "also",
    "answer",
    "available",
    "been",
    "before",
    "could",
    "from",
    "have",
    "into",
    "marks",
    "question",
    "students",
    "that",
    "their",
    "there",
    "these",
    "this",
    "those",
    "using",
    "were",
    "which",
    "with",
    "would",
}
logger = logging.getLogger(__name__)


def _tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in STOP_WORDS}


def relevant_node_excerpt(
    node: NodeWithScore,
    query: str,
    *,
    max_chars: int = 4_200,
) -> str:
    content = node.node.get_content().strip()
    if node.node.metadata.get("block_kind") != "table":
        return content[:max_chars]

    rows = re.findall(
        r"<tr\b[^>]*>.*?</tr>",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not rows:
        return str(node.node.metadata.get("retrieval_text") or content)[:max_chars]
    query_tokens = _tokens(query)
    scored: list[tuple[int, int, str]] = []
    for index, row in enumerate(rows):
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", row)).strip()
        overlap = len(query_tokens & _tokens(plain))
        if overlap:
            scored.append((overlap, index, row))
    if not scored:
        return str(node.node.metadata.get("retrieval_text") or content)[:max_chars]

    first_plain = re.sub(r"<[^>]+>", " ", rows[0]).lower()
    header = (
        rows[0]
        if "<th" in rows[0].lower()
        or ("content" in first_plain and "additional information" in first_plain)
        or ("question" in first_plain and ("mark scheme" in first_plain or "marks" in first_plain))
        else None
    )
    selected: list[tuple[int, str]] = []
    used = len("<table></table>") + (len(header) if header else 0)
    for _, index, row in sorted(scored, key=lambda item: (-item[0], item[1])):
        if header is not None and index == 0:
            continue
        if selected and used + len(row) > max_chars:
            continue
        selected.append((index, row))
        used += len(row)
        if used >= max_chars:
            break
    selected.sort(key=lambda item: item[0])
    body = "".join(([header] if header else []) + [row for _, row in selected])
    return f"<table>{body}</table>"


@lru_cache(maxsize=32)
def _pdf_page_tokens(source: str) -> tuple[frozenset[str], ...]:
    path = Path(source)
    if not path.exists() or path.suffix.lower() != ".pdf":
        return ()
    try:
        return tuple(
            frozenset(_tokens(page.extract_text() or "")) for page in PdfReader(path).pages
        )
    except Exception:
        return ()


def infer_pdf_page(source: str, text: str) -> int | None:
    needle = _tokens(re.sub(r"<[^>]+>", " ", text))
    if len(needle) < 5:
        return None
    candidates = _pdf_page_tokens(source)
    if not candidates:
        return None
    scores = [len(needle & page) / len(needle) for page in candidates]
    best = max(range(len(scores)), key=scores.__getitem__)
    return best + 1 if scores[best] >= 0.08 else None


def citation_from_node(node: NodeWithScore) -> Citation:
    metadata = node.node.metadata
    text = node.node.get_content().strip()
    page_match = re.search(r"(?:<!--\s*page:|##\s*Page\s+)(\d+)", text, re.IGNORECASE)
    excerpt_source = str(metadata.get("retrieval_text") or text)
    excerpt = re.sub(r"\s+", " ", excerpt_source)[:360]
    page = metadata.get("page")
    source = metadata.get("source") or metadata.get("filename") or "unknown"
    if page is None:
        page = infer_pdf_page(source, text)
    try:
        section_path = metadata.get("section_path") or []
        if isinstance(section_path, str):
            section_path = [section_path]
    except TypeError:
        section_path = []
    document_id = metadata.get("document_id")
    content_url = metadata.get("content_url")
    if not content_url and document_id:
        root = f"/sources/{quote(str(document_id), safe='')}/context"
        if page is not None:
            content_url = f"{root}?page={int(page)}"
        elif metadata.get("section"):
            content_url = f"{root}?query={quote(str(metadata['section'])[:160])}"
        else:
            content_url = root
    return Citation(
        source=source,
        document_id=document_id,
        page=int(page) if page is not None else (int(page_match.group(1)) if page_match else None),
        source_type=metadata.get("source_type"),
        authority_tier=metadata.get("authority_tier"),
        pair_key=metadata.get("pair_key") or None,
        score=round(float(node.score), 4) if node.score is not None else None,
        excerpt=excerpt,
        section=metadata.get("section"),
        section_path=section_path,
        knowledge_code=metadata.get("knowledge_code"),
        index_build_id=metadata.get("index_build_id"),
        evidence_role=metadata.get("evidence_role"),
        content_url=content_url,
    )


def _render_card(card: dict) -> str:
    difficulty = card["difficulty"]
    relations = [
        (
            f"{relation['relation_type']} ({relation['direction']}): "
            f"{relation['code']} {relation['title']} "
            f"[confidence={relation['confidence']:.2f}]"
        )
        for relation in card.get("relations", [])
        if relation["relation_type"] != "contains"
    ]
    return "\n".join(
        [
            f"Knowledge point: {card['code']} — {card['title']}",
            f"Curriculum path: {card['breadcrumb']}",
            f"Learning objective: {card['definition']}",
            (
                f"Difficulty: {difficulty['score']:.4f} ({difficulty['label']}), "
                f"confidence={difficulty['confidence']:.2f}, "
                f"evidence_level={difficulty['evidence_level']}"
            ),
            f"Difficulty basis: {difficulty['rationale']}",
            f"Relations: {'; '.join(relations) if relations else 'none recorded'}",
        ]
    )


def _card_node(card: dict) -> NodeWithScore:
    references = card.get("references", [])
    primary = references[0] if references else {}
    metadata = {
        "node_kind": "knowledge_card",
        "subject_code": card.get("subject_code") or str(card["id"]).split(":", 1)[0],
        "unit_code": card.get("unit_code") or primary.get("unit_code") or "",
        "knowledge_code": card["code"],
        "knowledge_card": card,
        "evidence_items": references,
        "source": primary.get("source") or card["source_ref"],
        "document_id": primary.get("document_id"),
        "page": primary.get("page"),
        "section": primary.get("section") or card["title"],
        "section_path": primary.get("section_path") or [item["title"] for item in card["path"]],
        "source_type": primary.get("source_type") or "syllabus",
        "authority_tier": primary.get("authority_tier") or "official",
        "pair_key": primary.get("pair_key") or "",
        "evidence_role": primary.get("evidence_role") or "definition",
        "content_url": primary.get("content_url"),
        "index_build_id": card.get("index_build_id"),
    }
    return NodeWithScore(
        node=TextNode(
            id_=f"retrieval-card:{card['id']}",
            text=_render_card(card),
            metadata=metadata,
        ),
        score=float(card.get("retrieval_score") or 0),
    )


def calibrate_evidence_confidence(
    citations: list[Citation],
    *,
    claimed_confidence: float,
    claimed_grounded: bool,
    knowledge_evidence_levels: list[str] | None = None,
    mark_scheme_expected: bool = False,
) -> tuple[float, bool, list[str]]:
    warnings: list[str] = []
    if not citations:
        return 0.2, False, ["没有检索到可引用原文，答案不能标记为知识库已支撑。"]

    locatable = [
        citation
        for citation in citations
        if citation.page is not None or citation.section or citation.content_url
    ]
    card_linked = [citation for citation in citations if citation.knowledge_code]
    authoritative = [
        citation
        for citation in citations
        if citation.authority_tier in {"official", "licensed_core", "licensed"}
    ]
    mark_schemes = [citation for citation in citations if citation.source_type == "mark_scheme"]

    cap = 0.96
    grounded = claimed_grounded
    if not card_linked:
        cap = min(cap, 0.58)
        grounded = False
        warnings.append("检索结果未映射到明确课程知识点，不能把普通文本片段当作知识点。")
    if not locatable:
        cap = min(cap, 0.55)
        grounded = False
        warnings.append("参考内容缺少页码或章节定位，无法复核完整原文。")
    if not authoritative:
        cap = min(cap, 0.68)
        warnings.append("参考内容缺少官方或已授权核心资料，置信度已下调。")
    if knowledge_evidence_levels and all(level == "D" for level in knowledge_evidence_levels):
        cap = min(cap, 0.82)
        warnings.append("知识点难度仍为 D 级冷启动估计，尚未由官方题目统计校准。")
    if mark_scheme_expected and not mark_schemes:
        cap = min(cap, 0.86)
        warnings.append("本次未命中对应 mark scheme，不能声称已按官方评分标准验证。")

    return round(min(max(0.0, claimed_confidence), cap), 4), grounded, warnings


class RagService:
    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        knowledge_repository: KnowledgeRepository | None = None,
        documents: AnswerEvidenceReader | None = None,
        trace_repository: RetrievalTraceRepository | None = None,
        block_repository: DocumentBlockRepository | None = None,
        graph_repository: GraphRepository | None = None,
        *,
        final_answer_provider: FinalAnswerProvider | None = None,
        object_store: ManagedObjectStore | None = None,
    ):
        self.settings = settings
        self.knowledge_repository = knowledge_repository
        self.documents = documents
        self.trace_repository = trace_repository
        self.block_repository = block_repository
        self.graph_repository = graph_repository
        self.subject = subject
        self.final_answer_provider = final_answer_provider or build_final_answer_provider(settings)
        self.object_store = object_store

    @staticmethod
    def _in_scope(
        node: NodeWithScore,
        *,
        subject_code: str,
        unit_code: str | None,
        pair_key: str | None,
        source_types: set[str],
        authority_tiers: set[str],
    ) -> bool:
        metadata = node.node.metadata
        return bool(
            metadata.get("subject_code") == subject_code
            and (not unit_code or metadata.get("unit_code") in {"", unit_code})
            and (not pair_key or metadata.get("pair_key") == pair_key)
            and (not source_types or metadata.get("source_type") in source_types)
            and (not authority_tiers or metadata.get("authority_tier") in authority_tiers)
            and metadata.get("source_role") in {"core_knowledge", "supplementary_knowledge"}
        )

    def _expand_parent_context(
        self,
        nodes: list[NodeWithScore],
    ) -> list[NodeWithScore]:
        if self.block_repository is None:
            return nodes
        grouped: dict[str, list[str]] = {}
        for node in nodes:
            metadata = node.node.metadata
            build_id = metadata.get("index_build_id")
            parent_id = metadata.get("parent_block_id")
            if build_id and parent_id:
                grouped.setdefault(str(build_id), []).append(str(parent_id))
        parents: dict[str, dict[str, object]] = {}
        for build_id, parent_ids in grouped.items():
            parents.update(self.block_repository.parents(build_id, parent_ids))
        expanded: list[NodeWithScore] = []
        for node in nodes:
            parent = parents.get(str(node.node.metadata.get("parent_block_id") or ""))
            if parent is None:
                expanded.append(node)
                continue
            metadata = {**node.node.metadata, "matched_child_text": node.node.get_content()}
            expanded.append(
                NodeWithScore(
                    node=TextNode(
                        id_=node.node.node_id,
                        text=str(parent["content"]),
                        metadata=metadata,
                    ),
                    score=node.score,
                )
            )
        return expanded

    def _raw_fallbacks(
        self,
        reranked: list[NodeWithScore],
        cards: list[dict],
    ) -> list[NodeWithScore]:
        represented = {
            (
                reference.get("document_id"),
                reference.get("page"),
                reference.get("section"),
            )
            for card in cards
            for reference in card.get("references", [])
        }
        fallbacks: list[NodeWithScore] = []
        seen: set[tuple[object, object, object]] = set()
        for node in reranked:
            metadata = node.node.metadata
            if metadata.get("node_kind") not in {None, "evidence_chunk"}:
                continue
            key = (
                metadata.get("document_id"),
                metadata.get("page"),
                metadata.get("section"),
            )
            if key in represented or key in seen:
                continue
            seen.add(key)
            fallbacks.append(node)
            if len(fallbacks) >= self.settings.retrieval_raw_fallback_count:
                break
        return fallbacks

    @staticmethod
    def _filter_cards_to_scope(
        cards: list[dict],
        *,
        pair_key: str | None,
        source_types: set[str],
        authority_tiers: set[str],
    ) -> list[dict]:
        scoped: list[dict] = []
        explicit_evidence_scope = bool(pair_key or source_types or authority_tiers)
        for card in cards:
            references = [
                reference
                for reference in card.get("references", [])
                if (not pair_key or reference.get("pair_key") == pair_key)
                and (not source_types or reference.get("source_type") in source_types)
                and (not authority_tiers or reference.get("authority_tier") in authority_tiers)
            ]
            if explicit_evidence_scope and not references:
                continue
            scoped_card = dict(card)
            scoped_card["references"] = references
            scoped.append(scoped_card)
        return scoped

    def _record_trace(self, values: dict[str, object]) -> None:
        if not self.settings.retrieval_trace_enabled or self.trace_repository is None:
            return
        try:
            self.trace_repository.record(values)
        except Exception:
            logger.warning("retrieval_trace_write_failed", exc_info=True)

    def retrieve(
        self,
        question: str,
        *,
        subject_code: str,
        unit_code: str | None = None,
        pair_key: str | None = None,
        source_types: list[str] | None = None,
        authority_tiers: list[str] | None = None,
        top_k: int | None = None,
    ) -> list[NodeWithScore]:
        self.subject.require(subject_code)
        started = time.perf_counter()
        top_n = top_k or self.settings.rerank_top_n
        candidate_count = max(self.settings.similarity_top_k, top_n * 4)
        source_type_set = set(source_types or ())
        authority_tier_set = set(authority_tiers or ())
        trace: dict[str, object] = {
            "id": str(uuid.uuid4()),
            "subject_code": subject_code,
            "query_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "query_text": question[:2000],
            "filters_json": json.dumps(
                {
                    "unit_code": unit_code,
                    "pair_key": pair_key,
                    "source_types": sorted(source_type_set),
                    "authority_tiers": sorted(authority_tier_set),
                },
                ensure_ascii=False,
            ),
            "candidate_limit": candidate_count,
            "candidate_count": 0,
            "postfilter_count": 0,
            "reranked_count": 0,
            "card_count": 0,
            "raw_fallback_count": 0,
            "result_count": 0,
            "index_build_id": None,
            "result_json": "[]",
            "duration_ms": 0.0,
            "status": "failed",
            "error": None,
            "created_at": utcnow(),
        }
        try:
            retrieval_question = question
            if self.graph_repository is not None and self.subject.graph_version_id:
                expansion_terms = self.graph_repository.expansion_terms(
                    self.subject.graph_version_id,
                    question,
                )
                if expansion_terms:
                    retrieval_question = f"{question}\nRelated curriculum terms: " + "; ".join(
                        expansion_terms
                    )
            embedding = build_embedding(self.settings)
            collections = self.subject.vector_collections or (
                self.settings.qdrant_collection_alias,
            )
            nodes_by_id: dict[str, NodeWithScore] = {}
            retrieval_modes: set[str] = set()
            for collection in collections:
                collection_settings = self.settings.model_copy(
                    update={
                        "qdrant_collection": collection,
                        "qdrant_collection_alias": collection,
                    }
                )
                index = load_vector_index(collection_settings, embedding)
                hybrid = bool(getattr(index.vector_store, "enable_hybrid", False))
                retrieval_modes.add("hybrid" if hybrid else "dense_compat")
                retriever = index.as_retriever(
                    similarity_top_k=candidate_count,
                    sparse_top_k=candidate_count,
                    hybrid_top_k=candidate_count,
                    alpha=self.settings.retrieval_hybrid_alpha,
                    vector_store_query_mode=(
                        VectorStoreQueryMode.HYBRID if hybrid else VectorStoreQueryMode.DEFAULT
                    ),
                    filters=retrieval_filters(
                        subject_code=subject_code,
                        unit_code=unit_code,
                        pair_key=pair_key,
                        source_types=tuple(source_type_set),
                        authority_tiers=tuple(authority_tier_set),
                        source_roles=("core_knowledge", "supplementary_knowledge"),
                    ),
                )
                for node in retriever.retrieve(retrieval_question):
                    current = nodes_by_id.get(node.node.node_id)
                    if current is None or float(node.score or 0) > float(current.score or 0):
                        nodes_by_id[node.node.node_id] = node
            trace["retrieval_mode"] = "+".join(sorted(retrieval_modes))
            nodes = list(nodes_by_id.values())
            trace["candidate_count"] = len(nodes)
            filtered = [
                node
                for node in nodes
                if self._in_scope(
                    node,
                    subject_code=subject_code,
                    unit_code=unit_code,
                    pair_key=pair_key,
                    source_types=source_type_set,
                    authority_tiers=authority_tier_set,
                )
            ]
            trace["postfilter_count"] = len(filtered)
            if not filtered:
                trace.update(status="empty", retrieval_mode=trace["retrieval_mode"])
                return []
            reranked = SiliconFlowReranker(self.settings).rerank(
                question,
                filtered,
                top_n=min(max(top_n * 3, top_n), len(filtered)),
            )
            reranked = self._expand_parent_context(reranked)
            trace["reranked_count"] = len(reranked)
            if self.knowledge_repository is None:
                results = reranked[:top_n]
                trace["result_count"] = len(results)
                trace["status"] = "succeeded"
                return results
            build_ids = {
                str(node.node.metadata["index_build_id"])
                for node in reranked
                if node.node.metadata.get("index_build_id")
            }
            index_build_id = next(iter(build_ids), None) if len(build_ids) == 1 else None
            trace["index_build_id"] = index_build_id or json.dumps(
                sorted(build_ids), ensure_ascii=False
            )
            grouped_nodes: dict[str | None, list[NodeWithScore]] = {}
            for node in reranked:
                build_id = node.node.metadata.get("index_build_id")
                grouped_nodes.setdefault(str(build_id) if build_id else None, []).append(node)
            cards_by_id: dict[str, dict] = {}
            for build_id, build_nodes in grouped_nodes.items():
                evidence_items = [
                    {
                        "excerpt": relevant_node_excerpt(node, question),
                        "score": float(node.score or 0),
                        "metadata": dict(node.node.metadata),
                    }
                    for node in build_nodes
                ]
                for card in build_retrieval_cards(
                    self.knowledge_repository,
                    question,
                    evidence_items,
                    subject_code=subject_code,
                    index_build_id=build_id,
                    unit_code=unit_code,
                    limit=top_n,
                ):
                    existing = cards_by_id.get(str(card["id"]))
                    if existing is None or float(card.get("retrieval_score") or 0) > float(
                        existing.get("retrieval_score") or 0
                    ):
                        cards_by_id[str(card["id"])] = card
            cards = sorted(
                cards_by_id.values(),
                key=lambda card: float(card.get("retrieval_score") or 0),
                reverse=True,
            )[:top_n]
            cards = self._filter_cards_to_scope(
                cards,
                pair_key=pair_key,
                source_types=source_type_set,
                authority_tiers=authority_tier_set,
            )
            if cards:
                raw_fallbacks = self._raw_fallbacks(reranked, cards)
                results = [*[_card_node(card) for card in cards], *raw_fallbacks]
            else:
                raw_fallbacks = reranked[:top_n]
                results = raw_fallbacks
            trace.update(
                card_count=len(cards),
                raw_fallback_count=len(raw_fallbacks),
                result_count=len(results),
                status="succeeded",
            )
            trace["result_json"] = json.dumps(
                [
                    {
                        "node_id": node.node.node_id,
                        "score": node.score,
                        "node_kind": node.node.metadata.get("node_kind"),
                        "document_id": node.node.metadata.get("document_id"),
                        "page": node.node.metadata.get("page"),
                        "knowledge_code": node.node.metadata.get("knowledge_code"),
                    }
                    for node in results
                ],
                ensure_ascii=False,
            )
            return results
        except Exception as error:
            trace["error"] = str(error)[:2000]
            raise
        finally:
            trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
            self._record_trace(trace)

    def ask(
        self,
        request: AskRequest,
        *,
        question_images: tuple[QuestionImage, ...] = (),
        question_number: str | None = None,
        question_spec: QuestionSpec | None = None,
        visual_request_text: str | None = None,
        event_sink: AgentEventSink | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> AskResponse:
        forbidden_sources = set(request.source_types) & {
            "question_paper",
            "mark_scheme",
            "examiner_report",
            "answer_booklet",
            "specimen_paper",
        }
        if forbidden_sources:
            raise ValueError(
                "知识问答不能检索试卷、Mark Scheme 或考官报告；评分资料只允许在独立评分阶段使用"
            )
        self.subject.require(request.subject_code)
        runtime = build_answering_runtime(
            self.settings,
            retriever=self.retrieve,
            citation_factory=citation_from_node,
            documents=self.documents,
            final_answer_provider=self.final_answer_provider,
            object_store=self.object_store,
            subject_package=self.subject.package,
        )
        result = runtime.solve(
            AnswerTask(
                question=request.question,
                question_number=question_number,
                question_spec=question_spec or QuestionSpec(),
                visual_request_text=visual_request_text,
                subject_code=request.subject_code,
                unit_code=request.unit_code,
                pair_key=request.pair_key,
                source_booklet_document_id=request.source_booklet_document_id,
                source_booklet_checksum=request.source_booklet_checksum,
                source_types=tuple(request.source_types),
                authority_tiers=tuple(request.authority_tiers),
                top_k=request.top_k or self.settings.rerank_top_n,
                question_images=question_images,
                knowledge_base_version_ids=self.subject.knowledge_base_version_ids,
                graph_version_id=self.subject.graph_version_id,
            ),
            event_sink=event_sink,
            ledger=ledger,
        )
        citations = list(result.citations)
        codes = sorted(
            {citation.knowledge_code for citation in citations if citation.knowledge_code}
        )
        build_ids = {citation.index_build_id for citation in citations if citation.index_build_id}
        cards: dict[str, dict] = {}
        if self.knowledge_repository is not None and codes:
            for build_id in build_ids or {None}:
                cards.update(
                    knowledge_cards_by_code(
                        self.knowledge_repository,
                        request.subject_code,
                        codes,
                        index_build_id=build_id,
                    )
                )
        calibrated_confidence, calibrated_grounded, calibration_warnings = (
            calibrate_evidence_confidence(
                citations,
                claimed_confidence=result.confidence,
                claimed_grounded=result.grounded,
                knowledge_evidence_levels=[
                    str(cards[code]["evidence_level"]) for code in codes if code in cards
                ],
                mark_scheme_expected="mark_scheme" in request.source_types,
            )
        )
        return AskResponse(
            answer_markdown=result.answer_markdown,
            citations=citations,
            diagrams=list(result.diagrams),
            images=list(result.images),
            confidence=calibrated_confidence,
            grounded=calibrated_grounded,
            knowledge_base_version_ids=list(self.subject.knowledge_base_version_ids),
            graph_version_id=self.subject.graph_version_id,
            warnings=list(dict.fromkeys([*result.warnings, *calibration_warnings])),
        )
