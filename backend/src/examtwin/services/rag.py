from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from examtwin.answering_agent.contracts import (
    AgentEventSink,
    AgentRunLedger,
    AnswerTask,
    QuestionImage,
    QuestionSpec,
)
from examtwin.answering_agent.factory import AnswerEvidenceReader, build_answering_runtime
from examtwin.answering_agent.finalization import FinalAnswerProvider
from examtwin.config import Settings
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.schemas.evidence import Citation
from examtwin.schemas.knowledge import AskRequest, AskResponse
from examtwin.services.ingestion import load_vector_index
from examtwin.services.knowledge import build_retrieval_cards, knowledge_cards_by_code
from examtwin.services.providers import (
    SiliconFlowReranker,
    build_embedding,
    build_final_answer_provider,
)
from examtwin.services.subject_context import SubjectContext
from examtwin.storage import ManagedObjectStore
from llama_index.core.schema import NodeWithScore, TextNode
from pypdf import PdfReader

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
        *,
        final_answer_provider: FinalAnswerProvider | None = None,
        object_store: ManagedObjectStore | None = None,
    ):
        self.settings = settings
        self.knowledge_repository = knowledge_repository
        self.documents = documents
        self.subject = subject
        self.final_answer_provider = final_answer_provider or build_final_answer_provider(settings)
        self.object_store = object_store

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
        top_n = top_k or self.settings.rerank_top_n
        embedding = build_embedding(self.settings)
        index = load_vector_index(self.settings, embedding)
        candidate_count = max(self.settings.similarity_top_k, top_n * 4)
        nodes = index.as_retriever(similarity_top_k=candidate_count).retrieve(question)
        filtered = [
            node
            for node in nodes
            if node.node.metadata.get("subject_code") == subject_code
            and (not unit_code or node.node.metadata.get("unit_code") == unit_code)
            and (not pair_key or node.node.metadata.get("pair_key") == pair_key)
            and (not source_types or node.node.metadata.get("source_type") in set(source_types))
            and (
                not authority_tiers
                or node.node.metadata.get("authority_tier") in set(authority_tiers)
            )
        ]
        if not filtered:
            return []
        reranked = SiliconFlowReranker(self.settings).rerank(
            question,
            filtered,
            top_n=min(max(top_n * 3, top_n), len(filtered)),
        )
        if self.knowledge_repository is None:
            return reranked[:top_n]
        build_ids = {
            str(node.node.metadata["index_build_id"])
            for node in reranked
            if node.node.metadata.get("index_build_id")
        }
        if len(build_ids) > 1:
            raise RuntimeError("Live vector alias returned nodes from multiple index builds")
        index_build_id = next(iter(build_ids), None)
        evidence_items = [
            {
                "excerpt": relevant_node_excerpt(node, question),
                "score": float(node.score or 0),
                "metadata": dict(node.node.metadata),
            }
            for node in reranked
        ]
        cards = build_retrieval_cards(
            self.knowledge_repository,
            question,
            evidence_items,
            subject_code=subject_code,
            index_build_id=index_build_id,
            unit_code=unit_code,
            limit=top_n,
        )
        for card in cards:
            card["references"] = [
                reference
                for reference in card.get("references", [])
                if (not source_types or reference.get("source_type") in set(source_types))
                and (not authority_tiers or reference.get("authority_tier") in set(authority_tiers))
            ]
        return [_card_node(card) for card in cards] or reranked[:top_n]

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
                source_types=tuple(request.source_types),
                authority_tiers=tuple(request.authority_tiers),
                top_k=request.top_k or self.settings.rerank_top_n,
                question_images=question_images,
            ),
            event_sink=event_sink,
            ledger=ledger,
        )
        citations = list(result.citations)
        codes = sorted(
            {citation.knowledge_code for citation in citations if citation.knowledge_code}
        )
        build_ids = {citation.index_build_id for citation in citations if citation.index_build_id}
        if len(build_ids) > 1:
            raise RuntimeError("Answer citations crossed vector index build versions")
        index_build_id = next(iter(build_ids), None)
        cards = (
            knowledge_cards_by_code(
                self.knowledge_repository,
                request.subject_code,
                codes,
                index_build_id=index_build_id,
            )
            if self.knowledge_repository is not None and codes
            else {}
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
            warnings=list(dict.fromkeys([*result.warnings, *calibration_warnings])),
        )
