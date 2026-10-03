from datetime import UTC, datetime
from uuid import uuid4

import pytest
from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_unit_repository import PaperUnitRepository
from examtwin.assessment.paper_units import PaperUnitService
from examtwin.knowledge.corpus_repository import CorpusRepository, DocumentInUseError
from examtwin.platform.config import Settings
from examtwin.platform.database.models import (
    AssessmentModel,
    Base,
    DifficultyEvidenceRunModel,
    KnowledgePointModel,
    PaperJobModel,
    PaperUnitModel,
    SourceDocumentModel,
    SubjectModel,
)
from examtwin.subjects.public import subject_context
from examtwin.subjects.workspace_repository import WorkspaceRepository
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


def _completed_job(sessions: sessionmaker[Session], paper_unit_id: str) -> str:
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
                paper_unit_id=paper_unit_id,
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

    return job_id


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
    _completed_job(sessions, str(created["id"]))

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


def test_bound_document_cannot_be_archived_until_its_paper_is_permanently_deleted() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    created = service.create_unit(["qp"], display_name="June paper")

    with pytest.raises(DocumentInUseError, match="「June paper」"):
        service.documents.archive("qp", subject_code="9660")
    service.archive_unit(str(created["id"]))
    with pytest.raises(DocumentInUseError, match="回收站"):
        service.documents.archive("qp", subject_code="9660")
    assert service.documents.get_active("qp") is not None

    _document(sessions, subject_id, "loose", "mark_scheme", "9660:2025:JUN:P1")
    service.documents.archive("loose", subject_code="9660")
    assert service.documents.get_active("loose") is None


def test_answer_records_and_review_queue_expose_grading_progress_and_paper() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    created = service.create_unit(["qp"], display_name=None)
    job_id = _completed_job(sessions, str(created["id"]))
    ungraded_job_id = _completed_job(sessions, str(created["id"]))
    now = datetime(2026, 8, 13, tzinfo=UTC)
    with sessions.begin() as session:
        for index, (position, status) in enumerate(
            [(0, "confirmed"), (0, "pending_review"), (1, "pending_review")]
        ):
            session.add(
                AssessmentModel(
                    id=f"assessment-{index}",
                    subject_code="9660",
                    paper_job_id=job_id,
                    question_position=position,
                    rubric_set_id="rubric",
                    question_ref=f"Q{position + 1}",
                    answer_markdown="answer",
                    total_awarded=1,
                    total_available=2,
                    confidence=0.5,
                    status=status,
                    result_json="{}",
                    created_at=now,
                    updated_at=now,
                )
            )

    progress = PaperJobRepository(sessions, lease_seconds=60).grading_progress(
        [job_id, ungraded_job_id]
    )
    assert progress == {job_id: (2, 2)}
    pending = AssessmentRepository(sessions).pending(subject_code="9660")
    assert {item["paper_unit_id"] for item in pending} == {created["id"]}


def test_job_deletion_rejects_unknown_ids_without_deleting_the_valid_ones() -> None:
    service, sessions, subject_id = _service()
    _document(sessions, subject_id, "qp", "question_paper")
    created = service.create_unit(["qp"], display_name=None)
    job_id = _completed_job(sessions, str(created["id"]))
    jobs = PaperJobRepository(sessions, lease_seconds=60)

    with pytest.raises(LookupError, match="不存在"):
        jobs.delete_releasable((job_id, "missing-job"), "9660", terminal_statuses=("completed",))
    assert jobs.get(job_id) is not None
    assert jobs.delete_releasable((job_id,), "9660", terminal_statuses=("completed",)) == 1


def _enforce_sqlite_foreign_keys(sessions: sessionmaker[Session]) -> None:
    # The in-memory database lives on one pooled connection; enable enforcement on it so
    # RESTRICT bindings are exercised like on PostgreSQL.
    with sessions.kw["bind"].connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_subject_with_papers_and_difficulty_evidence_can_be_deleted() -> None:
    service, sessions, subject_id = _service()
    _enforce_sqlite_foreign_keys(sessions)
    _document(sessions, subject_id, "qp", "question_paper")
    _document(sessions, subject_id, "er", "examiner_report")
    created = service.create_unit(["qp"], display_name=None)
    job_id = _completed_job(sessions, str(created["id"]))
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(
            DifficultyEvidenceRunModel(
                id="run-1",
                subject_id=subject_id,
                subject_code="9660",
                source_document_id="er",
                source_checksum="checksum-er",
                question_paper_document_id="qp",
                question_paper_checksum="checksum-qp",
                question_catalog_json="[]",
                question_catalog_hash="catalog",
                pair_key="9660:2024:JUN:P1",
                input_hash="input",
                package_digest="package",
                extractor_version="v1",
                model_name="test",
                prompt_digest="prompt",
                status="completed",
                error=None,
                created_at=now,
                updated_at=now,
                completed_at=now,
                published_at=None,
            )
        )
        session.add(
            KnowledgePointModel(
                id="kp-1", subject_code="9660", code="1.1", features_json="{}", updated_at=now
            )
        )

    # Documents are bound to the paper unit and the evidence run with RESTRICT; deletion must
    # remove those first instead of failing on the foreign keys.
    assert WorkspaceRepository(sessions).delete_subjects([subject_id]) == [subject_id]
    with sessions() as session:
        for model, key in (
            (PaperUnitModel, str(created["id"])),
            (PaperJobModel, job_id),
            (SourceDocumentModel, "qp"),
            (SourceDocumentModel, "er"),
            (DifficultyEvidenceRunModel, "run-1"),
            (KnowledgePointModel, "kp-1"),
            (SubjectModel, subject_id),
        ):
            assert session.get(model, key) is None, model.__name__
