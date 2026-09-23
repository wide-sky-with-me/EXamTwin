from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from examtwin.app.api.dependencies import (
    get_difficulty_evidence_service,
    get_subject_context,
)
from examtwin.app.api.router import router
from examtwin.contracts.system import API_PREFIX
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeDifficultyService:
    def __init__(self) -> None:
        self.review: Any | None = None

    @staticmethod
    def _run() -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "id": "run-1",
            "subject_id": "subject-a",
            "subject_code": "SYNTH",
            "source_document_id": "report-1",
            "source_checksum": "report-checksum",
            "question_paper_document_id": "qp-1",
            "question_paper_checksum": "qp-checksum",
            "question_catalog_hash": "catalog-hash",
            "package_digest": "package-digest",
            "prompt_digest": "prompt-digest",
            "pair_key": "SYNTH:2026:JUN:U1",
            "input_hash": "input-hash",
            "extractor_version": "extractor-v1",
            "model_name": "model-a",
            "status": "review_ready",
            "candidate_count": 1,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
            "published_at": None,
            "run_fingerprint": "r" * 64,
            "candidates": [
                {
                    "id": "candidate-1",
                    "run_id": "run-1",
                    "candidate_fingerprint": "c" * 64,
                    "question_number": "1",
                    "page_number": 2,
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
                    "quote_hash": "quote-hash",
                    "block_hash": "block-hash",
                    "source_ref": "document:report-1:page:2",
                    "validation_status": "valid",
                    "validation_errors": [],
                    "review_decision": None,
                    "review_replacement": {},
                }
            ],
        }

    def create_from_source(self, **values: Any) -> dict[str, Any]:
        assert values["subject"].id == "subject-a"
        assert values["source_document_id"] == "report-1"
        return self._run()

    def list_runs(self, subject_id: str, *, limit: int) -> list[dict[str, Any]]:
        assert subject_id == "subject-a"
        assert limit == 20
        return [self._run()]

    def require_run(self, subject_id: str, run_id: str) -> dict[str, Any]:
        assert (subject_id, run_id) == ("subject-a", "run-1")
        return self._run()

    def review_candidate(self, **values: Any) -> dict[str, Any]:
        self.review = values["review"]
        return self._run()

    def publish_run(self, **values: Any) -> dict[str, Any]:
        return self._run()


def test_difficulty_routes_are_subject_scoped_and_keep_b_evidence_qualitative() -> None:
    # Exercise the real routes without the deployment lifespan (migrations/storage).
    app = FastAPI()
    app.include_router(router, prefix=API_PREFIX)
    service = FakeDifficultyService()
    subject = SimpleNamespace(id="subject-a")
    app.dependency_overrides[get_subject_context] = lambda: subject
    app.dependency_overrides[get_difficulty_evidence_service] = lambda: service
    try:
        with TestClient(app) as client:
            wrong = client.get("/api/v1/subject-workspaces/subject-b/difficulty-evidence/runs")
            assert wrong.status_code == 404

            created = client.post(
                "/api/v1/subject-workspaces/subject-a/difficulty-evidence/runs",
                json={"source_document_id": "report-1"},
            )
            assert created.status_code == 200
            assert created.json()["source_document_id"] == "report-1"

            detail = client.get(
                "/api/v1/subject-workspaces/subject-a/difficulty-evidence/runs/run-1"
            )
            assert detail.status_code == 200
            candidate = detail.json()["candidates"][0]
            assert candidate["evidence_level"] == "B"
            assert candidate["difficulty_score"] is None
            assert candidate["metric_value"] is None

            reviewed = client.post(
                "/api/v1/subject-workspaces/subject-a/difficulty-evidence/"
                "runs/run-1/candidates/candidate-1/reviews",
                json={
                    "decision": "accepted",
                    "expected_candidate_fingerprint": "c" * 64,
                },
            )
            assert reviewed.status_code == 200
            assert service.review is not None
            assert service.review.decision == "accepted"
    finally:
        app.dependency_overrides.pop(get_subject_context, None)
        app.dependency_overrides.pop(get_difficulty_evidence_service, None)
