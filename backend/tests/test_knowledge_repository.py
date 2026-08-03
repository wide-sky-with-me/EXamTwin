from datetime import UTC, datetime

from examtwin.persistence.knowledge_build_repository import KnowledgeBuildRepository
from examtwin.persistence.models import (
    Base,
    CurriculumCandidateModel,
    KnowledgePointModel,
    SourceDocumentModel,
)
from examtwin.persistence.session import sqlalchemy_database_url
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_repository_owns_run_checkpoints_and_syllabus_priority() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = KnowledgeBuildRepository(sessions)
    created_at = datetime(2026, 8, 3, tzinfo=UTC)
    later = datetime(2026, 8, 3, 0, 1, tzinfo=UTC)
    with sessions.begin() as session:
        session.add_all(
            [
                SourceDocumentModel(
                    id="converted",
                    subject_code="9660",
                    path="converted.pdf",
                    source_type="syllabus",
                    status="converted",
                    markdown_path="converted.md",
                ),
                SourceDocumentModel(
                    id="indexed",
                    subject_code="9660",
                    path="indexed.pdf",
                    source_type="syllabus",
                    status="indexed",
                    markdown_path="indexed.md",
                ),
            ]
        )
        session.add_all(
            [
                KnowledgePointModel(
                    id="9660:P1.1",
                    subject_code="9660",
                    code="P1.1",
                    features_json='{"node_type":"topic"}',
                ),
                KnowledgePointModel(
                    id="9660:P1.1.O01",
                    subject_code="9660",
                    code="P1.1.O01",
                    features_json='{"node_type":"learning_objective"}',
                ),
            ]
        )

    repository.create_run(
        {
            "id": "run-1",
            "subject_pack_id": "pack",
            "subject_code": "9660",
            "source_document_id": None,
            "status": "running",
            "stage": "loading_syllabus",
            "pipeline_version": "v1",
            "input_hash": "hash",
            "ai_model": "model",
            "config_json": "{}",
            "metrics_json": "{}",
            "artifact_json": '{"difficulty_assessments": [{"code": "P1.1.O01"}]}',
            "error": None,
            "created_at": created_at,
            "updated_at": created_at,
            "completed_at": None,
        }
    )
    repository.update_run(
        "run-1",
        {"stage": "assessing_difficulty:20/100", "updated_at": later},
    )
    repository.create_candidate(
        {
            "id": "candidate-1",
            "build_run_id": "run-1",
            "subject_pack_id": "pack",
            "subject_code": "9660",
            "source_document_id": "indexed",
            "input_hash": "hash",
            "content_hash": "content-hash",
            "extractor_version": "extractor-v1",
            "status": "ready",
            "review_status": "auto_approved",
            "candidate_json": "{}",
            "validation_json": "{}",
            "created_at": created_at,
            "updated_at": created_at,
            "published_at": None,
        }
    )
    repository.update_candidate(
        "candidate-1",
        {"status": "published", "updated_at": later, "published_at": later},
    )

    assert repository.syllabus_document("9660")["id"] == "indexed"  # type: ignore[index]
    assert repository.cached_artifacts(
        subject_code="9660",
        input_hash="hash",
        ai_model="model",
    ) == ['{"difficulty_assessments": [{"code": "P1.1.O01"}]}']
    assert repository.published_graph_codes("9660") == {
        "topics": {"P1.1"},
        "objectives": {"P1.1.O01"},
    }
    with sessions() as session:
        assert session.get(CurriculumCandidateModel, "candidate-1").status == "published"  # type: ignore[union-attr]


def test_sqlalchemy_uses_the_installed_psycopg3_driver() -> None:
    assert (
        sqlalchemy_database_url("postgresql://user:pass@db/name")
        == "postgresql+psycopg://user:pass@db/name"
    )
    assert sqlalchemy_database_url("sqlite+pysqlite:///:memory:").startswith("sqlite+pysqlite")
