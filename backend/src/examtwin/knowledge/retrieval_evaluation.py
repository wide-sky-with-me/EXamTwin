from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from llama_index.core.schema import NodeWithScore
from pydantic import BaseModel, Field, model_validator


class RetrievalTarget(BaseModel):
    knowledge_code: str | None = None
    document_id: str | None = None

    @model_validator(mode="after")
    def require_identity(self) -> RetrievalTarget:
        if not self.knowledge_code and not self.document_id:
            raise ValueError("A retrieval target needs knowledge_code or document_id")
        return self


class RetrievalCase(BaseModel):
    id: str
    query: str
    unit_code: str | None = None
    pair_key: str | None = None
    source_types: list[str] = Field(default_factory=list)
    authority_tiers: list[str] = Field(default_factory=list)
    targets: list[RetrievalTarget] = Field(min_length=1)


class RetrievalEvaluationDataset(BaseModel):
    subject_code: str
    top_k: int = Field(default=5, ge=1, le=20)
    minimum_recall_at_k: float = Field(default=0.8, ge=0, le=1)
    minimum_mrr: float = Field(default=0.6, ge=0, le=1)
    cases: list[RetrievalCase] = Field(min_length=1)


def load_retrieval_dataset(path: Path) -> RetrievalEvaluationDataset:
    return RetrievalEvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _matches(node: NodeWithScore, targets: Sequence[RetrievalTarget]) -> bool:
    metadata = node.node.metadata
    codes = {
        str(code)
        for code in [metadata.get("knowledge_code"), *(metadata.get("knowledge_codes") or [])]
        if code
    }
    document_id = str(metadata.get("document_id") or "")
    return any(
        (target.knowledge_code is not None and target.knowledge_code in codes)
        or (target.document_id is not None and target.document_id == document_id)
        for target in targets
    )


def _scope_violations(
    nodes: Sequence[NodeWithScore],
    *,
    subject_code: str,
    case: RetrievalCase,
) -> int:
    def unit_is_out_of_scope(node: NodeWithScore) -> bool:
        metadata = node.node.metadata
        return bool(
            case.unit_code
            and metadata.get("unit_code") != case.unit_code
            # A component is not a hard curriculum boundary on synoptic papers.
            # Subject-wide catalog nodes/cards are allowed, while raw evidence
            # from another unit remains a scope violation.
            and metadata.get("node_kind") not in {"knowledge_point", "knowledge_card"}
        )

    return sum(
        1
        for node in nodes
        if (
            node.node.metadata.get("subject_code") != subject_code
            or unit_is_out_of_scope(node)
            or (case.pair_key and node.node.metadata.get("pair_key") != case.pair_key)
            or (
                case.source_types and node.node.metadata.get("source_type") not in case.source_types
            )
            or (
                case.authority_tiers
                and node.node.metadata.get("authority_tier") not in case.authority_tiers
            )
        )
    )


def evaluate_retrieval(
    dataset: RetrievalEvaluationDataset,
    retrieve: Callable[..., list[NodeWithScore]],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    reciprocal_rank_total = 0.0
    hits = 0
    empty = 0
    scope_violations = 0
    for case in dataset.cases:
        nodes = retrieve(
            case.query,
            subject_code=dataset.subject_code,
            unit_code=case.unit_code,
            pair_key=case.pair_key,
            source_types=case.source_types,
            authority_tiers=case.authority_tiers,
            top_k=dataset.top_k,
        )[: dataset.top_k]
        if not nodes:
            empty += 1
        rank = next(
            (index for index, node in enumerate(nodes, start=1) if _matches(node, case.targets)),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_rank_total += 1 / rank
        violations = _scope_violations(
            nodes,
            subject_code=dataset.subject_code,
            case=case,
        )
        scope_violations += violations
        results.append(
            {
                "id": case.id,
                "rank": rank,
                "returned": len(nodes),
                "scope_violations": violations,
                "top_results": [
                    {
                        "knowledge_code": node.node.metadata.get("knowledge_code"),
                        "document_id": node.node.metadata.get("document_id"),
                        "source_type": node.node.metadata.get("source_type"),
                        "score": node.score,
                    }
                    for node in nodes
                ],
            }
        )

    case_count = len(dataset.cases)
    recall = hits / case_count
    mrr = reciprocal_rank_total / case_count
    passed = (
        recall >= dataset.minimum_recall_at_k
        and mrr >= dataset.minimum_mrr
        and scope_violations == 0
    )
    return {
        "subject_code": dataset.subject_code,
        "cases": case_count,
        "top_k": dataset.top_k,
        "recall_at_k": round(recall, 4),
        "mrr": round(mrr, 4),
        "empty_rate": round(empty / case_count, 4),
        "scope_violations": scope_violations,
        "thresholds": {
            "minimum_recall_at_k": dataset.minimum_recall_at_k,
            "minimum_mrr": dataset.minimum_mrr,
        },
        "passed": passed,
        "results": results,
    }


def render_evaluation(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)
