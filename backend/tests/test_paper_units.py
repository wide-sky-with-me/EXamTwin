from datetime import UTC, datetime
from uuid import uuid4

import pytest
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_unit_repository import PaperUnitRepository
from examtwin.assessment.paper_units import PaperUnitService
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.platform.config import Settings
from examtwin.platform.database.models import (
    Base,
    PaperJobModel,
    SourceDocumentModel,
    SubjectModel,
)
from examtwin.subjects.public import subject_context
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _service() -> tuple[PaperUnitService, sessionmaker[Session], str]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    settings = Settings()
    subject = subject_context(settings)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(
            SubjectModel(
                id=subject.id,
                subject_code=subject.subject_code,
                title=subject.pack.title,
                board_name="OxfordAQA",
                language="en",
                icon="book-open",
                color="#2F6FED",
                capability_profile_id=None,
                active_graph_version_id=None,
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
    return (
        PaperUnitService(subject, PaperUnitRepository(sessions), CorpusRepository(sessions)),
        sessions,
        subject.id,
    )


def _document(
    sessions: sessionmaker[Session],
    subject_id: str,
    document_id: str,
    source_type: str,
    pair_key: str = "9660:2024:JUN:P1",
) -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(
            SourceDocumentModel(
                id=document_id,
                subject_id=subject_id,
                subject_code="9660",
                knowledge_base_id=None,
                path=f"object://{document_id}.pdf",
                filename=f"{document_id}.pdf",
                display_name=None,
                source_type=source_type,
                authority_tier="assessment",
                source_role="assessment_only",
                license_confirmed=False,
                checksum=f"checksum-{document_id}",
                pair_key=pair_key,
                unit_code="P1",
                exam_year=2024,
                exam_session="JUN",
                identity_status="complete",
                identity_error=None,
                page_count=2,
                status="converted",
                object_key=f"documents/{document_id}.pdf",
                markdown_path=f"documents/{document_id}.md",
                converted_source_checksum=f"checksum-{document_id}",
                metadata_json="{}",
                error=None,
                created_at=now,
                updated_at=now,
            )
        )


def test_paper_unit_preserves_multiple_documents_and_filters_server_side() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp-one", "question_paper")
    _document(sessions, subject_id, "qp-two", "question_paper")
    _document(sessions, subject_id, "ms", "mark_scheme")
    _document(sessions, subject_id, "insert", "insert")

    created = service.create_unit(
        ["qp-one", "qp-two", "ms", "insert"],
        display_name="June paper",
    )
    items, total, facets = service.list_units(
        query="qp-two",
        unit_code="P1",
        exam_year=2024,
        exam_session="JUN",
        limit=10,
        offset=0,
    )

    assert total == 1
    assert items[0]["id"] == created["id"]
    assert [(item["id"], item["role"]) for item in created["documents"]] == [
        ("ms", "mark_scheme"),
        ("qp-one", "question_paper"),
        ("qp-two", "question_paper"),
        ("insert", "source_booklet"),
    ]
    assert facets == {"units": ["P1"], "years": [2024], "sessions": ["JUN"]}


def test_paper_unit_rejects_near_pair_and_document_reuse() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    _document(sessions, subject_id, "near-ms", "mark_scheme", "9660:2024:NOV:P1")

    with pytest.raises(ValueError, match="完全一致"):
        service.create_unit(["qp", "near-ms"], display_name=None)

    created = service.create_unit(["qp"], display_name=None)
    assert created["pair_key"] == "9660:2024:JUN:P1"
    retried = service.create_unit(["qp"], display_name="Retried name")
    assert retried["id"] == created["id"]
    assert retried["display_name"] == "Retried name"

    _document(sessions, subject_id, "replacement-qp", "question_paper")
    with pytest.raises(ValueError, match="已存在"):
        service.create_unit(["replacement-qp"], display_name=None)


def test_paper_unit_reactivates_archived_pair_with_its_deduplicated_documents() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    _document(sessions, subject_id, "ms", "mark_scheme")
    created = service.create_unit(["qp", "ms"], display_name="Original name")

    service.archive_unit(str(created["id"]))
    restored = service.create_unit(["qp", "ms"], display_name="Restored name")

    assert restored["id"] == created["id"]
    assert restored["status"] == "active"
    assert restored["display_name"] == "Restored name"
    assert [(item["id"], item["role"]) for item in restored["documents"]] == [
        ("ms", "mark_scheme"),
        ("qp", "question_paper"),
    ]


def test_paper_unit_trash_preserves_lineage_and_permanent_delete_removes_it() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    created = service.create_unit(["qp"], display_name=None)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    job_id = str(uuid4())
    with sessions.begin() as session:
        session.add(
            PaperJobModel(
                id=job_id,
                subject_pack_id="oxfordaqa-mathematics-9660",
                subject_code="9660",
                knowledge_base_version_ids_json="[]",
                knowledge_collection_names_json="[]",
                graph_version_id=None,
                source_integrity_status="verified",
                split_contract_version="v1",
                split_source_digest="digest",
                replacement_for_job_id=None,
                filename="qp.pdf",
                display_name=None,
                suffix=".pdf",
                answer_mode="generated",
                answer_filename=None,
                answer_suffix=None,
                answer_source_path=None,
                pair_key="9660:2024:JUN:P1",
                paper_unit_id=created["id"],
                question_paper_document_id="qp",
                source_booklet_document_id=None,
                source_booklet_checksum=None,
                source_booklet_filename=None,
                unit_code="P1",
                source_path=f"{job_id}/source.pdf",
                status="completed",
                stage="completed",
                total_pages=1,
                parsed_pages=1,
                total_questions=1,
                completed_questions=1,
                failed_questions=0,
                error=None,
                lease_token=None,
                lease_expires_at=None,
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=now,
            )
        )

    jobs = PaperJobRepository(sessions, lease_seconds=60)
    service.archive_unit(str(created["id"]))
    trashed, total, _facets = service.list_trash()
    assert total == 1
    assert trashed[0]["id"] == created["id"]
    assert trashed[0]["paper_job_count"] == 1
    assert jobs.list_for_subject("9660", paper_unit_id=str(created["id"]))[1] == 1

    restored = service.restore_unit(str(created["id"]))
    assert restored["status"] == "active"
    assert jobs.list_for_subject("9660", paper_unit_id=str(created["id"]))[1] == 1

    service.archive_unit(str(created["id"]))
    service.permanently_delete_unit(str(created["id"]))
    assert service.list_trash()[1] == 0
    assert jobs.list_for_subject("9660", paper_unit_id=str(created["id"]))[1] == 0
    assert service.documents.get_active("qp") is None
