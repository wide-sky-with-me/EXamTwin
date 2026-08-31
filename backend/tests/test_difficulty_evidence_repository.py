from __future__ import annotations

import json
import uuid

import pytest
from examtwin.assessment.difficulty_evidence_repository import DifficultyEvidenceRepository
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import (
    QuestionDifficultyModel,
    SourceDocumentModel,
    SubjectModel,
)
from examtwin.platform.database.session import create_session_factory, utcnow
from sqlalchemy import delete, select


@pytest.mark.integration
def test_reviews_are_append_only_and_publication_is_idempotent_without_fake_b_score() -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    repository = DifficultyEvidenceRepository(sessions)
    token = uuid.uuid4().hex
    subject_id = f"difficulty-subject-{token}"
    subject_code = f"D{token[:8]}"
    report_id = f"difficulty-report-{token}"
    question_id = f"difficulty-question-{token}"
    run_id = f"difficulty-run-{token}"
    pair_key = f"{subject_code}:2026:JUN:U1"
    now = utcnow()

    with sessions.begin() as session:
        session.add(
            SubjectModel(
                id=subject_id,
                subject_code=subject_code,
                title="Difficulty test",
                board_name="Test board",
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
        session.flush()
        for document_id, source_type in (
            (report_id, "examiner_report"),
            (question_id, "question_paper"),
        ):
            session.add(
                SourceDocumentModel(
                    id=document_id,
                    subject_id=subject_id,
                    subject_code=subject_code,
                    path=f"/tmp/{document_id}.pdf",
                    filename=f"{document_id}.pdf",
                    display_name=document_id,
                    source_type=source_type,
                    authority_tier="official",
                    source_role="assessment_only",
                    license_confirmed=True,
                    checksum=f"checksum-{document_id}",
                    pair_key=pair_key,
                    unit_code="U1",
                    exam_year=2026,
                    exam_session="JUN",
                    identity_status="complete",
                    identity_error=None,
                    page_count=2,
                    status="converted",
                    object_key=None,
                    markdown_path=f"/tmp/{document_id}.md",
                    converted_source_checksum=f"checksum-{document_id}",
                    metadata_json="{}",
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    run_values = {
        "id": run_id,
        "subject_id": subject_id,
        "subject_code": subject_code,
        "source_document_id": report_id,
        "source_checksum": f"checksum-{report_id}",
        "question_paper_document_id": question_id,
        "question_paper_checksum": f"checksum-{question_id}",
        "question_catalog_json": '["A.1","B:essay"]',
        "question_catalog_hash": "catalog-hash",
        "pair_key": pair_key,
        "input_hash": f"input-{token}",
        "package_digest": "package-digest",
        "extractor_version": "extractor-v1",
        "model_name": "model-a",
        "prompt_digest": "prompt-digest",
        "status": "review_ready",
        "candidate_count": 2,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": now,
        "published_at": None,
    }
    common = {
        "run_id": run_id,
        "subject_id": subject_id,
        "subject_code": subject_code,
        "source_document_id": report_id,
        "source_checksum": f"checksum-{report_id}",
        "pair_key": pair_key,
        "unit_code": "U1",
        "page_number": 2,
        "quote_hash": "quote-hash",
        "block_hash": "block-hash",
        "source_ref": "document:report:page:2",
        "model_confidence": 0.9,
        "validation_status": "valid",
        "validation_errors_json": "[]",
        "created_at": now,
    }
    candidates = [
        {
            **common,
            "id": f"candidate-a-{token}",
            "question_number": "A.1",
            "evidence_level": "A",
            "evidence_type": "quantitative",
            "metric_name": "facility",
            "metric_text": "80%",
            "metric_value": 80.0,
            "metric_scale": "percent",
            "metric_direction": "success",
            "metric_comparator": "eq",
            "difficulty_score": 0.2,
            "quote": "80% answered this question correctly.",
        },
        {
            **common,
            "id": f"candidate-b-{token}",
            "question_number": "B:essay",
            "evidence_level": "B",
            "evidence_type": "qualitative",
            "metric_name": None,
            "metric_text": None,
            "metric_value": None,
            "metric_scale": None,
            "metric_direction": None,
            "metric_comparator": None,
            "difficulty_score": None,
            "quote": "Students found this question challenging.",
            "quote_hash": "quote-hash-b",
        },
    ]

    try:
        created = repository.create_or_reuse_run(run_values, candidates)
        reused = repository.create_or_reuse_run(run_values, candidates)
        assert created["id"] == reused["id"]
        assert len(created["candidates"]) == 2

        current = created
        for candidate in current["candidates"]:
            current = repository.append_review(
                subject_id=subject_id,
                run_id=run_id,
                candidate_id=candidate["id"],
                decision="accepted",
                reviewer="reviewer@example.test",
                notes=None,
                replacement={},
                expected_fingerprint=candidate["candidate_fingerprint"],
            )
        published = repository.publish_run(
            subject_id=subject_id,
            run_id=run_id,
            expected_fingerprint=current["run_fingerprint"],
            reviewer="reviewer@example.test",
        )
        repeated = repository.publish_run(
            subject_id=subject_id,
            run_id=run_id,
            expected_fingerprint="stale-is-ignored-after-success",
            reviewer="reviewer@example.test",
        )
        assert published["status"] == repeated["status"] == "published"

        with sessions() as session:
            rows = list(
                session.scalars(
                    select(QuestionDifficultyModel)
                    .where(QuestionDifficultyModel.publication_run_id == run_id)
                    .order_by(QuestionDifficultyModel.question_number)
                )
            )
        assert len(rows) == 2
        assert rows[0].difficulty_score == pytest.approx(0.2)
        assert rows[1].evidence_level == "B"
        assert rows[1].difficulty_score is None
        assert rows[1].difficulty_label is None
        assert json.loads(rows[1].evidence_json)["reviewer"] == "reviewer@example.test"
    finally:
        with sessions.begin() as session:
            session.execute(
                delete(QuestionDifficultyModel).where(
                    QuestionDifficultyModel.publication_run_id == run_id
                )
            )
            subject = session.get(SubjectModel, subject_id)
            if subject is not None:
                session.delete(subject)
