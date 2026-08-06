from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from examtwin.persistence.knowledge_repository import KnowledgeRepository

KNOWLEDGE_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "apply",
    "from",
    "into",
    "knowledge",
    "of",
    "the",
    "this",
    "to",
    "use",
    "using",
    "with",
}
AUTHORITY_ORDER = {
    "official": 0,
    "licensed_core": 1,
    "licensed": 1,
    "supplementary": 2,
}


def _load_features(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _knowledge_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.lower())
        if token not in KNOWLEDGE_STOP_WORDS
    }


def _node_type(point: dict[str, Any]) -> str:
    return str(point.get("features", {}).get("node_type") or "topic")


def _difficulty_summary(point: dict[str, Any]) -> dict[str, Any]:
    features = point.get("features", {})
    method = str(features.get("difficulty_method") or "weighted-normalized-difficulty-v1")
    evidence_level = str(point["evidence_level"])
    confidence = float(point["difficulty_confidence"])
    if method == "model-evidence-direct-v1":
        basis = "AI 结合官方课纲与授权教材原文，在同一 Unit 内比较后直接给出的冷启动评级"
    elif features.get("facility_rate") is not None:
        basis = "已纳入官方历史正确率"
    elif evidence_level in {"A", "B"}:
        basis = "依据官方课程或考试证据"
    else:
        basis = "依据历史难度观测进行估计"
    if evidence_level == "D":
        caveat = "，尚无官方题目统计校准"
    else:
        caveat = ""
    numeric_features = {
        key: value
        for key, value in features.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    model_rationale = str(features.get("difficulty_rationale") or "").strip()
    rationale = f"{basis}{caveat}；当前置信度 {confidence:.2f}，证据等级 {evidence_level}。"
    if model_rationale:
        rationale = f"{rationale} 依据：{model_rationale}"
    return {
        "score": float(point["difficulty_score"]),
        "label": point["difficulty_label"],
        "confidence": confidence,
        "evidence_level": evidence_level,
        "method": method,
        "rationale": rationale,
        "features": numeric_features,
    }


def _content_url(
    document_id: str | None,
    *,
    page: int | None = None,
    query: str = "",
) -> str | None:
    if not document_id:
        return None
    root = f"/sources/{quote(document_id, safe='')}/context"
    if page is not None:
        return f"{root}?page={page}"
    return f"{root}?query={quote(query[:160])}" if query else root


def evidence_role_for_source(source_type: str | None, section: str | None = None) -> str:
    if source_type == "syllabus":
        return "definition"
    if source_type == "question_paper":
        return "assessment"
    if source_type == "mark_scheme":
        return "marking"
    if source_type == "textbook" and section and "example" in section.lower():
        return "worked_example"
    return "explanation"


def _deduplicate_references(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for reference in references:
        excerpt_key = re.sub(r"\s+", " ", str(reference.get("excerpt", ""))).strip()[:240]
        key = (
            reference.get("document_id"),
            reference.get("source"),
            reference.get("page"),
            reference.get("section"),
            excerpt_key,
        )
        existing = unique.get(key)
        if existing is None or float(reference.get("score") or 0) > float(
            existing.get("score") or 0
        ):
            unique[key] = reference
    return sorted(
        unique.values(),
        key=lambda item: (
            AUTHORITY_ORDER.get(str(item.get("authority_tier")), 9),
            {
                "definition": 0,
                "explanation": 1,
                "worked_example": 2,
                "assessment": 3,
                "marking": 4,
            }.get(str(item.get("evidence_role")), 9),
            -(float(item.get("score") or 0)),
            str(item.get("source") or ""),
            int(item.get("page") or 0),
        ),
    )


def _references_by_point(
    repository: KnowledgeRepository,
    point_ids: list[str],
    point_by_id: dict[str, dict[str, Any]],
    *,
    index_build_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    references: dict[str, list[dict[str, Any]]] = {point_id: [] for point_id in point_ids}
    if not point_ids:
        return references
    rows = repository.evidence(point_ids, index_build_id=index_build_id)
    for row in rows:
        try:
            section_path = json.loads(row["section_path_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            section_path = []
        point = point_by_id[row["knowledge_point_id"]]
        references[row["knowledge_point_id"]].append(
            {
                "source": row["source"] or row["source_ref"],
                "document_id": row["document_id"],
                "page": row["page"],
                "source_type": row["source_type"],
                "authority_tier": row["authority_tier"],
                "pair_key": row["pair_key"],
                "score": float(row["confidence"]),
                "excerpt": row["excerpt"],
                "section": row["section"],
                "section_path": section_path if isinstance(section_path, list) else [],
                "knowledge_code": point["code"],
                "evidence_role": row["evidence_role"],
                "content_url": _content_url(
                    row["document_id"],
                    page=row["page"],
                    query=row["section"] or point["title"],
                ),
            }
        )

    source_documents = repository.converted_sources()
    by_source: dict[str, dict[str, Any]] = {}
    for document in source_documents:
        by_source[str(document["path"])] = document
        by_source[str(document["filename"])] = document
        by_source[Path(str(document["path"])).name] = document
    for point_id in point_ids:
        if references[point_id]:
            references[point_id] = _deduplicate_references(references[point_id])
            continue
        point = point_by_id[point_id]
        source_ref = str(point["source_ref"])
        source, _, fragment = source_ref.partition("#page=")
        try:
            page = int(fragment) if fragment else None
        except ValueError:
            page = None
        document = by_source.get(source) or by_source.get(Path(source).name)
        definition = str(point.get("definition") or point["title"])
        references[point_id] = [
            {
                "source": document["path"] if document else source,
                "document_id": document["id"] if document else None,
                "page": page,
                "source_type": document["source_type"] if document else "syllabus",
                "authority_tier": document["authority_tier"] if document else "official",
                "pair_key": document["pair_key"] if document else None,
                "score": 1.0,
                "excerpt": definition[:1000],
                "section": point["title"],
                "section_path": [item["title"] for item in point.get("path", [])],
                "knowledge_code": point["code"],
                "evidence_role": "definition",
                "content_url": _content_url(
                    document["id"] if document else None,
                    page=page,
                    query=point["title"],
                ),
            }
        ]
    return references


def _enrich_points(
    repository: KnowledgeRepository,
    rows: list[dict[str, Any]],
    *,
    subject_code: str,
    index_build_id: str | None = None,
) -> list[dict[str, Any]]:
    point_by_id: dict[str, dict[str, Any]] = {}

    def add_points(items: list[dict[str, Any]]) -> None:
        for raw in items:
            point = dict(raw)
            point["features"] = _load_features(point.get("features_json"))
            point["definition"] = str(
                point["features"].get("description") or point["title"]
            ).strip()
            point_by_id[point["id"]] = point

    add_points(rows)
    selected_ids = list(point_by_id)
    relation_rows = repository.relations(subject_code=subject_code, point_ids=selected_ids)
    related_ids = {
        point_id
        for relation in relation_rows
        for point_id in (relation["source_id"], relation["target_id"])
        if point_id not in point_by_id
    }
    if related_ids:
        add_points(repository.points(subject_code=subject_code, ids=sorted(related_ids)))

    while True:
        missing_parents = {
            str(point["parent_id"])
            for point in point_by_id.values()
            if point.get("parent_id") and point["parent_id"] not in point_by_id
        }
        if not missing_parents:
            break
        parents = repository.points(subject_code=subject_code, ids=sorted(missing_parents))
        if not parents:
            break
        add_points(parents)

    for raw in point_by_id.values():
        if raw.get("subject_code") != subject_code:
            raise ValueError("Knowledge projection crossed a subject boundary")
    relations: dict[str, list[dict[str, Any]]] = {point_id: [] for point_id in point_by_id}
    for relation in relation_rows:
        source = point_by_id.get(relation["source_id"])
        target = point_by_id.get(relation["target_id"])
        if not source or not target:
            continue
        relations[source["id"]].append(
            {
                "relation_type": relation["relation_type"],
                "direction": "outgoing",
                "code": target["code"],
                "title": target["title"],
                "node_type": _node_type(target),
                "confidence": float(relation["confidence"]),
                "source_ref": relation["source_ref"],
            }
        )
        relations[target["id"]].append(
            {
                "relation_type": relation["relation_type"],
                "direction": "incoming",
                "code": source["code"],
                "title": source["title"],
                "node_type": _node_type(source),
                "confidence": float(relation["confidence"]),
                "source_ref": relation["source_ref"],
            }
        )

    selected: list[dict[str, Any]] = []
    for raw in rows:
        point = point_by_id[raw["id"]]
        path: list[dict[str, str]] = []
        cursor: dict[str, Any] | None = point
        visited: set[str] = set()
        while cursor and cursor["id"] not in visited:
            visited.add(cursor["id"])
            path.append(
                {
                    "code": cursor["code"],
                    "title": cursor["title"],
                    "node_type": _node_type(cursor),
                }
            )
            parent_id = cursor.get("parent_id")
            cursor = point_by_id.get(parent_id) if isinstance(parent_id, str) else None
        path.reverse()
        point["path"] = path
        point["breadcrumb"] = " › ".join(item["title"] for item in path)
        point["relations"] = sorted(
            relations.get(point["id"], []),
            key=lambda item: (
                item["relation_type"],
                item["direction"],
                item["code"],
            ),
        )
        point["difficulty"] = _difficulty_summary(point)
        point.pop("features_json", None)
        point.pop("updated_at", None)
        selected.append(point)

    point_by_selected_id = {point["id"]: point for point in selected}
    references = _references_by_point(
        repository,
        list(point_by_selected_id),
        point_by_selected_id,
        index_build_id=index_build_id,
    )
    for point in selected:
        point["references"] = references.get(point["id"], [])
    return selected
