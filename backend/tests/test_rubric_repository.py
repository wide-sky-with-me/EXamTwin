from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from examtwin.assessment.rubric_repository import (
    RubricConflictError,
    RubricRepository,
    _rubric_criterion_sort_key,
)
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import (
    PaperJobModel,
    RubricCriterionAiReviewModel,
    RubricCriterionModel,
    RubricCriterionReviewModel,
    RubricSetModel,
    SourceDocumentModel,
    SubjectModel,
)
from examtwin.platform.database.session import create_session_factory, utcnow


def test_rubric_criteria_use_natural_question_and_mark_sequence() -> None:
    def criterion(question: str, subpart: str, criterion_id: str) -> RubricCriterionModel:
        return RubricCriterionModel(
            id=criterion_id,
            rubric_set_id="rubric",
            question_number=question,
            subpart=subpart,
            criterion_id=criterion_id,
            scoring_mode="point_based",
            max_marks=1,
            description=criterion_id,
            source_excerpt=criterion_id,
            confidence=1,
        )

    criteria = [
        criterion("10", "whole", "Q10-B1"),
        criterion("2", "whole", "Q2-A2"),
        criterion("2", "whole", "Q2-M2"),
        criterion("1", "(a)", "Q1a_A1"),
        criterion("2", "whole", "Q2-A1"),
        criterion("2", "whole", "Q2-M1"),
        criterion("1", "(a)", "Q1a_M1"),
    ]

    assert [item.criterion_id for item in sorted(criteria, key=_rubric_criterion_sort_key)] == [
        "Q1a_M1",
        "Q1a_A1",
        "Q2-M1",
        "Q2-A1",
        "Q2-M2",
        "Q2-A2",
        "Q10-B1",
    ]


@pytest.fixture
def rubric_repository_context() -> Iterator[dict[str, Any]]:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    token = uuid.uuid4().hex
    subject_id = f"subject-{token}"
    subject_code = f"R{token[:8]}"
    paper_ids = [f"paper-{token}-1", f"paper-{token}-2"]
    document_ids = [f"mark-scheme-{token}-1", f"mark-scheme-{token}-2"]
    now = utcnow()
    with sessions.begin() as session:
        session.add(
            SubjectModel(
                id=subject_id,
                subject_code=subject_code,
                title="Rubric repository subject",
                board_name="Test board",
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add_all(
            [
                PaperJobModel(
                    id=paper_id,
                    subject_pack_id="test-pack",
                    subject_code=subject_code,
                    filename=f"paper-{position}.pdf",
                    suffix=".pdf",
                    unit_code="U1",
                    source_path=f"paper-source-{position}",
                    status="completed",
                    stage="completed",
                    error=None,
                    created_at=now,
                    updated_at=now,
                )
                for position, paper_id in enumerate(paper_ids, start=1)
            ]
        )
        session.add_all(
            [
                SourceDocumentModel(
                    id=document_id,
                    subject_code=subject_code,
                    subject_id=subject_id,
                    path=f"/source/{document_id}.pdf",
                    filename=f"mark-scheme-{position}.pdf",
                    source_type="mark_scheme",
                    status="converted",
                    checksum=f"{token}-{position}",
                )
                for position, document_id in enumerate(document_ids, start=1)
            ]
        )

    repository = RubricRepository(sessions)
    first = repository.create(
        subject_id=subject_id,
        paper_job_id=paper_ids[0],
        source_document_id=document_ids[0],
        source_document_checksum=f"{token}-1",
        identity={"pair_key": "test:2024:JUN:U1"},
        parser_model="rubric-parser",
        warnings=[],
        criteria=[
            {
                "question_number": "1",
                "criterion_id": "1-B1",
                "scoring_mode": "point_based",
                "max_marks": 1,
                "description": "First criterion.",
                "source_excerpt": "B1",
                "confidence": 1,
            },
            {
                "question_number": "2",
                "criterion_id": "2-B1",
                "scoring_mode": "point_based",
                "max_marks": 1,
                "description": "Second criterion.",
                "source_excerpt": "B1",
                "confidence": 1,
            },
        ],
    )
    second = repository.create(
        subject_id=subject_id,
        paper_job_id=paper_ids[1],
        source_document_id=document_ids[1],
        source_document_checksum=f"{token}-2",
        identity={"pair_key": "test:2024:JUN:U1"},
        parser_model="rubric-parser",
        warnings=[],
        criteria=[
            {
                "question_number": "1",
                "criterion_id": "1-B1",
                "scoring_mode": "point_based",
                "max_marks": 1,
                "description": "Other rubric criterion.",
                "source_excerpt": "B1",
                "confidence": 1,
            }
        ],
    )
    rubric_ids = [str(first["id"]), str(second["id"])]
    try:
        yield {
            "repository": repository,
            "sessions": sessions,
            "subject_id": subject_id,
            "rubrics": [first, second],
            "source_checksum": f"{token}-1",
        }
    finally:
        with sessions.begin() as session:
            session.query(RubricCriterionAiReviewModel).filter(
                RubricCriterionAiReviewModel.rubric_set_id.in_(rubric_ids)
            ).delete(synchronize_session=False)
            session.query(RubricCriterionReviewModel).filter(
                RubricCriterionReviewModel.rubric_set_id.in_(rubric_ids)
            ).delete(synchronize_session=False)
            session.query(RubricCriterionModel).filter(
                RubricCriterionModel.rubric_set_id.in_(rubric_ids)
            ).delete(synchronize_session=False)
            session.query(RubricSetModel).filter(RubricSetModel.id.in_(rubric_ids)).delete(
                synchronize_session=False
            )
            session.query(SourceDocumentModel).filter(
                SourceDocumentModel.id.in_(document_ids)
            ).delete(synchronize_session=False)
            session.query(PaperJobModel).filter(PaperJobModel.id.in_(paper_ids)).delete(
                synchronize_session=False
            )
            session.query(SubjectModel).filter_by(id=subject_id).delete()


@pytest.mark.integration
def test_rubric_source_checksum_is_projected(
    rubric_repository_context: dict[str, Any],
) -> None:
    first = rubric_repository_context["rubrics"][0]

    assert first["source_document_checksum"] == rubric_repository_context["source_checksum"]


@pytest.mark.integration
def test_batch_review_validates_the_full_criterion_set_before_writing(
    rubric_repository_context: dict[str, Any],
) -> None:
    repository = rubric_repository_context["repository"]
    sessions = rubric_repository_context["sessions"]
    subject_id = rubric_repository_context["subject_id"]
    first, second = rubric_repository_context["rubrics"]
    rubric_id = str(first["id"])
    first_id = str(first["criteria"][0]["id"])
    second_id = str(first["criteria"][1]["id"])
    cross_rubric_id = str(second["criteria"][0]["id"])

    with pytest.raises(ValueError, match="重复"):
        repository.review_criteria_batch(
            rubric_id,
            subject_id=subject_id,
            reviewer="Teacher",
            decisions=[
                {"criterion_id": first_id, "review_status": "accepted"},
                {"criterion_id": first_id, "review_status": "rejected"},
            ],
        )
    with pytest.raises(LookupError, match="评分原子不存在"):
        repository.review_criteria_batch(
            rubric_id,
            subject_id=subject_id,
            reviewer="Teacher",
            decisions=[
                {"criterion_id": first_id, "review_status": "accepted"},
                {"criterion_id": cross_rubric_id, "review_status": "rejected"},
            ],
        )
    with pytest.raises(ValueError, match="max_marks"):
        repository.review_criteria_batch(
            rubric_id,
            subject_id=subject_id,
            reviewer="Teacher",
            decisions=[
                {"criterion_id": first_id, "review_status": "accepted"},
                {
                    "criterion_id": second_id,
                    "review_status": "accepted",
                    "updates": {"max_marks": -1},
                },
            ],
        )

    unchanged = repository.get(rubric_id, subject_id=subject_id)
    assert [criterion["review_status"] for criterion in unchanged["criteria"]] == [
        "pending",
        "pending",
    ]
    with sessions() as session:
        assert (
            session.query(RubricCriterionReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 0
        )

    reviewed = repository.review_criteria_batch(
        rubric_id,
        subject_id=subject_id,
        reviewer="Teacher",
        decisions=[
            {
                "criterion_id": first_id,
                "review_status": "accepted",
                "updates": {"description": "Edited first criterion."},
            },
            {"criterion_id": second_id, "review_status": "rejected", "note": "Not used."},
        ],
    )
    assert [criterion["review_status"] for criterion in reviewed["criteria"]] == [
        "accepted",
        "rejected",
    ]
    assert reviewed["criteria"][0]["description"] == "Edited first criterion."
    with sessions() as session:
        audits = session.query(RubricCriterionReviewModel).filter_by(rubric_set_id=rubric_id).all()
        assert len(audits) == 2
        assert {audit.criterion_id for audit in audits} == {first_id, second_id}


@pytest.mark.integration
def test_batch_ai_application_rejects_any_stale_fingerprint_before_writing(
    rubric_repository_context: dict[str, Any],
) -> None:
    repository = rubric_repository_context["repository"]
    sessions = rubric_repository_context["sessions"]
    subject_id = rubric_repository_context["subject_id"]
    first = rubric_repository_context["rubrics"][0]
    rubric_id = str(first["id"])
    first_id = str(first["criteria"][0]["id"])
    second_id = str(first["criteria"][1]["id"])
    first_fingerprint = str(first["criteria"][0]["criterion_fingerprint"])
    stale_fingerprint = "0" * 64
    if stale_fingerprint == str(first["criteria"][1]["criterion_fingerprint"]):
        stale_fingerprint = "1" * 64

    with pytest.raises(RubricConflictError, match="发生变化"):
        repository.review_criteria_batch(
            rubric_id,
            subject_id=subject_id,
            reviewer="Teacher",
            decisions=[
                {
                    "criterion_id": first_id,
                    "review_status": "accepted",
                    "expected_criterion_fingerprint": first_fingerprint,
                },
                {
                    "criterion_id": second_id,
                    "review_status": "rejected",
                    "expected_criterion_fingerprint": stale_fingerprint,
                },
            ],
        )

    unchanged = repository.get(rubric_id, subject_id=subject_id)
    assert [criterion["review_status"] for criterion in unchanged["criteria"]] == [
        "pending",
        "pending",
    ]
    with sessions() as session:
        assert (
            session.query(RubricCriterionReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 0
        )


@pytest.mark.integration
def test_ai_review_draft_race_raises_conflict_before_writing(
    rubric_repository_context: dict[str, Any],
) -> None:
    repository = rubric_repository_context["repository"]
    sessions = rubric_repository_context["sessions"]
    subject_id = rubric_repository_context["subject_id"]
    first = rubric_repository_context["rubrics"][0]
    rubric_id = str(first["id"])
    criterion_id = str(first["criteria"][0]["id"])
    criterion_fingerprint = str(first["criteria"][0]["criterion_fingerprint"])

    with sessions.begin() as session:
        session.query(RubricSetModel).filter_by(id=rubric_id).update({"status": "confirmed"})

    with pytest.raises(RubricConflictError, match="草稿"):
        repository.record_ai_reviews(
            rubric_id,
            subject_id=subject_id,
            model="review-model",
            reviews=[
                {
                    "criterion_id": criterion_id,
                    "criterion_fingerprint": criterion_fingerprint,
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Review completed against the former draft.",
                    "suggested_updates": None,
                }
            ],
        )

    with sessions() as session:
        assert (
            session.query(RubricCriterionAiReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 0
        )


@pytest.mark.integration
def test_ai_review_projection_is_latest_and_does_not_change_human_review_fields(
    rubric_repository_context: dict[str, Any],
) -> None:
    repository = rubric_repository_context["repository"]
    sessions = rubric_repository_context["sessions"]
    subject_id = rubric_repository_context["subject_id"]
    first, second = rubric_repository_context["rubrics"]
    rubric_id = str(first["id"])
    criterion_id = str(first["criteria"][0]["id"])
    cross_rubric_id = str(second["criteria"][0]["id"])
    criterion_fingerprint = str(first["criteria"][0]["criterion_fingerprint"])
    cross_rubric_fingerprint = str(second["criteria"][0]["criterion_fingerprint"])

    with pytest.raises(LookupError, match="评分原子不存在"):
        repository.record_ai_reviews(
            rubric_id,
            subject_id=subject_id,
            model="review-model",
            reviews=[
                {
                    "criterion_id": criterion_id,
                    "criterion_fingerprint": criterion_fingerprint,
                    "recommendation": "accept",
                    "confidence": 0.8,
                    "rationale": "Matches the source.",
                    "suggested_updates": None,
                },
                {
                    "criterion_id": cross_rubric_id,
                    "criterion_fingerprint": cross_rubric_fingerprint,
                    "recommendation": "reject",
                    "confidence": 0.7,
                    "rationale": "Belongs elsewhere.",
                    "suggested_updates": None,
                },
            ],
        )
    with pytest.raises(ValueError, match="max_marks"):
        repository.record_ai_reviews(
            rubric_id,
            subject_id=subject_id,
            model="review-model",
            reviews=[
                {
                    "criterion_id": criterion_id,
                    "criterion_fingerprint": criterion_fingerprint,
                    "recommendation": "revise",
                    "confidence": 0.8,
                    "rationale": "Invalid patch.",
                    "suggested_updates": {"max_marks": -1},
                }
            ],
        )
    with sessions() as session:
        assert (
            session.query(RubricCriterionAiReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 0
        )
    repository.review_criterion(
        rubric_id,
        criterion_id,
        subject_id=subject_id,
        review_status="accepted",
        reviewer="Teacher",
        note=None,
        updates={"description": "Human-edited criterion."},
    )
    with pytest.raises(RubricConflictError, match="发生变化"):
        repository.record_ai_reviews(
            rubric_id,
            subject_id=subject_id,
            model="review-model",
            reviews=[
                {
                    "criterion_id": criterion_id,
                    "criterion_fingerprint": criterion_fingerprint,
                    "recommendation": "accept",
                    "confidence": 0.9,
                    "rationale": "Stale review.",
                    "suggested_updates": None,
                }
            ],
        )
    with sessions() as session:
        assert (
            session.query(RubricCriterionAiReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 0
        )
    current = repository.get(rubric_id, subject_id=subject_id)
    criterion_fingerprint = str(current["criteria"][0]["criterion_fingerprint"])

    for recommendation, rationale in [
        ("accept", "Initial review."),
        ("revise", "Later review."),
    ]:
        repository.record_ai_reviews(
            rubric_id,
            subject_id=subject_id,
            model="review-model",
            reviews=[
                {
                    "criterion_id": criterion_id,
                    "criterion_fingerprint": criterion_fingerprint,
                    "recommendation": recommendation,
                    "confidence": 0.9,
                    "rationale": rationale,
                    "suggested_updates": {"description": rationale},
                }
            ],
        )

    tied_at = utcnow()
    with sessions.begin() as session:
        rows = (
            session.query(RubricCriterionAiReviewModel)
            .filter_by(rubric_set_id=rubric_id, criterion_id=criterion_id)
            .all()
        )
        assert len(rows) == 2
        for row in rows:
            row.created_at = tied_at
        expected = max(rows, key=lambda row: row.id)
        expected_recommendation = expected.recommendation
        expected_rationale = expected.rationale

    refreshed = repository.get(rubric_id, subject_id=subject_id)
    criterion = refreshed["criteria"][0]
    assert criterion["review_status"] == "accepted"
    assert criterion["reviewed_by"] == "Teacher"
    assert criterion["reviewed_at"] is not None
    assert criterion["ai_review"]["recommendation"] == expected_recommendation
    assert criterion["ai_review"]["rationale"] == expected_rationale
    assert criterion["ai_review"]["model"] == "review-model"
    assert criterion["ai_review"]["reviewed_at"] == tied_at
    assert criterion["ai_review"]["criterion_fingerprint"] == criterion_fingerprint

    repository.review_criterion(
        rubric_id,
        criterion_id,
        subject_id=subject_id,
        review_status="accepted",
        reviewer="Teacher",
        note="Changed after AI review.",
        updates={"description": "Post-AI human edit."},
    )
    post_edit = repository.get(rubric_id, subject_id=subject_id)
    assert post_edit["criteria"][0]["ai_review"] is None
    with sessions() as session:
        assert (
            session.query(RubricCriterionAiReviewModel).filter_by(rubric_set_id=rubric_id).count()
            == 2
        )
