import json
from collections.abc import Sequence
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, TypeVar, cast

import pytest
from examtwin.assessment.assessment_repository import AssessmentRepository
from examtwin.assessment.grading import GradingService, symbolic_checks
from examtwin.contracts import (
    ExpectedExpression,
    GradeRequest,
    ReviewRequest,
)
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.platform.agent_runtime import HarnessMessage
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import AssessmentModel, ReviewModel
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import subject_context, subject_package_registry
from examtwin.subjects.workspace_repository import WorkspaceRepository
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


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


class FakeStructuredModel:
    model_name = "fake-grading-model"

    def complete(
        self,
        _messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        return response_model.model_validate(json.loads(FakeResponse.text))


class CorrectingEvidenceModel:
    model_name = "correcting-grading-model"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        _messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        self.calls += 1
        payload = json.loads(FakeResponse.text)
        payload["rubric_awards"][0]["student_evidence"] = (
            "The student rearranged the equation."
            if self.calls == 1
            else "I rearranged the equation."
        )
        return response_model.model_validate(payload)


class PersistentlyNonVerbatimEvidenceModel(CorrectingEvidenceModel):
    model_name = "persistently-non-verbatim-grading-model"

    def complete(
        self,
        _messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        assert timeout > 0
        self.calls += 1
        payload = json.loads(FakeResponse.text)
        payload["rubric_awards"][0]["student_evidence"] = "The student rearranged it."
        return response_model.model_validate(payload)


class CapturingAssessments:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def create(self, values: dict[str, Any]) -> None:
        self.created.append(values)


def test_grading_retries_until_student_evidence_is_verbatim() -> None:
    model = CorrectingEvidenceModel()
    assessments = CapturingAssessments()
    settings = get_settings()
    service = GradingService(
        cast(Any, SimpleNamespace()),
        cast(Any, assessments),
        settings,
        subject_context(settings),
        structured_model=model,
    )

    result = service.grade(
        GradeRequest(
            question_markdown="Solve x = 2.",
            mark_scheme_markdown="M1 rearrange. A1 answer 2.",
            answer_markdown="I rearranged the equation.",
            max_marks=2,
        )
    )

    assert model.calls == 2
    assert result.rubric_awards[0].student_evidence == "I rearranged the equation."
    assert len(assessments.created) == 1


def test_grading_withholds_marks_when_corrected_evidence_is_still_not_verbatim() -> None:
    model = PersistentlyNonVerbatimEvidenceModel()
    assessments = CapturingAssessments()
    settings = get_settings()
    service = GradingService(
        cast(Any, SimpleNamespace()),
        cast(Any, assessments),
        settings,
        subject_context(settings),
        structured_model=model,
    )

    result = service.grade(
        GradeRequest(
            question_markdown="Solve x = 2.",
            mark_scheme_markdown="M1 rearrange. A1 answer 2.",
            answer_markdown="I rearranged the equation.",
            max_marks=2,
        )
    )

    assert model.calls == 2
    assert result.total_awarded == 0
    assert result.rubric_awards[0].awarded == 0
    assert result.rubric_awards[0].student_evidence is None
    assert result.manual_review_required is True
    assert any("暂缓授分" in warning for warning in result.warnings)
    assert len(assessments.created) == 1


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


def test_pending_reviews_include_paper_provenance_and_preserve_legacy_rows() -> None:
    common = {
        "subject_code": "9640",
        "question_ref": "Q2",
        "total_awarded": 3.0,
        "total_available": 5.0,
        "confidence": 0.8,
        "status": "pending_review",
        "result_json": '{"status": "pending_review"}',
        "created_at": "2026-08-17T00:00:00Z",
    }
    linked = SimpleNamespace(
        **common,
        id="assessment-linked",
        paper_job_id="job-1",
        question_position=2,
    )
    legacy = SimpleNamespace(
        **common,
        id="assessment-legacy",
        paper_job_id=None,
        question_position=None,
    )
    paper_job = SimpleNamespace(
        display_name="Economics June U1",
        filename="qp-june-u1.pdf",
        answer_mode="uploaded",
    )
    captured_statements: list[str] = []

    class FakeSession:
        def execute(self, statement: object) -> SimpleNamespace:
            captured_statements.append(str(statement))
            return SimpleNamespace(all=lambda: [(linked, paper_job), (legacy, None)])

    @contextmanager
    def sessions() -> Any:
        yield FakeSession()

    repository = AssessmentRepository(cast(Any, sessions))

    items = repository.pending(subject_code="9640")

    assert "LEFT OUTER JOIN paper_jobs" in captured_statements[0]
    assert items[0]["paper_job_id"] == "job-1"
    assert items[0]["paper_display_name"] == "Economics June U1"
    assert items[0]["paper_filename"] == "qp-june-u1.pdf"
    assert items[0]["question_position"] == 2
    assert items[0]["answer_mode"] == "uploaded"
    assert items[1]["paper_job_id"] is None
    assert items[1]["paper_display_name"] is None
    assert items[1]["paper_filename"] is None
    assert items[1]["question_position"] is None
    assert items[1]["answer_mode"] is None


def _review_repository(
    *,
    total_awarded: float = 1,
    total_available: float = 2,
) -> tuple[AssessmentRepository, SimpleNamespace, list[ReviewModel]]:
    assessment = SimpleNamespace(
        total_awarded=total_awarded,
        total_available=total_available,
        status="pending_review",
        updated_at=None,
    )
    reviews: list[ReviewModel] = []

    class FakeSession:
        def scalar(self, _statement: object) -> SimpleNamespace:
            return assessment

        def add(self, review: ReviewModel) -> None:
            reviews.append(review)

    @contextmanager
    def begin() -> Any:
        yield FakeSession()

    sessions = SimpleNamespace(begin=begin)
    return AssessmentRepository(cast(Any, sessions)), assessment, reviews


def test_repository_review_rejects_a_negative_override_mark() -> None:
    repository, assessment, reviews = _review_repository()

    with pytest.raises(ValueError, match="override_mark cannot be negative"):
        repository.review(
            "assessment-1",
            reviewer="pytest",
            decision="override",
            override_mark=-1,
            note=None,
            subject_code="9660",
        )

    assert assessment.total_awarded == 1
    assert reviews == []


@pytest.mark.parametrize("override_mark", [0.0, 2.0])
def test_repository_review_accepts_override_mark_boundaries(override_mark: float) -> None:
    repository, assessment, reviews = _review_repository()

    result = repository.review(
        "assessment-1",
        reviewer="pytest",
        decision="override",
        override_mark=override_mark,
        note=None,
        subject_code="9660",
    )

    assert result["final_mark"] == override_mark
    assert assessment.total_awarded == override_mark
    assert len(reviews) == 1
    assert reviews[0].override_mark == override_mark


@pytest.mark.integration
def test_grading_always_enters_review_queue() -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    # A fresh integration DB must not depend on a previous API test's startup.
    WorkspaceRepository(sessions).synchronize_installed_subjects(
        subject_package_registry(settings.subject_packages_dir).all()
    )
    service = GradingService(
        CorpusRepository(sessions),
        AssessmentRepository(sessions),
        settings,
        subject_context(settings),
        structured_model=FakeStructuredModel(),
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
