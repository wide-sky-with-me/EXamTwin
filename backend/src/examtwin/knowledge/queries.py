from __future__ import annotations

import re
from typing import Any

from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.knowledge.projection import (
    _content_url,
    _deduplicate_references,
    _enrich_points,
    _knowledge_tokens,
    _node_type,
    evidence_role_for_source,
)


def list_knowledge_points(
    repository: KnowledgeRepository,
    *,
    subject_code: str,
    unit_code: str | None = None,
    strand: str | None = None,
    index_build_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = repository.points(
        subject_code=subject_code,
        unit_code=unit_code,
        strand=strand,
        include_root=False,
    )
    return _enrich_points(
        repository,
        rows,
        subject_code=subject_code,
        index_build_id=index_build_id,
    )


def knowledge_cards_by_code(
    repository: KnowledgeRepository,
    subject_code: str,
    codes: list[str],
    *,
    index_build_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    wanted = {code for code in codes if code}
    if not wanted:
        return {}
    rows = repository.points(subject_code=subject_code, codes=sorted(wanted))
    return {
        point["code"]: point
        for point in _enrich_points(
            repository,
            rows,
            subject_code=subject_code,
            index_build_id=index_build_id,
        )
    }


def match_knowledge_points(
    text: str,
    points: list[dict[str, Any]],
    *,
    limit: int = 4,
) -> list[tuple[float, dict[str, Any]]]:
    lowered = text.lower()
    text_tokens = _knowledge_tokens(text)
    scored: list[tuple[float, dict[str, Any]]] = []
    for point in points:
        code = str(point["code"])
        explicit = bool(
            re.search(rf"(?<![a-z0-9.]){re.escape(code.lower())}(?![a-z0-9.])", lowered)
        )
        title = str(point["title"])
        definition = str(
            point.get("definition") or point.get("features", {}).get("description", "")
        )
        title_tokens = _knowledge_tokens(title)
        definition_tokens = _knowledge_tokens(definition)
        title_overlap = len(text_tokens & title_tokens)
        definition_overlap = len(text_tokens & definition_tokens)
        title_coverage = title_overlap / max(1, len(title_tokens))
        definition_coverage = definition_overlap / max(1, min(len(definition_tokens), 12))
        score = 0.72 * title_coverage + 0.28 * min(1.0, definition_coverage)
        if title.lower() in lowered and len(title) >= 5:
            score = max(score, 0.96)
        if explicit:
            score = 2.0
        minimum_hits = 1 if len(title_tokens) <= 2 else 2
        if explicit or title.lower() in lowered or title_overlap >= minimum_hits or score >= 0.3:
            scored.append((score, point))
    scored.sort(
        key=lambda item: (
            -item[0],
            0 if _node_type(item[1]) == "learning_objective" else 1,
            item[1]["code"],
        )
    )
    return scored[: max(1, limit)]


def build_retrieval_cards(
    repository: KnowledgeRepository,
    question: str,
    evidence_items: list[dict[str, Any]],
    *,
    subject_code: str,
    index_build_id: str | None = None,
    unit_code: str | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    catalog = [
        point
        for point in list_knowledge_points(
            repository,
            subject_code=subject_code,
            unit_code=unit_code,
            index_build_id=index_build_id,
        )
        if _node_type(point) == "learning_objective"
    ]
    if not catalog:
        catalog = [
            point
            for point in list_knowledge_points(
                repository,
                subject_code=subject_code,
                unit_code=unit_code,
                index_build_id=index_build_id,
            )
            if _node_type(point) == "topic"
        ]
    catalog_by_code = {point["code"]: point for point in catalog}
    question_matches = match_knowledge_points(
        question,
        catalog,
        limit=max(20, limit * 4),
    )
    selected: dict[str, tuple[float, dict[str, Any]]] = {
        point["code"]: (score, point) for score, point in question_matches
    }

    for evidence in evidence_items:
        metadata = evidence.get("metadata", {})
        metadata_codes = metadata.get("knowledge_codes") or []
        if isinstance(metadata_codes, str):
            metadata_codes = [metadata_codes]
        primary_code = metadata.get("knowledge_code")
        if primary_code:
            metadata_codes = [primary_code, *metadata_codes]
        evidence_relevance = min(1.0, max(0.0, float(evidence.get("score") or 0)))
        match_confidences = metadata.get("knowledge_match_confidence") or {}
        unique_codes = list(dict.fromkeys(str(code) for code in metadata_codes if code))
        for code in unique_codes:
            point = catalog_by_code.get(str(code))
            if point is None:
                continue
            if metadata.get("node_kind") == "knowledge_point" and code == str(primary_code):
                linked_score = 1.0 + evidence_relevance
            else:
                link_confidence = min(
                    1.0,
                    max(0.0, float(match_confidences.get(code, 0.3))),
                )
                linked_score = 0.72 * evidence_relevance + 0.28 * link_confidence
                if code == str(primary_code):
                    linked_score = min(0.99, linked_score + 0.03)
            existing = selected.get(point["code"])
            if existing is None or linked_score > existing[0]:
                selected[point["code"]] = (linked_score, point)
        for score, point in match_knowledge_points(
            str(evidence.get("excerpt") or ""),
            catalog,
            limit=2,
        ):
            weighted = min(1.0, score) * max(0.2, float(evidence.get("score") or 0.5))
            existing = selected.get(point["code"])
            if existing is None or weighted > existing[0]:
                selected[point["code"]] = (weighted, point)

    ranked = sorted(
        selected.values(),
        key=lambda item: (-item[0], item[1]["code"]),
    )[: max(1, limit)]
    cards: list[dict[str, Any]] = []
    for match_score, point in ranked:
        references = list(point.get("references", []))
        point_terms = _knowledge_tokens(f"{point['title']} {point['definition']}")
        evidence_score = 0.0
        for evidence in evidence_items:
            metadata = evidence.get("metadata", {})
            if metadata.get("node_kind") == "knowledge_point":
                continue
            metadata_codes = metadata.get("knowledge_codes") or []
            if isinstance(metadata_codes, str):
                metadata_codes = [metadata_codes]
            if metadata.get("knowledge_code"):
                metadata_codes = [metadata["knowledge_code"], *metadata_codes]
            excerpt = re.sub(
                r"\s+",
                " ",
                str(evidence.get("excerpt") or ""),
            ).strip()
            overlap = len(point_terms & _knowledge_tokens(excerpt))
            explicitly_linked = point["code"] in {str(code) for code in metadata_codes}
            if not explicitly_linked and overlap == 0:
                continue
            page = metadata.get("page")
            try:
                page = int(page) if page is not None else None
            except (TypeError, ValueError):
                page = None
            section = metadata.get("section")
            section_path = metadata.get("section_path") or []
            if isinstance(section_path, str):
                section_path = [section_path]
            source_type = metadata.get("source_type")
            score = float(evidence.get("score") or 0)
            evidence_score = max(evidence_score, score)
            references.append(
                {
                    "source": metadata.get("source") or metadata.get("filename") or "unknown",
                    "document_id": metadata.get("document_id"),
                    "page": page,
                    "source_type": source_type,
                    "authority_tier": metadata.get("authority_tier"),
                    "pair_key": metadata.get("pair_key") or None,
                    "unit_code": metadata.get("unit_code") or None,
                    "score": score or None,
                    "excerpt": excerpt[:1200],
                    "section": section,
                    "section_path": section_path,
                    "knowledge_code": point["code"],
                    "evidence_role": evidence_role_for_source(source_type, section),
                    "content_url": _content_url(
                        metadata.get("document_id"),
                        page=page,
                        query=str(section or point["title"]),
                    ),
                }
            )
        card = dict(point)
        card["index_build_id"] = index_build_id
        card["references"] = _deduplicate_references(references)[:6]
        card["retrieval_score"] = round(max(match_score, evidence_score), 4)
        cards.append(card)
    return cards


def list_relations(
    repository: KnowledgeRepository,
    *,
    subject_code: str | None = None,
) -> list[dict[str, Any]]:
    return repository.relation_projection(subject_code=subject_code)
