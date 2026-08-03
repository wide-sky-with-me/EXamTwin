import json

import pytest
from examtwin.config import get_settings
from examtwin.persistence.assessment_repository import AssessmentRepository
from examtwin.persistence.corpus_repository import CorpusRepository
from examtwin.persistence.migrations import upgrade_database
from examtwin.persistence.models import AssessmentModel, ReviewModel
from examtwin.persistence.session import create_session_factory
from examtwin.schemas import (
    ExpectedExpression,
    GradeRequest,
    ReviewRequest,
)
from examtwin.services.grading import GradingService, symbolic_checks


class FakeResponse:
    text = json.dumps(
        {
            "total_available": 2,
            "rubric_awards": [
                {
                    "criterion_id": "1.M1",
                    "description": "valid method",
                    "mark_type": "M1",
                    "max_marks": 1,
                    "awarded": 1,
                    "student_evidence": "rearranged",
                    "rationale": "Method is visible.",
                    "confidence": 0.9,
                    "source_ref": "MS 1.M1",
                },
                {
                    "criterion_id": "1.A1",
                    "description": "correct answer",
                    "mark_type": "A1",
                    "max_marks": 1,
                    "awarded": 0,
                    "student_evidence": None,
                    "rationale": "No final value is present.",
                    "confidence": 0.95,
                    "source_ref": "MS 1.A1",
                },
            ],
            "warnings": [],
        }
    )


class FakeLLM:
    def complete(self, _: str) -> FakeResponse:
        return FakeResponse()


def test_safe_symbolic_equivalence() -> None:
    request = GradeRequest(
        question_markdown="Simplify.",
        mark_scheme_markdown="A1 for x^2 - 1.",
        answer_markdown="(x-1)(x+1)",
        expected_expressions=[
            ExpectedExpression(student="(x-1)*(x+1)", expected="x^2-1", variable="x")
        ],
    )
    result = symbolic_checks(request)
    assert result[0].equivalent is True


def test_symbolic_check_rejects_unsafe_input() -> None:
    request = GradeRequest(
        question_markdown="Q",
        mark_scheme_markdown="MS",
        answer_markdown="A",
        expected_expressions=[ExpectedExpression(student="__import__('os')", expected="0")],
    )
    result = symbolic_checks(request)
    assert result[0].equivalent is None


@pytest.mark.integration
def test_grading_always_enters_review_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    monkeypatch.setattr("examtwin.services.grading.build_llm", lambda *_args, **_kwargs: FakeLLM())
    service = GradingService(
        CorpusRepository(sessions),
        AssessmentRepository(sessions),
        settings,
    )
    result = service.grade(
        GradeRequest(
            question_markdown="Solve x = 2.",
            mark_scheme_markdown="M1 rearrange. A1 answer 2.",
            answer_markdown="I rearranged the equation.",
            max_marks=2,
        )
    )
    try:
        assert result.total_awarded == 1
        assert result.status == "pending_review"
        assert result.manual_review_required is True
        reviewed = service.review(
            result.assessment_id,
            ReviewRequest(reviewer="pytest", decision="confirm"),
        )
        assert reviewed["status"] == "confirmed"
    finally:
        with sessions.begin() as session:
            session.query(ReviewModel).filter_by(assessment_id=result.assessment_id).delete()
            session.query(AssessmentModel).filter_by(id=result.assessment_id).delete()
