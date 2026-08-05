from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from examtwin.answering_agent.contracts import ToolReplayPayload
from examtwin.config import Settings
from examtwin.persistence.paper_job_repository import LostLeaseError
from examtwin.schemas import (
    AnswerDiagram,
    DiagramElement,
    PaperDiagramSource,
    PaperQuestionAnswer,
)
from examtwin.services.agent_run_ledger import PaperAgentRunLedger
from examtwin.services.paper_vision import (
    VisionReviewResult,
    format_physical_page_markdown,
)
from examtwin.services.paper_worker import PaperWorker
from examtwin.services.subject_context import subject_context

from backend.tests.paper_job_support import (
    FakeAnswerService,
    _job_runtime,
    _job_service,
    _pdf_bytes,
    _test_database,
)


@pytest.mark.integration
def test_agent_tool_ledger_replays_a_completed_safe_call_across_attempts(
    tmp_path: Path,
) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path)
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    created = jobs.create_job("paper.md", b"# Question 1\nCalculate 2+2.", unit_code="P1")
    claimed = runtime.claim_next()
    assert claimed is not None
    _, token = claimed
    runtime.store_questions(
        created.job_id,
        token,
        [{"number": "1", "question_markdown": "Calculate 2+2."}],
    )

    first_attempt = runtime.start_question(created.job_id, token, 0)
    first = PaperAgentRunLedger(
        runtime.repository,
        job_id=created.job_id,
        lease_token=token,
        question_position=0,
        run_attempt=first_attempt,
    )
    run_metadata = {
        "package_id": "oxfordaqa-mathematics-9660",
        "package_version": "test-v1",
        "package_digest": "package-digest",
        "skill_digest": "skill-digest",
        "prompt_digest": "prompt-digest",
        "model_name": "test-model",
        "max_iterations": 4,
        "max_tool_calls": 2,
    }
    first.start_run(**run_metadata)
    first.tool_started(
        call_key="call-key",
        tool_name="math_calculate",
        input_digest="input-digest",
        execution_fingerprint="execution-fingerprint",
        replay_safe=True,
    )
    first.tool_finished(
        call_key="call-key",
        status="completed",
        result_digest="result-digest",
        replay=ToolReplayPayload(observation="evaluate(2+2) = 4"),
        error_type=None,
    )
    first.finish_run("failed")
    runtime.requeue_question(created.job_id, token, 0, RuntimeError("retry"))

    second_attempt = runtime.start_question(created.job_id, token, 0)
    second = PaperAgentRunLedger(
        runtime.repository,
        job_id=created.job_id,
        lease_token=token,
        question_position=0,
        run_attempt=second_attempt,
    )

    replay = second.find_replay(
        call_key="call-key",
        execution_fingerprint="execution-fingerprint",
    )
    assert replay is not None
    assert replay.observation == "evaluate(2+2) = 4"


@pytest.mark.integration
def test_single_question_retry_repairs_only_a_missing_required_diagram(
    tmp_path: Path,
) -> None:
    database = _test_database()
    jobs = _job_service(database, Settings(object_store_local_root=tmp_path))
    created = jobs.create_job("paper.md", b"# Question 3\nSketch the graph.", unit_code="P1")
    question = "### (c)\nSketch the graph of $y=x^2$ on the axes."
    missing_diagram = PaperQuestionAnswer(
        number="3",
        question_markdown=question,
        answer_markdown="The graph should be sketched.",
        confidence=0.5,
        grounded=False,
    )
    matching_diagram = missing_diagram.model_copy(
        update={
            "diagrams": [
                AnswerDiagram(
                    title="Quadratic graph",
                    tool_name="math_plot",
                    source=PaperDiagramSource(
                        page_number=1,
                        width=100,
                        height=100,
                        calibration="blank_axes",
                    ),
                    view_box=(0, 0, 100, 100),
                    elements=[
                        DiagramElement(
                            kind="line",
                            x1=0,
                            y1=0,
                            x2=1,
                            y2=1,
                        )
                    ],
                )
            ]
        }
    )
    try:
        database.execute(
            """
            INSERT INTO paper_job_questions (
                job_id, position, number, question_markdown, status,
                answer_json, attempts, completed_at
            ) VALUES (?, 2, '3', ?, 'completed', ?, 1, ?)
            """,
            (created.job_id, question, missing_diagram.model_dump_json(), "now"),
        )
        database.execute(
            """
            UPDATE paper_jobs
            SET status='completed', stage='completed', total_questions=1,
                completed_questions=1, completed_at='now'
            WHERE id=?
            """,
            (created.job_id,),
        )

        jobs.retry_question(created.job_id, 2)

        queued = jobs.get_job(created.job_id)
        assert (queued.status, queued.completed_questions, queued.failed_questions) == (
            "queued",
            0,
            0,
        )
        assert queued.questions[0].status == "pending"
        assert queued.questions[0].attempts == 1
        assert queued.questions[0].answer_markdown == ""
        assert queued.questions[0].diagrams == []

        database.execute(
            """
            UPDATE paper_job_questions
            SET status='completed', answer_json=?, completed_at='now'
            WHERE job_id=? AND position=2
            """,
            (matching_diagram.model_dump_json(), created.job_id),
        )
        database.execute(
            """
            UPDATE paper_jobs
            SET status='completed', stage='completed', completed_questions=1,
                completed_at='now'
            WHERE id=?
            """,
            (created.job_id,),
        )
        with pytest.raises(ValueError, match="产物完整"):
            jobs.retry_question(created.job_id, 2)

        database.execute(
            """
            UPDATE paper_job_questions SET answer_json=? WHERE job_id=? AND position=2
            """,
            (missing_diagram.model_dump_json(), created.job_id),
        )
        database.execute(
            "UPDATE paper_jobs SET lease_token='active-worker' WHERE id=?",
            (created.job_id,),
        )
        with pytest.raises(ValueError, match="Worker 持有"):
            jobs.retry_question(created.job_id, 2)
        unchanged = database.fetch_one(
            "SELECT status FROM paper_job_questions WHERE job_id=? AND position=2",
            (created.job_id,),
        )
        assert unchanged is not None and unchanged["status"] == "completed"
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_expired_lease_can_be_reclaimed_and_rejects_old_heartbeat(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path, paper_lease_seconds=30)
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    created = jobs.create_job("lease.md", b"# Question 1\nEnough content to parse.")
    try:
        first = runtime.claim_next()
        assert first is not None
        first_job, first_token = first
        assert first_job["id"] == created.job_id
        assert runtime.claim_next() is None

        database.execute(
            "UPDATE paper_jobs SET lease_expires_at=? WHERE id=?",
            ("2000-01-01T00:00:00+00:00", created.job_id),
        )
        second = runtime.claim_next()
        assert second is not None
        second_job, second_token = second
        assert second_job["id"] == created.job_id
        assert second_token != first_token
        assert runtime.heartbeat(created.job_id, first_token) is False
        runtime.ensure_chunks(created.job_id, second_token, 1, 1)
        with pytest.raises(LostLeaseError):
            runtime.complete_chunk(
                created.job_id,
                first_token,
                0,
                f"{created.job_id}/stale.md",
            )
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_two_workers_cannot_claim_the_same_paper_job(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path, paper_lease_seconds=30)
    jobs = _job_service(database, settings)
    runtimes = [_job_runtime(database, settings), _job_runtime(database, settings)]
    created = jobs.create_job("race.md", b"# Question 1\nEnough content to parse.")
    barrier = threading.Barrier(2)

    def claim(runtime: Any) -> tuple[dict[str, Any], str] | None:
        barrier.wait(timeout=2)
        return runtime.claim_next()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, runtimes))
        claimed = [result for result in results if result is not None]
        assert len(claimed) == 1
        assert claimed[0][0]["id"] == created.job_id
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_pdf_retry_reuses_completed_chunks(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_chunk_pages=5,
        paper_lease_seconds=30,
        paper_vision_enabled=False,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    calls: list[tuple[int, int]] = []
    failed_once = False

    def parse_chunk(_path: Path, page_start: int, page_end: int) -> str:
        nonlocal failed_once
        calls.append((page_start, page_end))
        if page_start == 6 and not failed_once:
            failed_once = True
            raise TimeoutError("simulated MinerU timeout")
        return f"# Parsed pages {page_start}-{page_end}\nEnough Markdown content."

    created = jobs.create_job(
        "paper.pdf",
        _pdf_bytes(7),
        unit_code="P2",
    )
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        chunk_parser=parse_chunk,
    )
    try:
        assert worker.run_once() is True
        failed = jobs.get_job(created.job_id)
        assert failed.status == "failed"
        assert failed.stage == "parsing"
        assert failed.parsed_pages == 5
        assert [(chunk.page_start, chunk.page_end, chunk.status) for chunk in failed.chunks] == [
            (1, 5, "completed"),
            (6, 7, "failed"),
        ]
        assert failed.chunks[1].attempts == 1
        assert "simulated MinerU timeout" in (failed.chunks[1].error or "")
        assert calls == [(1, 5), (6, 7)]

        retried = jobs.retry(created.job_id)
        queued = jobs.get_job(retried.job_id)
        assert queued.status == "queued"
        assert queued.stage == "queued"
        assert [chunk.status for chunk in queued.chunks] == ["completed", "pending"]
        assert worker.run_once() is True
        completed = jobs.get_job(created.job_id)
        assert completed.status == "completed"
        assert completed.parsed_pages == 7
        assert completed.completed_questions == 1
        assert completed.questions[0].citations[0].page == 22
        assert completed.questions[0].source_pages == [1]
        assert completed.questions[0].diagrams[0].title == "Axes"
        assert [
            (step.sequence, step.phase, step.status) for step in completed.questions[0].agent_steps
        ] == [
            (1, "preparing", "completed"),
            (2, "finalizing", "completed"),
        ]
        assert calls == [(1, 5), (6, 7), (6, 7)]
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_pdf_source_page_is_rendered_and_cached(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path)
    jobs = _job_service(database, settings)
    created = jobs.create_job("visual-paper.pdf", _pdf_bytes(2), unit_code="P2")
    try:
        first = jobs.source_page(created.job_id, 2)
        second = jobs.source_page(created.job_id, 2)

        assert first == second
        assert first.suffix == ".jpg"
        assert first.read_bytes().startswith(b"\xff\xd8")
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_pdf_vision_review_is_checkpointed_across_split_retry(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_chunk_pages=5,
        paper_lease_seconds=30,
        paper_vision_enabled=True,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    calls: list[tuple[int, int]] = []
    failed_once = False

    def parse_chunk(_path: Path, page_start: int, page_end: int) -> str:
        return f"# MinerU pages {page_start}-{page_end}\nIncomplete question text."

    def review_chunk(
        _path: Path,
        _markdown: str,
        page_start: int,
        page_end: int,
    ) -> VisionReviewResult:
        nonlocal failed_once
        calls.append((page_start, page_end))
        if page_start == 6 and not failed_once:
            failed_once = True
            raise TimeoutError("simulated vision timeout")
        return VisionReviewResult(
            markdown=format_physical_page_markdown(
                [
                    (
                        page_number,
                        (
                            "6 (a) Find the missing equation. [5 marks]\n"
                            "6 (b) Find the area. [4 marks]"
                            if page_number == page_start
                            else ""
                        ),
                    )
                    for page_number in range(page_start, page_end + 1)
                ]
            ),
            repairs=("restored question 6(a)",),
            confidence=0.96,
            model="vision-test",
        )

    created = jobs.create_job("paper.pdf", _pdf_bytes(7), unit_code="P2")
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        chunk_parser=parse_chunk,
        vision_reviewer=review_chunk,
    )
    try:
        assert worker.run_once() is True
        failed = jobs.get_job(created.job_id)
        assert failed.status == "failed"
        assert failed.stage == "vision_review"
        assert calls == [(1, 5), (6, 7)]
        checkpoint_root = tmp_path / "paper-jobs" / created.job_id / "chunks"
        assert len(list(checkpoint_root.glob("*.vision.md"))) == 1

        jobs.retry(created.job_id)
        assert worker.run_once() is True
        completed = jobs.get_job(created.job_id)
        assert completed.status == "completed"
        assert calls == [(1, 5), (6, 7), (6, 7)]
        assert len(list(checkpoint_root.glob("*.vision.md"))) == 2
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_pdf_vision_chunks_use_bounded_concurrency(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_chunk_pages=1,
        paper_vision_enabled=True,
        paper_vision_concurrency=2,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    active = 0
    max_active = 0
    guard = threading.Lock()

    def review_chunk(
        _path: Path,
        _markdown: str,
        page_start: int,
        page_end: int,
    ) -> VisionReviewResult:
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.04)
            return VisionReviewResult(
                markdown=format_physical_page_markdown(
                    [(page_start, f"{page_start} Find x. [2 marks]")]
                ),
                repairs=(),
                confidence=0.99,
                model="vision-test",
            )
        finally:
            with guard:
                active -= 1

    created = jobs.create_job("paper.pdf", _pdf_bytes(4), unit_code="P2")
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        chunk_parser=lambda _path, start, end: f"Pages {start}-{end} content",
        vision_reviewer=review_chunk,
    )
    try:
        assert worker.run_once() is True
        completed = jobs.get_job(created.job_id)
        assert completed.status == "completed"
        assert max_active == 2
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_only_active_question_workers_are_marked_answering(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_lease_seconds=30,
        paper_question_concurrency=4,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    release = threading.Event()
    four_started = threading.Event()
    started_lock = threading.Lock()
    started_count = 0

    class BlockingAnswerService(FakeAnswerService):
        def split_questions(
            self,
            _markdown: str,
            *,
            unit_code: str | None = None,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "number": str(number),
                    "question_markdown": f"Question {number} has enough content.",
                    "knowledge_codes": [],
                }
                for number in range(1, 5)
            ]

        def answer_question(
            self,
            item: dict[str, Any],
            *,
            unit_code: str | None = None,
            event_sink: Any | None = None,
        ) -> PaperQuestionAnswer:
            nonlocal started_count
            with started_lock:
                started_count += 1
                if started_count == 4:
                    four_started.set()
            release.wait(timeout=2)
            return super().answer_question(
                item,
                unit_code="P2",
                event_sink=event_sink,
            )

    created = jobs.create_job(
        "concurrency.md",
        b"# Questions\nEnough Markdown content for four questions.",
        unit_code="P2",
    )
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=BlockingAnswerService(),  # type: ignore[arg-type]
    )
    thread = threading.Thread(target=worker.run_once)
    thread.start()
    try:
        assert four_started.wait(timeout=2)
        deadline = time.monotonic() + 2
        statuses: list[str] = []
        while time.monotonic() < deadline:
            statuses = [row["status"] for row in runtime.list_questions(created.job_id)]
            if statuses.count("answering") == 4:
                break
            time.sleep(0.02)
        assert statuses.count("answering") == 4
        assert statuses.count("pending") == 0
        release.set()
        thread.join(timeout=3)
        assert not thread.is_alive()
        assert jobs.get_job(created.job_id).status == "completed"
    finally:
        release.set()
        thread.join(timeout=3)
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_failed_question_is_automatically_retried(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_lease_seconds=30,
        paper_question_max_attempts=3,
        paper_question_retry_delay_seconds=0,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)

    class FlakyAnswerService(FakeAnswerService):
        calls = 0

        def answer_question(
            self,
            item: dict[str, Any],
            *,
            unit_code: str | None = None,
            event_sink: Any | None = None,
        ) -> PaperQuestionAnswer:
            self.calls += 1
            if self.calls < 3:
                raise TypeError("'NoneType' object is not subscriptable")
            return super().answer_question(
                item,
                unit_code=unit_code,
                event_sink=event_sink,
            )

    answer_service = FlakyAnswerService()
    created = jobs.create_job(
        "auto-retry.md",
        b"# Question 1\nEvaluate the integral, showing all working.",
        unit_code="P2",
    )
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=answer_service,  # type: ignore[arg-type]
    )
    try:
        assert worker.run_once() is True
        completed = jobs.get_job(created.job_id)
        assert completed.status == "completed"
        assert completed.failed_questions == 0
        assert completed.questions[0].status == "completed"
        assert completed.questions[0].attempts == 3
        assert answer_service.calls == 3
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))
