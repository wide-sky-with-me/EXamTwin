from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import QuestionDifficultyModel


class DifficultyRepository:
    """Own empirical question-difficulty observations and projections."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def upsert_questions(self, rows: Sequence[Mapping[str, Any]]) -> None:
        with self.sessions.begin() as session:
            for values in rows:
                payload = dict(values)
                row = session.scalar(
                    select(QuestionDifficultyModel).where(
                        QuestionDifficultyModel.source_document_id == payload["source_document_id"],
                        QuestionDifficultyModel.question_number == payload["question_number"],
                    )
                )
                if row is None:
                    session.add(QuestionDifficultyModel(**payload))
                    continue
                for field, value in payload.items():
                    if field != "source_document_id":
                        setattr(row, field, value)

    def list_questions(
        self,
        *,
        pair_key: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        statement = select(QuestionDifficultyModel)
        if pair_key:
            statement = statement.where(QuestionDifficultyModel.pair_key == pair_key)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        rows.sort(
            key=lambda row: (
                row.pair_key is None,
                str(row.pair_key or ""),
                int(row.question_number),
            )
        )
        return [
            {
                "question_ref": row.question_ref,
                "pair_key": row.pair_key,
                "question_number": row.question_number,
                "difficulty_score": row.difficulty_score,
                "difficulty_label": row.difficulty_label,
                "confidence": row.confidence,
                "evidence_level": row.evidence_level,
                "knowledge_codes": json.loads(row.knowledge_codes_json),
                "evidence": json.loads(row.evidence_json),
                "source_ref": row.source_ref,
            }
            for row in rows[:limit]
        ]
