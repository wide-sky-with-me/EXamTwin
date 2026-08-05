from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import RetrievalTraceModel


class RetrievalTraceRepository:
    """Own durable, bounded diagnostics for the retrieval pipeline."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        max_rows_per_subject: int = 2_000,
    ) -> None:
        self.sessions = sessions
        self.max_rows_per_subject = max(1, max_rows_per_subject)

    def record(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(RetrievalTraceModel(**dict(values)))
            session.flush()
            stale_ids = (
                select(RetrievalTraceModel.id)
                .where(RetrievalTraceModel.subject_code == values["subject_code"])
                .order_by(
                    RetrievalTraceModel.created_at.desc(),
                    RetrievalTraceModel.id.desc(),
                )
                .offset(self.max_rows_per_subject)
            )
            session.execute(
                delete(RetrievalTraceModel).where(RetrievalTraceModel.id.in_(stale_ids))
            )

    def recent(self, *, subject_code: str, limit: int = 20) -> list[dict[str, Any]]:
        statement = (
            select(RetrievalTraceModel)
            .where(RetrievalTraceModel.subject_code == subject_code)
            .order_by(RetrievalTraceModel.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
            for row in rows
        ]
