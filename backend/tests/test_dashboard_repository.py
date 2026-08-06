from __future__ import annotations

from examtwin.platform.database.models import (
    Base,
    KnowledgePointModel,
    KnowledgeRelationModel,
    SourceDocumentModel,
)
from examtwin.subjects.dashboard_repository import DashboardRepository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_dashboard_stats_are_scoped_to_the_active_subject() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with sessions.begin() as session:
        for relation_id, subject_code in enumerate(("9660", "9640"), start=1):
            session.add_all(
                [
                    SourceDocumentModel(
                        id=f"{subject_code}-qp",
                        subject_code=subject_code,
                        path=f"{subject_code}-qp.pdf",
                        filename=f"{subject_code}-qp.pdf",
                        source_type="question_paper",
                        authority_tier="official",
                        checksum=f"{subject_code}-qp",
                        pair_key=f"oxfordaqa:{subject_code}:2024:JUN:U1",
                        identity_status="complete",
                        status="discovered",
                    ),
                    SourceDocumentModel(
                        id=f"{subject_code}-ms",
                        subject_code=subject_code,
                        path=f"{subject_code}-ms.pdf",
                        filename=f"{subject_code}-ms.pdf",
                        source_type="mark_scheme",
                        authority_tier="official",
                        checksum=f"{subject_code}-ms",
                        pair_key=f"oxfordaqa:{subject_code}:2024:JUN:U1",
                        identity_status="complete",
                        status="discovered",
                    ),
                    KnowledgePointModel(
                        id=f"{subject_code}:ROOT",
                        subject_code=subject_code,
                        code="ROOT",
                        features_json='{"node_type":"subject"}',
                    ),
                    KnowledgePointModel(
                        id=f"{subject_code}:U1",
                        subject_code=subject_code,
                        code="U1",
                        parent_id=f"{subject_code}:ROOT",
                        features_json='{"node_type":"unit"}',
                    ),
                    KnowledgeRelationModel(
                        id=relation_id,
                        source_id=f"{subject_code}:ROOT",
                        target_id=f"{subject_code}:U1",
                        relation_type="contains",
                        confidence=1,
                        source_ref="official syllabus",
                    ),
                ]
            )

    result = DashboardRepository(sessions).stats(subject_code="9640")

    assert result["documents_total"] == 2
    assert result["documents_by_type"] == {"mark_scheme": 1, "question_paper": 1}
    assert result["strict_pairs"] == 1
    assert result["knowledge_points"] == 2
    assert result["relations"] == 1
