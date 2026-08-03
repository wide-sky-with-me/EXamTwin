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

    def stats(self) -> dict[str, Any]:
        with self.sessions() as session:
            documents_total = self._count(session, SourceDocumentModel)
            by_type = dict(
                session.execute(
                    select(SourceDocumentModel.source_type, func.count()).group_by(
                        SourceDocumentModel.source_type
                    )
                ).all()
            )
            by_status = dict(
                session.execute(
                    select(SourceDocumentModel.status, func.count()).group_by(
                        SourceDocumentModel.status
                    )
                ).all()
            )
            pairs: dict[str, set[str]] = defaultdict(set)
            pair_rows = session.execute(
                select(SourceDocumentModel.pair_key, SourceDocumentModel.source_type).where(
                    SourceDocumentModel.pair_key.is_not(None),
                    SourceDocumentModel.source_type.in_(("question_paper", "mark_scheme")),
                )
            )
            for pair_key, source_type in pair_rows:
                pairs[str(pair_key)].add(str(source_type))
            knowledge_points = self._count(session, KnowledgePointModel)
            relations = self._count(session, KnowledgeRelationModel)
            question_difficulty_rows = self._count(session, QuestionDifficultyModel)
            pending_reviews = int(
                session.scalar(
                    select(func.count())
                    .select_from(AssessmentModel)
                    .where(AssessmentModel.status == "pending_review")
                )
                or 0
            )
            exam_identity_incomplete = int(
                session.scalar(
                    select(func.count())
                    .select_from(SourceDocumentModel)
                    .where(SourceDocumentModel.identity_status == "incomplete")
                )
                or 0
            )
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

    @staticmethod
    def _count(session: Session, model: type[Any]) -> int:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)
