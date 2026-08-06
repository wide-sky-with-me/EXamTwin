from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    CurriculumCandidateModel,
    KnowledgeBuildRunModel,
    KnowledgePointModel,
    SourceDocumentModel,
)
from examtwin.platform.database.results import affected_rows

RUN_MUTABLE_FIELDS = frozenset(
    {
        "source_document_id",
        "status",
        "stage",
        "input_hash",
        "metrics_json",
        "artifact_json",
        "error",
        "updated_at",
        "completed_at",
    }
)

CANDIDATE_MUTABLE_FIELDS = frozenset(
    {"status", "review_status", "validation_json", "updated_at", "published_at"}
)


class KnowledgeBuildRepository:
    """Own persistence and checkpoint queries for knowledge-build runs."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create_run(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(KnowledgeBuildRunModel(**dict(values)))

    def update_run(self, run_id: str, updates: Mapping[str, Any]) -> None:
        invalid = set(updates) - RUN_MUTABLE_FIELDS
        if invalid:
            raise ValueError(f"Unsupported knowledge run fields: {sorted(invalid)}")
        with self.sessions.begin() as session:
            result = session.execute(
                update(KnowledgeBuildRunModel)
                .where(KnowledgeBuildRunModel.id == run_id)
                .values(**dict(updates))
            )
            if affected_rows(result) != 1:
                raise LookupError(f"Knowledge build run does not exist: {run_id}")

    def create_candidate(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(CurriculumCandidateModel(**dict(values)))

    def update_candidate(self, candidate_id: str, updates: Mapping[str, Any]) -> None:
        invalid = set(updates) - CANDIDATE_MUTABLE_FIELDS
        if invalid:
            raise ValueError(f"Unsupported curriculum candidate fields: {sorted(invalid)}")
        with self.sessions.begin() as session:
            result = session.execute(
                update(CurriculumCandidateModel)
                .where(CurriculumCandidateModel.id == candidate_id)
                .values(**dict(updates))
            )
            if affected_rows(result) != 1:
                raise LookupError(f"Curriculum candidate does not exist: {candidate_id}")

    def published_graph_codes(self, subject_code: str) -> dict[str, set[str]]:
        statement = select(KnowledgePointModel.code, KnowledgePointModel.features_json).where(
            KnowledgePointModel.subject_code == subject_code
        )
        topics: set[str] = set()
        objectives: set[str] = set()
        with self.sessions() as session:
            rows = list(session.execute(statement))
        for code, features_value in rows:
            try:
                features = json.loads(features_value or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            node_type = features.get("node_type")
            if node_type == "topic":
                topics.add(str(code))
            elif node_type == "learning_objective":
                objectives.add(str(code))
        return {"topics": topics, "objectives": objectives}

    def syllabus_document(self, subject_code: str) -> dict[str, Any] | None:
        priority = case(
            (SourceDocumentModel.status == "indexed", 0),
            (SourceDocumentModel.status == "converted", 1),
            else_=2,
        )
        statement = (
            select(SourceDocumentModel)
            .where(
                SourceDocumentModel.subject_code == subject_code,
                SourceDocumentModel.source_type == "syllabus",
                SourceDocumentModel.markdown_path.is_not(None),
            )
            .order_by(priority)
            .limit(1)
        )
        with self.sessions() as session:
            row = session.scalar(statement)
        if row is None:
            return None
        return {"id": row.id, "path": row.path, "markdown_path": row.markdown_path}

    def cached_artifacts(
        self,
        *,
        subject_code: str,
        input_hash: str,
        ai_model: str,
        limit: int = 20,
    ) -> list[str]:
        statement = (
            select(KnowledgeBuildRunModel.artifact_json)
            .where(
                KnowledgeBuildRunModel.subject_code == subject_code,
                KnowledgeBuildRunModel.input_hash == input_hash,
                KnowledgeBuildRunModel.ai_model == ai_model,
            )
            .order_by(KnowledgeBuildRunModel.created_at.desc())
            .limit(limit)
        )
        with self.sessions() as session:
            return list(session.scalars(statement))
