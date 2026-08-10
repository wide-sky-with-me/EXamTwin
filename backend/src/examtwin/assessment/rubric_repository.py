from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    RubricCriterionAiReviewModel,
    RubricCriterionModel,
    RubricCriterionReviewModel,
    RubricSetModel,
)
from examtwin.platform.database.session import utcnow

_LIST_UPDATE_FIELDS = {
    "dependencies": "dependencies_json",
    "alternatives": "alternatives_json",
    "units": "units_json",
}
_REQUIRED_UPDATE_FIELDS = {
    "scoring_mode",
    "max_marks",
    "description",
    "dependencies",
    "alternatives",
    "units",
    "source_excerpt",
}
_ALLOWED_UPDATE_FIELDS = _REQUIRED_UPDATE_FIELDS | {
    "mark_type",
    "accuracy_requirement",
    "follow_through_policy",
    "source_page",
}


def _is_criterion_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class RubricConflictError(ValueError):
    """The rubric changed after the caller read the draft."""


def _set_dict(row: RubricSetModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_id": row.subject_id,
        "paper_job_id": row.paper_job_id,
        "source_document_id": row.source_document_id,
        "source_document_checksum": row.source_document_checksum,
        "version_number": row.version_number,
        "status": row.status,
        "identity": json.loads(row.identity_json or "{}"),
        "parser_model": row.parser_model,
        "parser_version": row.parser_version,
        "warnings": json.loads(row.warnings_json or "[]"),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "confirmed_at": row.confirmed_at,
        "confirmed_by": row.confirmed_by,
    }


def _ai_review_dict(row: RubricCriterionAiReviewModel) -> dict[str, Any]:
    return {
        "recommendation": row.recommendation,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "suggested_updates": (
            json.loads(row.suggested_updates_json)
            if row.suggested_updates_json is not None
            else None
        ),
        "model": row.model,
        "reviewed_at": row.created_at,
        "criterion_fingerprint": row.criterion_fingerprint,
    }


def _criterion_values(row: RubricCriterionModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "question_number": row.question_number,
        "subpart": row.subpart,
        "criterion_id": row.criterion_id,
        "scoring_mode": row.scoring_mode,
        "mark_type": row.mark_type,
        "max_marks": row.max_marks,
        "description": row.description,
        "dependencies": json.loads(row.dependencies_json or "[]"),
        "alternatives": json.loads(row.alternatives_json or "[]"),
        "accuracy_requirement": row.accuracy_requirement,
        "units": json.loads(row.units_json or "[]"),
        "follow_through_policy": row.follow_through_policy,
        "source_page": row.source_page,
        "source_excerpt": row.source_excerpt,
        "confidence": row.confidence,
        "review_status": row.review_status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
    }


def _criterion_fingerprint(row: RubricCriterionModel) -> str:
    canonical = json.dumps(
        _criterion_values(row),
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _criterion_dict(
    row: RubricCriterionModel,
    *,
    ai_review: RubricCriterionAiReviewModel | None = None,
) -> dict[str, Any]:
    values = _criterion_values(row)
    current_fingerprint = _criterion_fingerprint(row)
    values["criterion_fingerprint"] = current_fingerprint
    values["ai_review"] = (
        _ai_review_dict(ai_review)
        if ai_review is not None and ai_review.criterion_fingerprint == current_fingerprint
        else None
    )
    return values


def _snapshot(row: RubricCriterionModel) -> str:
    return json.dumps(_criterion_values(row), ensure_ascii=False, default=str)


def _validated_updates(updates: Mapping[str, Any] | None) -> dict[str, Any]:
    if updates is None:
        return {}
    if not isinstance(updates, Mapping):
        raise ValueError("评分原子更新必须是对象")
    unknown_fields = set(updates) - _ALLOWED_UPDATE_FIELDS
    if unknown_fields:
        raise ValueError(f"不支持更新字段: {sorted(unknown_fields)[0]}")
    values = dict(updates)
    for field, value in values.items():
        if field in _REQUIRED_UPDATE_FIELDS and value is None:
            raise ValueError(f"{field} 不能设为空")
        if field == "scoring_mode" and value not in {"point_based", "levels_based"}:
            raise ValueError("无效的评分模式")
        if field == "max_marks":
            if isinstance(value, bool):
                raise ValueError("max_marks 必须大于 0")
            try:
                max_marks = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError("max_marks 必须大于 0") from error
            if not max_marks > 0:
                raise ValueError("max_marks 必须大于 0")
            values[field] = max_marks
        if field == "description" and (not isinstance(value, str) or not value):
            raise ValueError("description 不能为空")
        if field in _LIST_UPDATE_FIELDS:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{field} 必须是文本列表")
        if (
            field
            in {
                "mark_type",
                "accuracy_requirement",
                "follow_through_policy",
            }
            and value is not None
            and not isinstance(value, str)
        ):
            raise ValueError(f"{field} 必须是文本")
        if field == "source_page" and (
            value is not None
            and (isinstance(value, bool) or not isinstance(value, int) or value < 1)
        ):
            raise ValueError("source_page 必须大于等于 1")
        if field == "source_excerpt" and not isinstance(value, str):
            raise ValueError("source_excerpt 必须是文本")
    return values


def _apply_human_review(
    session: Session,
    *,
    rubric: RubricSetModel,
    criterion: RubricCriterionModel,
    review_status: str,
    reviewer: str,
    note: str | None,
    updates: Mapping[str, Any],
    now: Any,
) -> None:
    before_json = _snapshot(criterion)
    for field, value in updates.items():
        if field in _LIST_UPDATE_FIELDS:
            setattr(
                criterion,
                _LIST_UPDATE_FIELDS[field],
                json.dumps(value, ensure_ascii=False),
            )
        else:
            setattr(criterion, field, value)
    criterion.review_status = review_status
    criterion.reviewed_by = reviewer
    criterion.reviewed_at = now
    session.add(
        RubricCriterionReviewModel(
            rubric_set_id=rubric.id,
            criterion_id=criterion.id,
            action=(f"edited_and_{review_status}" if updates else review_status),
            reviewer=reviewer,
            before_json=before_json,
            after_json=_snapshot(criterion),
            note=note,
            created_at=now,
        )
    )


class RubricRepository:
    """Own versioned, subject-scoped, human-reviewable mark-scheme rubric sets."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create(
        self,
        *,
        subject_id: str,
        paper_job_id: str,
        source_document_id: str,
        source_document_checksum: str,
        identity: Mapping[str, Any],
        parser_model: str,
        warnings: Sequence[str],
        criteria: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        now = utcnow()
        with self.sessions.begin() as session:
            version_number = (
                int(
                    session.scalar(
                        select(func.coalesce(func.max(RubricSetModel.version_number), 0)).where(
                            RubricSetModel.paper_job_id == paper_job_id
                        )
                    )
                    or 0
                )
                + 1
            )
            rubric_id = str(uuid.uuid4())
            session.add(
                RubricSetModel(
                    id=rubric_id,
                    subject_id=subject_id,
                    paper_job_id=paper_job_id,
                    source_document_id=source_document_id,
                    source_document_checksum=source_document_checksum,
                    version_number=version_number,
                    status="draft",
                    identity_json=json.dumps(dict(identity), ensure_ascii=False),
                    parser_model=parser_model,
                    warnings_json=json.dumps(list(warnings), ensure_ascii=False),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            for item in criteria:
                session.add(
                    RubricCriterionModel(
                        id=str(uuid.uuid4()),
                        rubric_set_id=rubric_id,
                        question_number=str(item["question_number"]),
                        subpart=str(item.get("subpart") or "whole"),
                        criterion_id=str(item["criterion_id"]),
                        scoring_mode=str(item["scoring_mode"]),
                        mark_type=item.get("mark_type"),
                        max_marks=float(item["max_marks"]),
                        description=str(item["description"]),
                        dependencies_json=json.dumps(
                            item.get("dependencies", []), ensure_ascii=False
                        ),
                        alternatives_json=json.dumps(
                            item.get("alternatives", []), ensure_ascii=False
                        ),
                        accuracy_requirement=item.get("accuracy_requirement"),
                        units_json=json.dumps(item.get("units", []), ensure_ascii=False),
                        follow_through_policy=item.get("follow_through_policy"),
                        source_page=item.get("source_page"),
                        source_excerpt=str(item.get("source_excerpt") or ""),
                        confidence=float(item.get("confidence", 0.5)),
                        review_status="pending",
                    )
                )
        return self.get(rubric_id, subject_id=subject_id)

    def list_for_paper(self, paper_job_id: str, *, subject_id: str) -> list[dict[str, Any]]:
        statement = (
            select(RubricSetModel)
            .where(
                RubricSetModel.paper_job_id == paper_job_id,
                RubricSetModel.subject_id == subject_id,
            )
            .order_by(RubricSetModel.version_number.desc())
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_set_dict(row) for row in rows]

    def get(self, rubric_id: str, *, subject_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            rubric = session.scalar(
                select(RubricSetModel).where(
                    RubricSetModel.id == rubric_id,
                    RubricSetModel.subject_id == subject_id,
                )
            )
            if rubric is None:
                raise LookupError("评分规则版本不存在")
            criteria = list(
                session.scalars(
                    select(RubricCriterionModel)
                    .where(RubricCriterionModel.rubric_set_id == rubric_id)
                    .order_by(
                        RubricCriterionModel.question_number,
                        RubricCriterionModel.subpart,
                        RubricCriterionModel.criterion_id,
                    )
                )
            )
            latest_ai_reviews: dict[str, RubricCriterionAiReviewModel] = {}
            if criteria:
                ai_reviews = session.scalars(
                    select(RubricCriterionAiReviewModel)
                    .where(RubricCriterionAiReviewModel.rubric_set_id == rubric_id)
                    .order_by(
                        RubricCriterionAiReviewModel.criterion_id,
                        RubricCriterionAiReviewModel.created_at.desc(),
                        RubricCriterionAiReviewModel.id.desc(),
                    )
                )
                for ai_review in ai_reviews:
                    latest_ai_reviews.setdefault(ai_review.criterion_id, ai_review)
            result = _set_dict(rubric)
            result["criteria"] = [
                _criterion_dict(row, ai_review=latest_ai_reviews.get(row.id)) for row in criteria
            ]
            return result

    def review_criterion(
        self,
        rubric_id: str,
        criterion_id: str,
        *,
        subject_id: str,
        review_status: str,
        reviewer: str,
        note: str | None,
        updates: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self.review_criteria_batch(
            rubric_id,
            subject_id=subject_id,
            reviewer=reviewer,
            decisions=[
                {
                    "criterion_id": criterion_id,
                    "review_status": review_status,
                    "note": note,
                    "updates": updates,
                }
            ],
        )

    def review_criteria_batch(
        self,
        rubric_id: str,
        *,
        subject_id: str,
        reviewer: str,
        decisions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("必须填写审核人")
        if not decisions:
            raise ValueError("至少需要一个审核决定")
        if len(decisions) > 200:
            raise ValueError("一次最多审核 200 个评分原子")

        normalized: list[dict[str, Any]] = []
        criterion_ids: list[str] = []
        for decision in decisions:
            if not isinstance(decision, Mapping):
                raise ValueError("审核决定必须是对象")
            criterion_id = decision.get("criterion_id")
            if not isinstance(criterion_id, str) or not criterion_id.strip():
                raise ValueError("评分原子 ID 不能为空")
            review_status = decision.get("review_status")
            if review_status not in {"accepted", "rejected"}:
                raise ValueError("无效的审核状态")
            note = decision.get("note")
            if note is not None and not isinstance(note, str):
                raise ValueError("审核备注必须是文本")
            expected_criterion_fingerprint = decision.get("expected_criterion_fingerprint")
            if expected_criterion_fingerprint is not None and not _is_criterion_fingerprint(
                expected_criterion_fingerprint
            ):
                raise ValueError("评分原子指纹格式无效")
            normalized.append(
                {
                    "criterion_id": criterion_id,
                    "review_status": review_status,
                    "note": note,
                    "updates": _validated_updates(decision.get("updates")),
                    "expected_criterion_fingerprint": expected_criterion_fingerprint,
                }
            )
            criterion_ids.append(criterion_id)
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("请求包含重复评分原子")

        now = utcnow()
        with self.sessions.begin() as session:
            rubric = session.scalar(
                select(RubricSetModel)
                .where(
                    RubricSetModel.id == rubric_id,
                    RubricSetModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if rubric is None:
                raise LookupError("评分规则版本不存在")
            if rubric.status != "draft":
                raise RubricConflictError("只有草稿评分规则可以审核")
            criteria = list(
                session.scalars(
                    select(RubricCriterionModel)
                    .where(
                        RubricCriterionModel.rubric_set_id == rubric_id,
                        RubricCriterionModel.id.in_(criterion_ids),
                    )
                    .with_for_update()
                )
            )
            if len(criteria) != len(criterion_ids):
                raise LookupError("评分原子不存在")
            criteria_by_id = {criterion.id: criterion for criterion in criteria}
            mismatched_ids = [
                decision["criterion_id"]
                for decision in normalized
                if decision["expected_criterion_fingerprint"] is not None
                and decision["expected_criterion_fingerprint"]
                != _criterion_fingerprint(criteria_by_id[decision["criterion_id"]])
            ]
            if mismatched_ids:
                raise RubricConflictError("评分原子已在审核期间发生变化")
            for decision in normalized:
                _apply_human_review(
                    session,
                    rubric=rubric,
                    criterion=criteria_by_id[decision["criterion_id"]],
                    review_status=decision["review_status"],
                    reviewer=reviewer,
                    note=decision["note"],
                    updates=decision["updates"],
                    now=now,
                )
            rubric.updated_at = now
            session.flush()
        return self.get(rubric_id, subject_id=subject_id)

    def record_ai_reviews(
        self,
        rubric_id: str,
        *,
        subject_id: str,
        reviews: Sequence[Mapping[str, Any]],
        model: str,
    ) -> dict[str, Any]:
        model = model.strip()
        if not model:
            raise ValueError("AI 审核模型不能为空")
        if not reviews:
            raise ValueError("至少需要一个 AI 审核结果")
        if len(reviews) > 200:
            raise ValueError("一次最多保存 200 个 AI 审核结果")

        normalized: list[dict[str, Any]] = []
        criterion_ids: list[str] = []
        for review in reviews:
            if not isinstance(review, Mapping):
                raise ValueError("AI 审核结果必须是对象")
            criterion_id = review.get("criterion_id")
            if not isinstance(criterion_id, str) or not criterion_id.strip():
                raise ValueError("评分原子 ID 不能为空")
            criterion_fingerprint = review.get("criterion_fingerprint")
            if not _is_criterion_fingerprint(criterion_fingerprint):
                raise ValueError("AI 审核缺少评分原子指纹")
            recommendation = review.get("recommendation")
            if recommendation not in {"accept", "reject", "revise"}:
                raise ValueError("无效的 AI 审核建议")
            confidence_value = review.get("confidence")
            if isinstance(confidence_value, bool) or not isinstance(confidence_value, (int, float)):
                raise ValueError("AI 审核置信度必须位于 0 到 1")
            confidence = float(confidence_value)
            if not 0 <= confidence <= 1:
                raise ValueError("AI 审核置信度必须位于 0 到 1")
            rationale = review.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise ValueError("AI 审核理由不能为空")
            suggested_updates = review.get("suggested_updates")
            suggested_updates_json = (
                json.dumps(
                    _validated_updates(suggested_updates),
                    ensure_ascii=False,
                )
                if suggested_updates is not None
                else None
            )
            normalized.append(
                {
                    "criterion_id": criterion_id,
                    "recommendation": recommendation,
                    "confidence": confidence,
                    "rationale": rationale,
                    "suggested_updates_json": suggested_updates_json,
                    "criterion_fingerprint": criterion_fingerprint,
                }
            )
            criterion_ids.append(criterion_id)
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("请求包含重复评分原子")

        now = utcnow()
        with self.sessions.begin() as session:
            rubric = session.scalar(
                select(RubricSetModel)
                .where(
                    RubricSetModel.id == rubric_id,
                    RubricSetModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if rubric is None:
                raise LookupError("评分规则版本不存在")
            if rubric.status != "draft":
                raise RubricConflictError("只有草稿评分规则可以进行 AI 审核")
            criteria = list(
                session.scalars(
                    select(RubricCriterionModel)
                    .where(
                        RubricCriterionModel.rubric_set_id == rubric_id,
                        RubricCriterionModel.id.in_(criterion_ids),
                    )
                    .with_for_update()
                )
            )
            if len(criteria) != len(criterion_ids):
                raise LookupError("评分原子不存在")
            criteria_by_id = {criterion.id: criterion for criterion in criteria}
            mismatched_ids = [
                review["criterion_id"]
                for review in normalized
                if review["criterion_fingerprint"]
                != _criterion_fingerprint(criteria_by_id[review["criterion_id"]])
            ]
            if mismatched_ids:
                raise RubricConflictError("评分原子已在 AI 审核期间发生变化")
            session.add_all(
                [
                    RubricCriterionAiReviewModel(
                        id=str(uuid.uuid4()),
                        rubric_set_id=rubric_id,
                        criterion_id=review["criterion_id"],
                        criterion_fingerprint=review["criterion_fingerprint"],
                        recommendation=review["recommendation"],
                        confidence=review["confidence"],
                        rationale=review["rationale"],
                        suggested_updates_json=review["suggested_updates_json"],
                        model=model,
                        created_at=now,
                    )
                    for review in normalized
                ]
            )
            session.flush()
        return self.get(rubric_id, subject_id=subject_id)

    def confirm(self, rubric_id: str, *, subject_id: str, reviewer: str) -> dict[str, Any]:
        reviewer = reviewer.strip()
        if not reviewer:
            raise ValueError("必须填写审核人")
        now = utcnow()
        with self.sessions.begin() as session:
            rubric = session.scalar(
                select(RubricSetModel)
                .where(
                    RubricSetModel.id == rubric_id,
                    RubricSetModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if rubric is None:
                raise LookupError("评分规则版本不存在")
            if rubric.status != "draft":
                raise RubricConflictError("只有草稿评分规则可以确认")
            pending = session.scalar(
                select(func.count())
                .select_from(RubricCriterionModel)
                .where(
                    RubricCriterionModel.rubric_set_id == rubric_id,
                    RubricCriterionModel.review_status == "pending",
                )
            )
            accepted = session.scalar(
                select(func.count())
                .select_from(RubricCriterionModel)
                .where(
                    RubricCriterionModel.rubric_set_id == rubric_id,
                    RubricCriterionModel.review_status == "accepted",
                )
            )
            if pending:
                raise ValueError("仍有未审核的评分原子")
            if not accepted:
                raise ValueError("至少需要接受一个评分原子")
            rubric.status = "confirmed"
            rubric.updated_at = now
            rubric.confirmed_at = now
            rubric.confirmed_by = reviewer
        return self.get(rubric_id, subject_id=subject_id)

    def accepted_for_question(
        self,
        rubric_id: str,
        question_number: str,
        *,
        subject_id: str,
    ) -> list[dict[str, Any]]:
        statement = (
            select(RubricCriterionModel)
            .join(RubricSetModel, RubricSetModel.id == RubricCriterionModel.rubric_set_id)
            .where(
                RubricCriterionModel.rubric_set_id == rubric_id,
                RubricCriterionModel.question_number == question_number,
                RubricCriterionModel.review_status == "accepted",
                RubricSetModel.status == "confirmed",
                RubricSetModel.subject_id == subject_id,
            )
            .order_by(RubricCriterionModel.subpart, RubricCriterionModel.criterion_id)
        )
        with self.sessions() as session:
            return [_criterion_dict(row) for row in session.scalars(statement)]
