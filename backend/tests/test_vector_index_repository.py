from __future__ import annotations

from datetime import UTC, datetime

from examtwin.persistence.models import Base, SourceDocumentModel
from examtwin.persistence.vector_index_repository import VectorIndexRepository
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_vector_repository_owns_build_and_document_index_state() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    repository = VectorIndexRepository(sessions)
    now = datetime(2026, 8, 3, tzinfo=UTC)
    with sessions.begin() as session:
        session.add_all(
            [
                SourceDocumentModel(
                    id="math",
                    subject_code="9660",
                    path="math.md",
                    filename="math.md",
                    source_type="syllabus",
                    authority_tier="official",
                    checksum="abc",
                    status="converted",
                    markdown_path="math.md",
                ),
                SourceDocumentModel(
                    id="economics",
                    subject_code="9640",
                    path="economics.md",
                    filename="economics.md",
                    source_type="syllabus",
                    authority_tier="official",
                    checksum="def",
                    status="converted",
                    markdown_path="economics.md",
                ),
            ]
        )
    repository.create_run(
        {
            "id": "run-1",
            "subject_code": "9660",
            "alias_name": "math_live",
            "staging_collection": "math_staging_1",
            "previous_collection": "math_v1",
            "status": "running",
            "stage": "embedding",
            "input_hash": "hash",
            "expected_points": 2,
            "indexed_points": 1,
            "document_count": 1,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
        }
    )

    assert [row["id"] for row in repository.indexable_documents(subject_code="9660")] == ["math"]
    assert repository.latest_resumable(subject_code="9660", alias_name="math_live") == {
        "id": "run-1",
        "staging_collection": "math_staging_1",
        "input_hash": "hash",
        "expected_points": 2,
    }

    repository.mark_documents_indexed(["math"])
    assert repository.indexable_documents(subject_code="9660")[0]["id"] == "math"
