from examtwin.app.api.dependencies import get_rubric_service
from examtwin.app.api.grading import router
from examtwin.assessment.rubric_repository import RubricConflictError
from examtwin.assessment.rubrics import AiReviewModelError
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FailingRubricService:
    def review_criteria_batch(self, rubric_id: str, request: object) -> None:
        raise LookupError(f"missing rubric: {rubric_id}")

    def ai_review_criteria(self, rubric_id: str, request: object) -> None:
        raise AiReviewModelError(f"model failed for: {rubric_id}")

    def grading_overview(self, paper_job_id: str, rubric_set_id: str) -> None:
        raise ValueError(f"{rubric_set_id} does not belong to {paper_job_id}")


class ConflictingRubricService:
    def review_criteria_batch(self, rubric_id: str, request: object) -> None:
        raise RubricConflictError(f"stale AI review for: {rubric_id}")

    def ai_review_criteria(self, rubric_id: str, request: object) -> None:
        raise RubricConflictError("评分规则来源 Mark Scheme 已发生变化，请重新创建评分规则")


def test_batch_ai_review_and_overview_endpoint_status_contracts() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_rubric_service] = FailingRubricService

    with TestClient(app) as client:
        invalid_batch = client.post(
            "/api/v1/grading/rubrics/rubric-1/batch-review",
            json={"reviewer": "Teacher", "decisions": []},
        )
        missing_batch = client.post(
            "/api/v1/grading/rubrics/rubric-1/batch-review",
            json={
                "reviewer": "Teacher",
                "decisions": [
                    {
                        "criterion_id": "criterion-1",
                        "review_status": "accepted",
                    }
                ],
            },
        )
        malformed_fingerprint = client.post(
            "/api/v1/grading/rubrics/rubric-1/batch-review",
            json={
                "reviewer": "Teacher",
                "decisions": [
                    {
                        "criterion_id": "criterion-1",
                        "expected_criterion_fingerprint": "z" * 64,
                        "review_status": "accepted",
                    }
                ],
            },
        )
        failed_ai = client.post(
            "/api/v1/grading/rubrics/rubric-1/ai-review",
            json={"criterion_ids": ["criterion-1"]},
        )
        wrong_overview = client.get(
            "/api/v1/grading/papers/paper-1/overview",
            params={"rubric_set_id": "rubric-other"},
        )

    assert invalid_batch.status_code == 422
    assert malformed_fingerprint.status_code == 422
    assert missing_batch.status_code == 404
    assert failed_ai.status_code == 502
    assert failed_ai.headers["X-Error-Code"] == "RUBRIC_AI_REVIEW_FAILED"
    assert wrong_overview.status_code == 422


def test_rubric_stale_application_and_source_changes_are_conflicts() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_rubric_service] = ConflictingRubricService
    fingerprint = "a" * 64

    with TestClient(app) as client:
        stale_application = client.post(
            "/api/v1/grading/rubrics/rubric-1/batch-review",
            json={
                "reviewer": "Teacher",
                "decisions": [
                    {
                        "criterion_id": "criterion-1",
                        "expected_criterion_fingerprint": fingerprint,
                        "review_status": "accepted",
                    }
                ],
            },
        )
        source_conflict = client.post(
            "/api/v1/grading/rubrics/rubric-1/ai-review",
            json={"criterion_ids": ["criterion-1"]},
        )

    assert stale_application.status_code == 409
    assert source_conflict.status_code == 409
    assert source_conflict.json()["detail"] == (
        "评分规则来源 Mark Scheme 已发生变化，请重新创建评分规则"
    )


def test_rubric_conflicts_are_declared_in_openapi_without_replacing_validation_errors() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    schema = app.openapi()

    for path in (
        "/api/v1/grading/rubrics/{rubric_id}/criteria/{criterion_id}/review",
        "/api/v1/grading/rubrics/{rubric_id}/batch-review",
        "/api/v1/grading/rubrics/{rubric_id}/ai-review",
        "/api/v1/grading/rubrics/{rubric_id}/confirm",
    ):
        responses = schema["paths"][path]["post"]["responses"]
        assert "409" in responses
        assert "422" in responses
