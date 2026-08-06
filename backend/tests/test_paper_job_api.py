from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from examtwin.api.dependencies import get_paper_jobs, get_task_events
from examtwin.api.papers import (
    answer_paper,
    paper_job,
    retry_paper_job,
)
from examtwin.api.papers import router as paper_router
from examtwin.config import Settings
from examtwin.main import app
from examtwin.services.paper_jobs import (
    PaperJobService,
    _question_source_warnings,
)
from examtwin.services.subject_context import subject_context
from examtwin.services.task_events import PostgresTaskEvents

from backend.tests.paper_job_support import (
    CapturingCreateJobRepository,
    FakePaperJobs,
    FakeUpload,
    _job_service,
    _test_database,
)


@pytest.mark.parametrize(
    ("filename", "explicit_unit", "expected_unit"),
    [
        ("oxfordaqa-jun26-math-up1.pdf", None, "P1"),
        ("oxfordaqa-jun26-math-up1.pdf", "M2", "M2"),
    ],
)
def test_create_job_infers_unit_from_filename_unless_explicitly_set(
    tmp_path: Path,
    filename: str,
    explicit_unit: str | None,
    expected_unit: str,
) -> None:
    repository = CapturingCreateJobRepository()
    jobs = PaperJobService(  # type: ignore[arg-type]
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)).with_retrieval_snapshot(
            version_ids=("version-1",),
            collections=("collection-1",),
            graph_version_id=None,
        ),
        repository=repository,  # type: ignore[arg-type]
    )

    jobs.create_job(filename, b"%PDF-1.7", unit_code=explicit_unit)

    assert repository.values is not None
    assert repository.values["unit_code"] == expected_unit


def test_create_job_rejects_mark_scheme_before_persisting(tmp_path: Path) -> None:
    repository = CapturingCreateJobRepository()
    jobs = PaperJobService(  # type: ignore[arg-type]
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)).with_retrieval_snapshot(
            version_ids=("version-1",),
            collections=("collection-1",),
            graph_version_id=None,
        ),
        repository=repository,  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="Mark Scheme"):
        jobs.create_job(
            "A-Level-AQA经济学-国际卷MS-202505-Economics-U4-AQA.pdf",
            b"%PDF-1.7",
        )

    assert repository.values is None


async def test_paper_upload_api_returns_a_persistent_job_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from examtwin.api import papers as papers_api

    class SnapshotRepository:
        def __init__(self, _sessions: object) -> None:
            pass

        def active_retrieval_snapshot(
            self,
            subject_id: str,
            *,
            include_supplementary: bool,
        ) -> dict[str, object]:
            assert subject_id
            assert include_supplementary is False
            return {
                "version_ids": ["version-1"],
                "collections": ["collection-1"],
                "graph_version_id": None,
            }

    jobs = FakePaperJobs()
    monkeypatch.setattr(papers_api, "WorkspaceRepository", SnapshotRepository)
    monkeypatch.setattr(papers_api, "build_paper_job_service", lambda _settings, _subject: jobs)
    upload = FakeUpload()
    settings = Settings(object_store_local_root=tmp_path)
    created = await answer_paper(
        upload,  # type: ignore[arg-type]
        unit_code="P2",
        knowledge_base_version_ids=None,
        include_supplementary=False,
        settings=settings,
        subject=subject_context(settings),
    )
    assert created.model_dump() == {
        "job_id": "job-1",
        "status": "queued",
        "stage": "queued",
    }
    assert jobs.created == ("paper.md", b"# Question 1\nSolve it.", "P2")
    assert paper_job("job-1", jobs=jobs).filename == "paper.md"  # type: ignore[arg-type]
    assert retry_paper_job("job-1", jobs=jobs).status == "queued"  # type: ignore[arg-type]

    upload_route = next(route for route in paper_router.routes if route.path == "/papers/answer")
    retry_route = next(
        route for route in paper_router.routes if route.path.endswith("/{job_id}/retry")
    )
    assert upload_route.status_code == 202
    assert retry_route.status_code == 202


@pytest.mark.integration
async def test_postgres_task_events_receive_paper_job_changes(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path)
    jobs = _job_service(database, settings)
    created = jobs.create_job("events.md", b"# Question 1\nEnough content to parse.")
    events = PostgresTaskEvents(database.database_url)
    try:
        async with events.subscribe("paper_job", created.job_id) as updates:
            database.execute(
                "UPDATE paper_jobs SET updated_at=? WHERE id=?",
                ("2026-07-30T00:00:00+00:00", created.job_id),
            )
            event = await asyncio.wait_for(anext(updates), timeout=2)
        assert event.topic == "paper_job"
        assert event.resource_id == created.job_id
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_paper_job_websocket_receives_real_postgres_trigger(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path)
    jobs = _job_service(database, settings)
    created = jobs.create_job("live-events.md", b"# Question 1\nEnough content to parse.")
    events = PostgresTaskEvents(database.database_url)
    app.dependency_overrides[get_paper_jobs] = lambda: jobs
    app.dependency_overrides[get_task_events] = lambda: events
    try:
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/api/v1/papers/jobs/{created.job_id}/events"
            ) as websocket:
                initial = websocket.receive_json()
                database.execute(
                    """
                    UPDATE paper_jobs
                    SET status='failed', stage='queued', error='integration test', updated_at=?
                    WHERE id=?
                    """,
                    ("2026-07-30T00:00:01+00:00", created.job_id),
                )
                changed = websocket.receive_json()
        assert initial["data"]["status"] == "queued"
        assert changed["data"]["status"] == "failed"
        assert changed["data"]["error"] == "integration test"
    finally:
        app.dependency_overrides.pop(get_paper_jobs, None)
        app.dependency_overrides.pop(get_task_events, None)
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


def test_question_source_warnings_only_flag_non_structural_figure_hint() -> None:
    warnings = _question_source_warnings("Figure 2 shows a cuboid. 5 (b) Find its maximum volume.")

    assert len(warnings) == 1
    assert "依赖图形" in warnings[0]
