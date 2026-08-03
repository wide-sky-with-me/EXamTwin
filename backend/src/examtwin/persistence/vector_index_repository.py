from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import (
    SourceDocumentModel,
    VectorIndexBuildRunModel,
    VectorIndexPublicationModel,
)

RUN_MUTABLE_FIELDS = frozenset(
    {
        "previous_collection",
        "status",
        "stage",
        "input_hash",
        "expected_points",
        "indexed_points",
        "document_count",
        "error",
        "updated_at",
        "published_at",
    }
)


class VectorIndexRepository:
    """Own vector-index build checkpoints and source indexing state."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create_run(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(VectorIndexBuildRunModel(**dict(values)))

    def update_run(self, run_id: str, values: Mapping[str, Any]) -> None:
        invalid = set(values) - RUN_MUTABLE_FIELDS
        if invalid:
            raise ValueError(f"Unsupported vector index run fields: {sorted(invalid)}")
        with self.sessions.begin() as session:
            result = session.execute(
                update(VectorIndexBuildRunModel)
                .where(VectorIndexBuildRunModel.id == run_id)
                .values(**dict(values))
            )
            if result.rowcount != 1:
                raise LookupError(f"Vector index build run does not exist: {run_id}")

    def latest_resumable(self, *, subject_code: str, alias_name: str) -> dict[str, Any] | None:
        statement = (
            select(VectorIndexBuildRunModel)
            .where(
                VectorIndexBuildRunModel.subject_code == subject_code,
                VectorIndexBuildRunModel.alias_name == alias_name,
                VectorIndexBuildRunModel.status.in_(("running", "failed")),
            )
            .order_by(VectorIndexBuildRunModel.created_at.desc())
            .limit(1)
        )
        with self.sessions() as session:
            row = session.scalar(statement)
        if row is None:
            return None
        return {
            "id": row.id,
            "staging_collection": row.staging_collection,
            "input_hash": row.input_hash,
            "expected_points": row.expected_points,
        }

    def indexable_documents(
        self,
        *,
        subject_code: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        priority = case(
            (SourceDocumentModel.source_type == "syllabus", 0),
            (SourceDocumentModel.source_type == "mark_scheme", 1),
            else_=2,
        )
        statement = (
            select(SourceDocumentModel)
            .where(
                SourceDocumentModel.subject_code == subject_code,
                SourceDocumentModel.status.in_(("converted", "indexed")),
                SourceDocumentModel.markdown_path.is_not(None),
            )
            .order_by(priority, SourceDocumentModel.path)
        )
        if limit is not None:
            statement = statement.limit(limit)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [
            {
                "id": row.id,
                "path": row.path,
                "filename": row.filename,
                "source_type": row.source_type,
                "authority_tier": row.authority_tier,
                "pair_key": row.pair_key,
                "unit_code": row.unit_code,
                "subject_code": row.subject_code,
                "markdown_path": row.markdown_path,
                "checksum": row.checksum,
            }
            for row in rows
        ]

    def mark_documents_indexed(self, document_ids: Sequence[str]) -> None:
        if not document_ids:
            return
        with self.sessions.begin() as session:
            session.execute(
                update(SourceDocumentModel)
                .where(SourceDocumentModel.id.in_(tuple(document_ids)))
                .values(status="indexed")
            )

    def finalize_publication(
        self,
        *,
        run_id: str,
        subject_code: str,
        alias_name: str,
        collection_name: str,
        indexed_points: int,
        document_ids: Sequence[str],
        published_at: datetime,
    ) -> None:
        """Commit the PostgreSQL side of a successful Qdrant alias switch once."""
        with self.sessions.begin() as session:
            run = session.get(VectorIndexBuildRunModel, run_id)
            if run is None:
                raise LookupError(f"Vector index build run does not exist: {run_id}")
            if run.subject_code != subject_code or run.alias_name != alias_name:
                raise ValueError("Vector publication context does not match its build run")
            publication = session.get(VectorIndexPublicationModel, subject_code)
            if publication is None:
                publication = VectorIndexPublicationModel(
                    subject_code=subject_code,
                    alias_name=alias_name,
                    active_build_id=run_id,
                    collection_name=collection_name,
                    updated_at=published_at,
                )
                session.add(publication)
            else:
                publication.alias_name = alias_name
                publication.active_build_id = run_id
                publication.collection_name = collection_name
                publication.updated_at = published_at
            run.status = "published"
            run.stage = "published"
            run.indexed_points = indexed_points
            run.updated_at = published_at
            run.published_at = published_at
            if document_ids:
                session.execute(
                    update(SourceDocumentModel)
                    .where(SourceDocumentModel.id.in_(tuple(document_ids)))
                    .values(status="indexed")
                )
