from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, insert, or_, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import (
    DifficultyEvidenceModel,
    KnowledgeEvidenceModel,
    KnowledgePointModel,
    KnowledgeRelationModel,
    SourceDocumentModel,
)


def _model_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class KnowledgeRepository:
    """Own the published curriculum graph, its evidence, and read projections."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def publish_curriculum(
        self,
        *,
        subject_code: str,
        points: Sequence[Mapping[str, Any]],
        relations: Sequence[Mapping[str, Any]],
        valid_objective_ids: set[str],
        definition_document_id: str | None,
        definitions: Sequence[Mapping[str, Any]],
        difficulty_evidence: Sequence[Mapping[str, Any]],
    ) -> None:
        """Atomically replace one subject's source-derived curriculum projection."""
        with self.sessions.begin() as session:
            subject_ids = select(KnowledgePointModel.id).where(
                KnowledgePointModel.subject_code == subject_code
            )
            session.execute(
                delete(KnowledgeRelationModel).where(
                    KnowledgeRelationModel.relation_type == "prerequisite_of",
                    KnowledgeRelationModel.source_ref.like("%inferred-curriculum-sequence%"),
                    KnowledgeRelationModel.source_id.in_(subject_ids),
                )
            )
            stale_objective_ids = (
                self._stale_objective_ids(
                    session,
                    subject_code,
                    valid_objective_ids,
                )
                if valid_objective_ids
                else set()
            )
            if stale_objective_ids:
                session.execute(
                    delete(KnowledgeRelationModel).where(
                        or_(
                            KnowledgeRelationModel.source_id.in_(stale_objective_ids),
                            KnowledgeRelationModel.target_id.in_(stale_objective_ids),
                        )
                    )
                )
                session.execute(
                    delete(DifficultyEvidenceModel).where(
                        DifficultyEvidenceModel.knowledge_point_id.in_(stale_objective_ids)
                    )
                )
                session.execute(
                    delete(KnowledgeEvidenceModel).where(
                        KnowledgeEvidenceModel.knowledge_point_id.in_(stale_objective_ids)
                    )
                )
                session.execute(
                    delete(KnowledgePointModel).where(
                        KnowledgePointModel.id.in_(stale_objective_ids)
                    )
                )
            if definition_document_id and definitions:
                session.execute(
                    delete(KnowledgeEvidenceModel).where(
                        KnowledgeEvidenceModel.source_document_id == definition_document_id,
                        KnowledgeEvidenceModel.evidence_role == "definition",
                    )
                )
            for values in points:
                self._upsert_point(session, values)
            for values in relations:
                self._upsert_relation(session, values)
            for values in difficulty_evidence:
                session.add(DifficultyEvidenceModel(**dict(values)))
            for values in definitions:
                self._upsert_evidence(session, values)

    def stage_index_evidence(
        self,
        *,
        subject_code: str,
        build_id: str,
        evidence: Sequence[Mapping[str, Any]],
    ) -> None:
        """Write an immutable evidence version without touching the active version."""
        with self.sessions.begin() as session:
            subject_ids = select(KnowledgePointModel.id).where(
                KnowledgePointModel.subject_code == subject_code
            )
            session.execute(
                delete(KnowledgeEvidenceModel).where(
                    KnowledgeEvidenceModel.build_id == build_id,
                    KnowledgeEvidenceModel.knowledge_point_id.in_(subject_ids),
                )
            )
            if evidence:
                session.execute(
                    insert(KnowledgeEvidenceModel),
                    [{**dict(values), "build_id": build_id} for values in evidence],
                )

    def points(
        self,
        *,
        subject_code: str | None = None,
        unit_code: str | None = None,
        strand: str | None = None,
        codes: Sequence[str] | None = None,
        ids: Sequence[str] | None = None,
        include_root: bool = True,
    ) -> list[dict[str, Any]]:
        statement = select(KnowledgePointModel)
        if not include_root:
            statement = statement.where(KnowledgePointModel.code != "ROOT")
        if subject_code:
            statement = statement.where(KnowledgePointModel.subject_code == subject_code)
        if unit_code:
            statement = statement.where(KnowledgePointModel.unit_code == unit_code)
        if strand:
            statement = statement.where(KnowledgePointModel.strand == strand)
        if codes:
            statement = statement.where(KnowledgePointModel.code.in_(tuple(codes)))
        if ids:
            statement = statement.where(KnowledgePointModel.id.in_(tuple(ids)))
        statement = statement.order_by(KnowledgePointModel.unit_code, KnowledgePointModel.code)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_model_dict(row) for row in rows]

    def relations(
        self,
        *,
        subject_code: str | None = None,
        point_ids: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(KnowledgeRelationModel)
        if subject_code:
            subject_ids = select(KnowledgePointModel.id).where(
                KnowledgePointModel.subject_code == subject_code
            )
            statement = statement.where(
                KnowledgeRelationModel.source_id.in_(subject_ids),
                KnowledgeRelationModel.target_id.in_(subject_ids),
            )
        if point_ids:
            statement = statement.where(
                or_(
                    KnowledgeRelationModel.source_id.in_(tuple(point_ids)),
                    KnowledgeRelationModel.target_id.in_(tuple(point_ids)),
                )
            )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_model_dict(row) for row in rows]

    def evidence(
        self,
        point_ids: Sequence[str],
        *,
        index_build_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not point_ids:
            return []
        statement = (
            select(KnowledgeEvidenceModel, SourceDocumentModel)
            .outerjoin(
                SourceDocumentModel,
                SourceDocumentModel.id == KnowledgeEvidenceModel.source_document_id,
            )
            .where(KnowledgeEvidenceModel.knowledge_point_id.in_(tuple(point_ids)))
            .order_by(
                KnowledgeEvidenceModel.knowledge_point_id,
                KnowledgeEvidenceModel.confidence.desc(),
            )
        )
        if index_build_id is not None:
            statement = statement.where(
                or_(
                    KnowledgeEvidenceModel.evidence_role == "definition",
                    KnowledgeEvidenceModel.build_id == index_build_id,
                )
            )
        with self.sessions() as session:
            rows = list(session.execute(statement))
        return [
            {
                **_model_dict(evidence),
                "document_id": document.id if document else None,
                "source": document.path if document else None,
                "source_type": document.source_type if document else None,
                "authority_tier": document.authority_tier if document else None,
                "pair_key": document.pair_key if document else None,
            }
            for evidence, document in rows
        ]

    def converted_sources(self) -> list[dict[str, Any]]:
        statement = select(SourceDocumentModel).where(
            SourceDocumentModel.markdown_path.is_not(None)
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_model_dict(row) for row in rows]

    def relation_projection(
        self,
        *,
        subject_code: str | None = None,
    ) -> list[dict[str, Any]]:
        source = KnowledgePointModel.__table__.alias("source")
        target = KnowledgePointModel.__table__.alias("target")
        statement = (
            select(
                KnowledgeRelationModel.id,
                source.c.code.label("source_code"),
                source.c.title.label("source_title"),
                target.c.code.label("target_code"),
                target.c.title.label("target_title"),
                KnowledgeRelationModel.relation_type,
                KnowledgeRelationModel.confidence,
                KnowledgeRelationModel.source_ref,
            )
            .join(source, source.c.id == KnowledgeRelationModel.source_id)
            .join(target, target.c.id == KnowledgeRelationModel.target_id)
        )
        if subject_code:
            statement = statement.where(
                source.c.subject_code == subject_code,
                target.c.subject_code == subject_code,
            )
        statement = statement.order_by(source.c.code, target.c.code)
        with self.sessions() as session:
            return [dict(row) for row in session.execute(statement).mappings()]

    @staticmethod
    def _stale_objective_ids(
        session: Session,
        subject_code: str,
        valid_objective_ids: set[str],
    ) -> set[str]:
        rows = session.execute(
            select(KnowledgePointModel.id, KnowledgePointModel.features_json).where(
                KnowledgePointModel.subject_code == subject_code
            )
        )
        stale: set[str] = set()
        for point_id, raw_features in rows:
            try:
                features = json.loads(raw_features or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if (
                features.get("node_type") == "learning_objective"
                and point_id not in valid_objective_ids
            ):
                stale.add(str(point_id))
        return stale

    @staticmethod
    def _upsert_point(session: Session, values: Mapping[str, Any]) -> None:
        payload = dict(values)
        row = session.get(KnowledgePointModel, payload["id"])
        if row is None:
            session.add(KnowledgePointModel(**payload))
            return
        for field, value in payload.items():
            setattr(row, field, value)

    @staticmethod
    def _upsert_relation(session: Session, values: Mapping[str, Any]) -> None:
        payload = dict(values)
        row = session.scalar(
            select(KnowledgeRelationModel).where(
                KnowledgeRelationModel.source_id == payload["source_id"],
                KnowledgeRelationModel.target_id == payload["target_id"],
                KnowledgeRelationModel.relation_type == payload["relation_type"],
            )
        )
        if row is None:
            session.add(KnowledgeRelationModel(**payload))
            return
        row.confidence = payload["confidence"]
        row.source_ref = payload["source_ref"]

    @staticmethod
    def _upsert_evidence(session: Session, values: Mapping[str, Any]) -> None:
        payload = dict(values)
        statement = select(KnowledgeEvidenceModel).where(
            KnowledgeEvidenceModel.knowledge_point_id == payload["knowledge_point_id"],
            KnowledgeEvidenceModel.source_document_id == payload.get("source_document_id"),
            KnowledgeEvidenceModel.page == payload.get("page"),
            KnowledgeEvidenceModel.section == payload.get("section"),
            KnowledgeEvidenceModel.content_hash == payload["content_hash"],
            KnowledgeEvidenceModel.build_id == payload.get("build_id"),
        )
        row = session.scalar(statement)
        if row is None:
            session.add(KnowledgeEvidenceModel(**payload))
            return
        for field in (
            "section_path_json",
            "evidence_role",
            "excerpt",
            "confidence",
            "source_ref",
        ):
            setattr(row, field, payload[field])
