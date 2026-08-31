from examtwin.assessment.policies import (
    FOUNDATION_SCORE_PERCENTAGE,
    GRADING_REVIEW_CONFIDENCE_THRESHOLD,
    STABLE_SCORE_PERCENTAGE,
)
from examtwin.assessment.rubrics import _overall_suggestion


def _suggestion(percentage: float) -> str:
    return _overall_suggestion(
        completed_questions=1,
        total_questions=1,
        percentage=percentage,
        common_error_types=[],
        suggestions=[],
    )


def test_score_guidance_uses_the_shared_policy_boundaries() -> None:
    assert "系统巩固" in _suggestion(FOUNDATION_SCORE_PERCENTAGE - 0.01)
    assert "基础已建立" in _suggestion(FOUNDATION_SCORE_PERCENTAGE)
    assert "基础已建立" in _suggestion(STABLE_SCORE_PERCENTAGE - 0.01)
    assert "得分较稳定" in _suggestion(STABLE_SCORE_PERCENTAGE)


def test_grading_review_confidence_boundary_is_explicit() -> None:
    assert GRADING_REVIEW_CONFIDENCE_THRESHOLD == 0.75
