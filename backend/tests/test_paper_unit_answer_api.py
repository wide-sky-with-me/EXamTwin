from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from examtwin.app.api import paper_units
from examtwin.app.api.dependencies import get_paper_units, get_subject_context
from examtwin.assessment.paper_jobs import PaperJobService
from examtwin.contracts.papers import PaperJobCreated
from examtwin.contracts.strategy import StrategyRequest
from examtwin.platform.config import Settings, get_settings
from examtwin.subjects.public import subject_context
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.tests.paper_job_support import CapturingCreateJobRepository


@pytest.mark.parametrize("with_strategy", [False, True])
def test_managed_answer_route_preserves_strategy_and_source_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, with_strategy: bool
) -> None:
    settings = Settings()
    subject = subject_context(settings)
    paper = tmp_path / "question.pdf"
    paper.write_bytes(b"managed question paper")
    booklet = {"id": "exact-insert", "checksum": "insert-checksum"}
    units = Mock()
    units.answer_sources.return_value = (
        {"id": "exact-paper", "filename": paper.name, "unit_code": "P1"},
        booklet,
    )
    workspaces = Mock()
    workspaces.active_retrieval_snapshot.return_value = {
        "collections": ["published-core"],
        "version_ids": ["version-1"],
    }
    captured = {}

    def create_job(filename: str, stream: BytesIO, **kwargs: object) -> PaperJobCreated:
        captured.update(kwargs, filename=filename, content=stream.read())
        return PaperJobCreated(job_id="job-1", status="queued", stage="queued")

    monkeypatch.setattr(paper_units, "WorkspaceRepository", lambda _: workspaces)
    monkeypatch.setattr(paper_units, "create_session_factory", lambda _: None)
    monkeypatch.setattr(paper_units, "_document_path", lambda *_: paper)
    monkeypatch.setattr(
        paper_units,
        "build_paper_job_service",
        lambda *_: SimpleNamespace(create_job_from_stream=create_job),
    )
    app = FastAPI()
    app.include_router(paper_units.router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_subject_context] = lambda: subject
    app.dependency_overrides[get_paper_units] = lambda: units
    payload = {"question_paper_document_id": "exact-paper"}
    strategy = StrategyRequest(
        target_score=48,
        study_budget_minutes=720,
        exam_budget_minutes=90,
    )
    if with_strategy:
        payload["strategy"] = strategy.model_dump()
    with TestClient(app) as client:
        response = client.post(
            f"/subject-workspaces/{subject.id}/paper-units/unit-1/answer",
            json=payload,
        )
    assert response.status_code == 202, response.text
    assert captured["strategy"] == (strategy if with_strategy else None)
    assert captured["paper_unit_id"] == "unit-1"
    assert captured["question_paper_document_id"] == "exact-paper"
    assert captured["source_booklet"] == booklet
    assert captured["content"] == paper.read_bytes()


@pytest.mark.parametrize("invalid", [{"target_score": 0}, {"reserve_minutes": 90}])
def test_managed_answer_rejects_invalid_strategy_before_creating_job(invalid: dict) -> None:
    app = FastAPI()
    app.include_router(paper_units.router)
    units = Mock()
    app.dependency_overrides[get_subject_context] = lambda: SimpleNamespace(id="subject")
    app.dependency_overrides[get_paper_units] = lambda: units
    app.dependency_overrides[get_settings] = lambda: Settings()
    with TestClient(app) as client:
        response = client.post(
            "/subject-workspaces/subject/paper-units/unit-1/answer",
            json={
                "question_paper_document_id": "exact-paper",
                "strategy": {
                    "target_score": 48,
                    "study_budget_minutes": 720,
                    "exam_budget_minutes": 90,
                    **invalid,
                },
            },
        )
    assert response.status_code == 422
    units.answer_sources.assert_not_called()


def test_managed_strategy_is_persisted_with_paper_identity(tmp_path: Path) -> None:
    settings = Settings(object_store_local_root=tmp_path)
    subject = subject_context(settings).with_retrieval_snapshot(
        version_ids=("version-1",),
        collections=("published-core",),
        graph_version_id=None,
    )
    repository = CapturingCreateJobRepository()
    jobs = PaperJobService(settings, subject, repository=repository)  # type: ignore[arg-type]
    strategy = StrategyRequest(
        target_score=48,
        study_budget_minutes=720,
        exam_budget_minutes=90,
    )
    jobs.create_job_from_stream(
        "oxfordaqa-jun26-math-up1.pdf",
        BytesIO(b"%PDF-1.7"),
        paper_unit_id="unit-1",
        question_paper_document_id="exact-paper",
        strategy=strategy,
    )
    assert repository.values is not None
    assert (
        StrategyRequest.model_validate_json(repository.values["strategy_request_json"]) == strategy
    )
    assert repository.values["paper_unit_id"] == "unit-1"
    assert repository.values["question_paper_document_id"] == "exact-paper"
    assert repository.values["answer_mode"] == "generated"
