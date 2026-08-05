from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import (
    AssessmentModel,
    KnowledgePointModel,
    KnowledgeRelationModel,
    QuestionDifficultyModel,
    SourceDocumentModel,
)


class DashboardRepository:
    """Own the cross-domain read model used by the operations overview."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def stats(self, *, subject_code: str | None = None) -> dict[str, Any]:
        with self.sessions() as session:
            document_scope = (
                SourceDocumentModel.subject_code == subject_code if subject_code else None
            )
            document_count = select(func.count()).select_from(SourceDocumentModel)
            type_counts = select(SourceDocumentModel.source_type, func.count())
            status_counts = select(SourceDocumentModel.status, func.count())
            if document_scope is not None:
                document_count = document_count.where(document_scope)
                type_counts = type_counts.where(document_scope)
                status_counts = status_counts.where(document_scope)
            documents_total = int(session.scalar(document_count) or 0)
            by_type = {
                str(source_type): int(count)
                for source_type, count in session.execute(
                    type_counts.group_by(SourceDocumentModel.source_type)
                )
            }
            by_status = {
                str(status): int(count)
                for status, count in session.execute(
                    status_counts.group_by(SourceDocumentModel.status)
                )
            }
            pairs: dict[str, set[str]] = defaultdict(set)
            pair_statement = select(
                SourceDocumentModel.pair_key,
                SourceDocumentModel.source_type,
            ).where(
                SourceDocumentModel.pair_key.is_not(None),
                SourceDocumentModel.source_type.in_(("question_paper", "mark_scheme")),
            )
            if document_scope is not None:
                pair_statement = pair_statement.where(document_scope)
            pair_rows = session.execute(pair_statement)
            for pair_key, source_type in pair_rows:
                pairs[str(pair_key)].add(str(source_type))
            point_ids = select(KnowledgePointModel.id)
            point_count = select(func.count()).select_from(KnowledgePointModel)
            difficulty_count = (
                select(func.count())
                .select_from(QuestionDifficultyModel)
                .join(
                    SourceDocumentModel,
                    SourceDocumentModel.id == QuestionDifficultyModel.source_document_id,
                )
            )
            if subject_code:
                point_ids = point_ids.where(KnowledgePointModel.subject_code == subject_code)
                point_count = point_count.where(KnowledgePointModel.subject_code == subject_code)
                difficulty_count = difficulty_count.where(
                    SourceDocumentModel.subject_code == subject_code
                )
            knowledge_points = int(session.scalar(point_count) or 0)
            relation_count = select(func.count()).select_from(KnowledgeRelationModel)
            if subject_code:
                relation_count = relation_count.where(
                    KnowledgeRelationModel.source_id.in_(point_ids),
                    KnowledgeRelationModel.target_id.in_(point_ids),
                )
            relations = int(session.scalar(relation_count) or 0)
            question_difficulty_rows = int(session.scalar(difficulty_count) or 0)
            pending_review_count = (
                select(func.count())
                .select_from(AssessmentModel)
                .where(AssessmentModel.status == "pending_review")
            )
            if subject_code:
                pending_review_count = pending_review_count.where(
                    AssessmentModel.subject_code == subject_code
                )
            pending_reviews = int(session.scalar(pending_review_count) or 0)
            incomplete_count = (
                select(func.count())
                .select_from(SourceDocumentModel)
                .where(SourceDocumentModel.identity_status == "incomplete")
            )
            if document_scope is not None:
                incomplete_count = incomplete_count.where(document_scope)
            exam_identity_incomplete = int(session.scalar(incomplete_count) or 0)
        return {
            "documents_total": documents_total,
            "documents_by_type": by_type,
            "documents_by_status": by_status,
            "strict_pairs": sum(
                source_types == {"question_paper", "mark_scheme"} for source_types in pairs.values()
            ),
            "orphan_question_papers": sum(
                source_types == {"question_paper"} for source_types in pairs.values()
            ),
            "orphan_mark_schemes": sum(
                source_types == {"mark_scheme"} for source_types in pairs.values()
            ),
            "knowledge_points": knowledge_points,
            "relations": relations,
            "question_difficulty_rows": question_difficulty_rows,
            "pending_reviews": pending_reviews,
            "exam_identity_incomplete": exam_identity_incomplete,
        }
