from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from examtwin.app.api.dependencies import get_paper_jobs, get_task_events
from examtwin.app.api.papers import (
    answer_paper,
    bulk_delete_paper_jobs,
    delete_paper_job,
    paper_job,
    paper_jobs,
    replace_paper_job,
    retry_paper_job,
)
from examtwin.app.api.papers import router as paper_router
from examtwin.app.main import app
from examtwin.assessment.paper_jobs import (
    PaperJobService,
    _question_source_warnings,
)
from examtwin.assessment.task_events import PostgresTaskEvents
from examtwin.contracts import PaperJobBulkDeleteRequest, PaperJobCreated
from examtwin.platform.config import Settings
from examtwin.subjects.public import subject_context

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


def test_economics_job_requires_and_freezes_exact_pair_source_booklet(tmp_path: Path) -> None:
    repository = CapturingCreateJobRepository()
    settings = Settings(object_store_local_root=tmp_path)
    subject = subject_context(settings, "oxfordaqa-economics-9640").with_retrieval_snapshot(
        version_ids=("version-1",),
        collections=("collection-1",),
        graph_version_id=None,
    )
    jobs = PaperJobService(settings, subject, repository=repository)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Source Booklet"):
        jobs.create_job("qp-202401-economics-u1.pdf", b"%PDF-1.7")

    booklet = {
        "id": "insert-1",
        "subject_code": "9640",
        "source_type": "insert",
        "identity_status": "complete",
        "pair_key": "9640:2024:JAN:U1",
        "checksum": "abc123",
        "converted_source_checksum": "abc123",
        "status": "converted",
        "filename": "IN-202401-Economics-U1.pdf",
    }
    jobs.create_job_from_stream(
        "qp-202401-economics-u1.pdf",
        BytesIO(b"%PDF-1.7"),
        source_booklet=booklet,
    )

    assert repository.values is not None
    assert repository.values["pair_key"] == "9640:2024:JAN:U1"
    assert repository.values["source_booklet_document_id"] == "insert-1"
    assert repository.values["source_booklet_checksum"] == "abc123"


def test_economics_job_rejects_nearby_source_booklet_pair(tmp_path: Path) -> None:
    repository = CapturingCreateJobRepository()
    settings = Settings(object_store_local_root=tmp_path)
    subject = subject_context(settings, "oxfordaqa-economics-9640").with_retrieval_snapshot(
        version_ids=("version-1",),
        collections=("collection-1",),
        graph_version_id=None,
    )
    jobs = PaperJobService(settings, subject, repository=repository)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="年份、考季或 Unit 不匹配"):
        jobs.create_job_from_stream(
            "qp-202401-economics-u1.pdf",
            BytesIO(b"%PDF-1.7"),
            source_booklet={
                "id": "insert-2",
                "subject_code": "9640",
                "source_type": "insert",
                "identity_status": "complete",
                "pair_key": "9640:2024:JUN:U1",
                "checksum": "def456",
                "converted_source_checksum": "def456",
                "status": "converted",
                "filename": "IN-202406-Economics-U1.pdf",
            },
        )

    assert repository.values is None


def test_managed_economics_replacement_forwards_exact_paper_bindings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(b"%PDF-1.7")
    job = {
        "id": "legacy-job",
        "subject_code": "9640",
        "status": "completed",
        "source_integrity_status": "verified",
        "split_contract_version": "paper-question-split-v1",
        "unit_code": "U1",
        "paper_unit_id": "paper-unit-1",
        "question_paper_document_id": "question-paper-1",
        "source_booklet_document_id": "insert-1",
    }

    class Repository:
        linked: tuple[str, str] | None = None

        def get(self, job_id: str) -> dict[str, object]:
            assert job_id == "legacy-job"
            return job

        def replacement_id(self, job_id: str) -> None:
            assert job_id == "legacy-job"
            return None

        def source_record(self, job_id: str) -> dict[str, object]:
            assert job_id == "legacy-job"
            return job

        def link_replacement(self, job_id: str, replacement_id: str) -> None:
            self.linked = (job_id, replacement_id)

    class Files:
        def source_file(self, _job: dict[str, object]) -> tuple[Path, str, str]:
            return source_path, "qp-202401-economics-u1.pdf", ".pdf"

    booklet = {
        "id": "insert-1",
        "subject_code": "9640",
        "source_type": "insert",
        "identity_status": "complete",
        "pair_key": "9640:2024:JAN:U1",
        "checksum": "abc123",
        "converted_source_checksum": "abc123",
        "status": "converted",
    }

    class Documents:
        def get_active(self, document_id: str) -> dict[str, object]:
            assert document_id == "insert-1"
            return booklet

    settings = Settings(object_store_local_root=tmp_path)
    subject = subject_context(settings, "oxfordaqa-economics-9640").with_retrieval_snapshot(
        version_ids=("version-1",),
        collections=("collection-1",),
        graph_version_id=None,
    )
    repository = Repository()
    jobs = PaperJobService(
        settings,
        subject,
        repository=repository,  # type: ignore[arg-type]
        files=Files(),  # type: ignore[arg-type]
        documents=Documents(),  # type: ignore[arg-type]
    )
    captured: dict[str, object] = {}

    def create_job(_filename: str, _stream: object, **kwargs: object) -> PaperJobCreated:
        captured.update(kwargs)
        return PaperJobCreated(job_id="replacement-job", status="queued", stage="queued")

    monkeypatch.setattr(jobs, "create_job_from_stream", create_job)

    replacement = jobs.create_replacement("legacy-job")

    assert replacement.job_id == "replacement-job"
    assert captured["source_booklet"] == booklet
    assert captured["paper_unit_id"] == "paper-unit-1"
    assert captured["question_paper_document_id"] == "question-paper-1"
    assert repository.linked == ("legacy-job", "replacement-job")


async def test_paper_upload_api_returns_a_persistent_job_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from examtwin.app.api import papers as papers_api

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
    assert replace_paper_job("job-1", jobs=jobs).job_id == "replacement-job"  # type: ignore[arg-type]

    upload_route = next(route for route in paper_router.routes if route.path == "/papers/answer")
    retry_route = next(
        route for route in paper_router.routes if route.path.endswith("/{job_id}/retry")
    )
    replacement_route = next(
        route for route in paper_router.routes if route.path.endswith("/{job_id}/replace")
    )
    assert upload_route.status_code == 202
    assert retry_route.status_code == 202
    assert replacement_route.status_code == 202


def test_paper_history_api_lists_filters_and_deletes_terminal_jobs() -> None:
    jobs = FakePaperJobs()

    listed = paper_jobs(
        status_filter="completed",
        answer_mode="uploaded",
        unit_code="P2",
        query="paper",
        created_after=None,
        limit=20,
        paper_unit_id=None,
        offset=0,
        jobs=jobs,  # type: ignore[arg-type]
    )

    assert listed.total == 1
    assert listed.items[0].filename == "paper.md"
    assert jobs.list_filters == {
        "status": "completed",
        "answer_mode": "uploaded",
        "unit_code": "P2",
        "query": "paper",
        "created_after": None,
        "paper_unit_id": None,
        "limit": 20,
        "offset": 0,
    }
    response = delete_paper_job("job-1", jobs=jobs)  # type: ignore[arg-type]
    assert response.status_code == 204
    assert jobs.deleted == ["job-1"]
    bulk = bulk_delete_paper_jobs(
        PaperJobBulkDeleteRequest(job_ids=["job-1"]),
        jobs=jobs,  # type: ignore[arg-type]
    )
    assert bulk.deleted_count == 1
    assert jobs.deleted == ["job-1", "job-1"]

    list_route = next(route for route in paper_router.routes if route.path == "/papers/jobs")
    delete_route = next(
        route
        for route in paper_router.routes
        if route.path == "/papers/jobs/{job_id}" and "DELETE" in route.methods
    )
    bulk_delete_route = next(
        route
        for route in paper_router.routes
        if route.path == "/papers/jobs/bulk-delete" and "POST" in route.methods
    )
    assert "GET" in list_route.methods
    assert delete_route.status_code == 204
    assert "POST" in bulk_delete_route.methods


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
    warnings = _question_source_warnings(
        "Figure 2 shows a cuboid. 5 (b) Find its maximum volume.",
        True,
        "verified",
    )

    assert len(warnings) == 1
    assert "依赖图形" in warnings[0]


def test_question_source_warnings_identify_unresolved_printed_content() -> None:
    warnings = _question_source_warnings(
        "$F(x)=\\text{[piecewise definition as printed]}$. Find $h$.",
        True,
        "verified",
    )

    assert warnings == ["题干提取不完整；该任务不满足来源完整性契约。"]


def test_question_source_warnings_fail_closed_for_legacy_unverified_jobs() -> None:
    assert _question_source_warnings("Complete question.", False, "legacy_unverified") == [
        "该题来自旧版未验证分题契约；请创建替代任务后再使用。"
    ]
