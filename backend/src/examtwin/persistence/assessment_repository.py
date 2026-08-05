from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import AssessmentModel, ReviewModel
from examtwin.persistence.session import utcnow


class AssessmentRepository:
    """Own assessment persistence and the atomic human-review transition."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(AssessmentModel(**dict(values)))

    def pending(self, *, subject_code: str) -> list[dict[str, Any]]:
        statement = (
            select(AssessmentModel)
            .where(
                AssessmentModel.subject_code == subject_code,
                AssessmentModel.status == "pending_review",
            )
            .order_by(AssessmentModel.created_at.desc())
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [
            {
                "id": row.id,
                "subject_code": row.subject_code,
                "question_ref": row.question_ref,
                "total_awarded": row.total_awarded,
                "total_available": row.total_available,
                "confidence": row.confidence,
                "status": row.status,
                "result": json.loads(row.result_json),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def review(
        self,
        assessment_id: str,
        *,
        reviewer: str,
        decision: str,
        override_mark: float | None,
        note: str | None,
        subject_code: str,
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            assessment = session.scalar(
                select(AssessmentModel)
                .where(
                    AssessmentModel.id == assessment_id,
                    AssessmentModel.subject_code == subject_code,
                )
                .with_for_update()
            )
            if assessment is None:
                raise LookupError("Assessment not found")
            if decision == "override" and override_mark is None:
                raise ValueError("override_mark is required for an override review")
            final_mark = (
                override_mark if override_mark is not None else float(assessment.total_awarded)
            )
            if final_mark > assessment.total_available:
                raise ValueError("override_mark cannot exceed total_available")
            status = "overridden" if decision == "override" else "confirmed"
            now = utcnow()
            session.add(
                ReviewModel(
                    assessment_id=assessment_id,
                    reviewer=reviewer,
                    decision=decision,
                    override_mark=override_mark,
                    note=note,
                    created_at=now,
                )
            )
            assessment.total_awarded = final_mark
            assessment.status = status
            assessment.updated_at = now
        return {
            "assessment_id": assessment_id,
            "status": status,
            "final_mark": final_mark,
            "reviewed_by": reviewer,
        }
