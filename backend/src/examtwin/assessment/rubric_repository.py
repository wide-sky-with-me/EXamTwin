from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    RubricCriterionModel,
    RubricCriterionReviewModel,
    RubricSetModel,
)
from examtwin.platform.database.session import utcnow


def _set_dict(row: RubricSetModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_id": row.subject_id,
        "paper_job_id": row.paper_job_id,
        "source_document_id": row.source_document_id,
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


def _criterion_dict(row: RubricCriterionModel) -> dict[str, Any]:
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


def _snapshot(row: RubricCriterionModel) -> str:
    return json.dumps(_criterion_dict(row), ensure_ascii=False, default=str)


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
        result = _set_dict(rubric)
        result["criteria"] = [_criterion_dict(row) for row in criteria]
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
        if review_status not in {"accepted", "rejected"}:
            raise ValueError("无效的审核状态")
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
                raise ValueError("只有草稿评分规则可以审核")
            criterion = session.scalar(
                select(RubricCriterionModel)
                .where(
                    RubricCriterionModel.id == criterion_id,
                    RubricCriterionModel.rubric_set_id == rubric_id,
                )
                .with_for_update()
            )
            if criterion is None:
                raise LookupError("评分原子不存在")
            before_json = _snapshot(criterion)
            list_fields = {
                "dependencies": "dependencies_json",
                "alternatives": "alternatives_json",
                "units": "units_json",
            }
            required_fields = {
                "scoring_mode",
                "max_marks",
                "description",
                "dependencies",
                "alternatives",
                "units",
                "source_excerpt",
            }
            for field, value in updates.items():
                if field in required_fields and value is None:
                    raise ValueError(f"{field} 不能设为空")
                if field in list_fields:
                    setattr(
                        criterion,
                        list_fields[field],
                        json.dumps(value, ensure_ascii=False),
                    )
                else:
                    setattr(criterion, field, value)
            criterion.review_status = review_status
            criterion.reviewed_by = reviewer
            criterion.reviewed_at = now
            rubric.updated_at = now
            session.flush()
            session.add(
                RubricCriterionReviewModel(
                    rubric_set_id=rubric_id,
                    criterion_id=criterion_id,
                    action=(f"edited_and_{review_status}" if updates else review_status),
                    reviewer=reviewer,
                    before_json=before_json,
                    after_json=_snapshot(criterion),
                    note=note,
                    created_at=now,
                )
            )
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
                raise ValueError("只有草稿评分规则可以确认")
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
