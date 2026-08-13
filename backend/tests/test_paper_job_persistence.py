from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from examtwin.assessment.agent_run_ledger import PaperAgentRunLedger
from examtwin.assessment.answering_agent.contracts import ToolReplayPayload
from examtwin.assessment.paper_answering import SPLIT_CONTRACT_VERSION
from examtwin.assessment.paper_job_repository import LostLeaseError, PaperJobRepository
from examtwin.assessment.paper_jobs import PaperJobService
from examtwin.assessment.paper_parsing import ParsedPaperChunk
from examtwin.assessment.paper_vision import (
    VISION_REVIEW_CONTRACT_VERSION,
    VisionPageClassification,
    VisionReviewResult,
    format_physical_page_markdown,
)
from examtwin.assessment.paper_worker import PaperWorker
from examtwin.contracts import (
    AnswerDiagram,
    DiagramElement,
    PaperDiagramSource,
    PaperQuestionAnswer,
)
from examtwin.platform.config import Settings
from examtwin.subjects.packages import subject_package_registry
from examtwin.subjects.public import subject_context
from examtwin.subjects.workspace_repository import WorkspaceRepository

from backend.tests.paper_job_support import (
    FakeAnswerService,
    _job_runtime,
    _job_service,
    _pdf_bytes,
    _test_database,
    accept_question_paper,
)


def _vision_page_classifications(
    page_start: int,
    page_end: int,
) -> tuple[VisionPageClassification, ...]:
    return tuple(
        VisionPageClassification(
            page_number=page_number,
            role="question" if page_number == page_start else "blank",
            contains_question=page_number == page_start,
            evidence=(
                "Visible question and mark allocation."
                if page_number == page_start
                else "No visible content."
            ),
            confidence=0.99,
        )
        for page_number in range(page_start, page_end + 1)
    )


@pytest.mark.integration
def test_agent_tool_ledger_replays_a_completed_safe_call_across_attempts(
    tmp_path: Path,
) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        subject_pack="oxfordaqa-mathematics-9660",
        database_url=database.database_url,
    )
    context = subject_context(settings).with_retrieval_snapshot(
        version_ids=("kb-v1", "kb-v2"),
        collections=("test-collection",),
        graph_version_id="graph-v3",
    )
    jobs = PaperJobService(
        settings,
        context,
        repository=PaperJobRepository(
            database.sessions,
            lease_seconds=settings.paper_lease_seconds,
        ),
    )
    runtime = _job_runtime(database, settings)
    created = jobs.create_job("paper.md", b"# Question 1\nCalculate 2+2.", unit_code="U1")
    claimed = runtime.claim_next()
    assert claimed is not None
    _, token = claimed
    runtime.store_questions(
        created.job_id,
        token,
        [
            {
                "number": "1",
                "question_markdown": "Calculate 2+2.",
                "requires_visual_context": False,
                "source_kind": "primary",
                "source_digest": "a" * 64,
            }
        ],
    )
    stored_source = database.fetch_one(
        """
        SELECT j.source_integrity_status, j.split_contract_version, j.split_source_digest,
               q.source_kind, q.source_digest, q.requires_visual_context
        FROM paper_jobs j
        JOIN paper_job_questions q ON q.job_id=j.id
        WHERE j.id=? AND q.position=0
        """,
        (created.job_id,),
    )
    assert stored_source == {
        "source_integrity_status": "verified",
        "split_contract_version": SPLIT_CONTRACT_VERSION,
        "split_source_digest": "a" * 64,
        "source_kind": "primary",
        "source_digest": "a" * 64,
        "requires_visual_context": False,
    }

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
        "knowledge_base_version_ids": ("kb-v1", "kb-v2"),
        "graph_version_id": "graph-v3",
    }
    first.start_run(**run_metadata)
    stored_run = database.fetch_one(
        """
        SELECT knowledge_base_version_ids_json, graph_version_id
        FROM paper_agent_runs
        WHERE job_id=? AND question_position=0 AND run_attempt=?
        """,
        (created.job_id, first_attempt),
    )
    assert stored_run is not None
    assert stored_run["knowledge_base_version_ids_json"] == '["kb-v1","kb-v2"]'
    assert stored_run["graph_version_id"] == "graph-v3"
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
def test_legacy_job_replacement_preserves_auditable_lineage(tmp_path: Path) -> None:
    database = _test_database()
    jobs = _job_service(database, Settings(object_store_local_root=tmp_path))
    created = jobs.create_job(
        "legacy-paper.md",
        b"# Question 1\nComplete source text.",
        unit_code="P1",
    )
    database.execute(
        """
        UPDATE paper_jobs
        SET status='completed', stage='completed', source_integrity_status='legacy_unverified'
        WHERE id=?
        """,
        (created.job_id,),
    )

    replacement = jobs.create_replacement(created.job_id)
    original_result = jobs.get_job(created.job_id)
    replacement_result = jobs.get_job(replacement.job_id)

    assert original_result.source_integrity_status == "replacement_queued"
    assert original_result.replaced_by_job_id == replacement.job_id
    assert replacement_result.source_integrity_status == "pending"
    assert replacement_result.replacement_for_job_id == created.job_id
    with pytest.raises(ValueError, match="已有替代任务"):
        jobs.create_replacement(created.job_id)

    database.execute(
        "UPDATE paper_jobs SET status='completed', stage='completed' WHERE id=?",
        (replacement.job_id,),
    )
    with pytest.raises(ValueError, match="替代审计关系"):
        jobs.delete_job(created.job_id)
    with pytest.raises(ValueError, match="替代审计关系"):
        jobs.delete_job(replacement.job_id)

    database.execute("DELETE FROM paper_jobs WHERE id=?", (replacement.job_id,))
    database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


@pytest.mark.integration
def test_uploaded_answer_enters_grading_discovery_only_after_terminal_state(
    tmp_path: Path,
) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path, database_url=database.database_url)
    WorkspaceRepository(database.sessions).synchronize_installed_subjects(
        subject_package_registry(settings.subject_packages_dir).all()
    )
    jobs = _job_service(database, settings)
    created = jobs.create_job_from_stream(
        "as-level-maths-unit-1-question-paper-Jan19.md",
        BytesIO(b"# Question 1\nCalculate 2+2."),
        unit_code="P1",
        answer_filename="student-answer.md",
        answer_stream=BytesIO(b"# Question 1\n4"),
    )
    try:
        assert created.job_id not in {
            str(row["id"]) for row in jobs.repository.recent_for_subject(jobs.subject.subject_code)
        }

        database.execute(
            "UPDATE paper_jobs SET status='completed', stage='completed' WHERE id=?",
            (created.job_id,),
        )

        discovered = jobs.repository.recent_for_subject(jobs.subject.subject_code)
        imported = next(row for row in discovered if row["id"] == created.job_id)
        assert imported["answer_mode"] == "uploaded"
        assert imported["status"] == "completed"
    finally:
        database.execute("DELETE FROM paper_jobs WHERE id=?", (created.job_id,))


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
def test_pdf_transport_disconnect_is_retried_before_job_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _test_database()
    settings = Settings(
        object_store_local_root=tmp_path,
        paper_mineru_max_attempts=3,
        paper_mineru_retry_delay_seconds=0,
        paper_vision_enabled=False,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    calls = 0

    def flaky_extract_paper_chunk(
        _settings: Settings,
        _source: Path,
        *,
        timeout: int | None = None,
    ) -> ParsedPaperChunk:
        del timeout
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return ParsedPaperChunk(
            markdown="# Question 1\nEvaluate the integral, showing all working."
        )

    monkeypatch.setattr(
        "examtwin.assessment.paper_worker.extract_paper_chunk",
        flaky_extract_paper_chunk,
    )
    created = jobs.create_job(
        "transport-retry.pdf",
        _pdf_bytes(1),
        unit_code="P2",
    )
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        document_classifier=accept_question_paper,
    )
    try:
        assert worker.run_once() is True
        completed = jobs.get_job(created.job_id)
        assert completed.status == "completed"
        assert completed.stage == "completed"
        assert calls == 2
        assert completed.chunks[0].attempts == 1
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
        document_classifier=accept_question_paper,
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
        assert completed.questions[0].requires_visual_context is False
        assert completed.questions[0].diagrams[0].title == "Axes"
        persisted = database.fetch_one(
            "SELECT knowledge_codes_json FROM paper_job_questions WHERE job_id=? AND position=0",
            (created.job_id,),
        )
        assert persisted is not None
        assert persisted["knowledge_codes_json"] == '["P2.7.O03"]'
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
def test_question_image_is_served_only_from_the_job_asset_namespace(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path)
    jobs = _job_service(database, settings)
    created = jobs.create_job("visual-paper.pdf", _pdf_bytes(1), unit_code="P2")
    asset_name = f"p0001-{'a' * 64}.png"
    try:
        jobs.files.write(
            f"{created.job_id}/question-images/{asset_name}",
            b"question-image",
        )

        assert jobs.question_image(created.job_id, asset_name).read_bytes() == b"question-image"
        with pytest.raises(ValueError, match="资源名无效"):
            jobs.question_image(created.job_id, "../source.pdf")
        with pytest.raises(LookupError, match="图片不存在"):
            jobs.question_image(created.job_id, f"p0001-{'b' * 64}.png")
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
            page_classifications=_vision_page_classifications(page_start, page_end),
        )

    created = jobs.create_job("paper.pdf", _pdf_bytes(7), unit_code="P2")
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        document_classifier=accept_question_paper,
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
def test_legacy_image_fallback_checkpoint_is_rereviewed_on_retry(tmp_path: Path) -> None:
    database = _test_database()
    settings = Settings(
        database_url=database.database_url,
        object_store_local_root=tmp_path,
        paper_chunk_pages=1,
        paper_lease_seconds=30,
        paper_vision_enabled=True,
    )
    jobs = _job_service(database, settings)
    runtime = _job_runtime(database, settings)
    review_calls = 0

    def review_chunk(
        _path: Path,
        _markdown: str,
        page_start: int,
        _page_end: int,
    ) -> VisionReviewResult:
        nonlocal review_calls
        review_calls += 1
        return VisionReviewResult(
            markdown=format_physical_page_markdown([(page_start, "1 Find x. [2 marks]")]),
            repairs=(
                ("视觉模型持续遗漏来源图片；已保留该物理页的 MinerU 原文。",)
                if review_calls == 1
                else ()
            ),
            confidence=0.96,
            model="vision-test",
            page_classifications=_vision_page_classifications(page_start, page_start),
        )

    class FailSplitOnce(FakeAnswerService):
        def __init__(self) -> None:
            self.split_calls = 0

        def split_questions(
            self,
            markdown: str,
            *,
            unit_code: str | None = None,
        ) -> list[dict[str, Any]]:
            self.split_calls += 1
            if self.split_calls == 1:
                raise ValueError("simulated split failure")
            return super().split_questions(markdown, unit_code=unit_code)

    created = jobs.create_job("paper.pdf", _pdf_bytes(1), unit_code="P2")
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=runtime,
        answer_service=FailSplitOnce(),  # type: ignore[arg-type]
        document_classifier=accept_question_paper,
        chunk_parser=lambda _path, _start, _end: "1 MinerU text. [2 marks]",
        vision_reviewer=review_chunk,
    )
    try:
        assert worker.run_once() is True
        assert jobs.get_job(created.job_id).stage == "splitting"
        metadata_path = tmp_path / "paper-jobs" / created.job_id / "chunks" / "0000-1-1.vision.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.pop("contract_version")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        jobs.retry(created.job_id)
        assert worker.run_once() is True

        assert jobs.get_job(created.job_id).status == "completed"
        assert review_calls == 2
        refreshed = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert refreshed["contract_version"] == VISION_REVIEW_CONTRACT_VERSION
        assert not any("MinerU 原文" in repair for repair in refreshed["repairs"])
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
                page_classifications=_vision_page_classifications(page_start, page_end),
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
        document_classifier=accept_question_paper,
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
            markdown: str,
            *,
            unit_code: str | None = None,
        ) -> list[dict[str, Any]]:
            return [
                {
                    "number": str(number),
                    "question_markdown": f"Question {number} has enough content.",
                    "knowledge_codes": [],
                    "requires_visual_context": False,
                    "source_kind": "primary",
                    "source_digest": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
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
        document_classifier=accept_question_paper,
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
        document_classifier=accept_question_paper,
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


@pytest.mark.integration
def test_paper_job_history_deletes_unclaimed_or_expired_jobs_but_rejects_live_leases(
    tmp_path: Path,
) -> None:
    database = _test_database()
    settings = Settings(object_store_local_root=tmp_path, database_url=database.database_url)
    jobs = _job_service(database, settings)
    completed = jobs.create_job(
        "history-completed-paper.md",
        b"# Question 1\nCalculate 2+2.",
        unit_code="P1",
    )
    unclaimed = jobs.create_job(
        "history-unclaimed-paper.md",
        b"# Question 1\nCalculate 3+3.",
        unit_code="P2",
    )
    leased = jobs.create_job(
        "history-leased-paper.md",
        b"# Question 1\nCalculate 5+5.",
        unit_code="P2",
    )
    completed_second = jobs.create_job(
        "history-completed-paper-2.md",
        b"# Question 1\nCalculate 4+4.",
        unit_code="P1",
    )
    uploaded = jobs.create_job_from_stream(
        "history-uploaded-paper.md",
        BytesIO(b"# Question 1\nCalculate 6+6."),
        unit_code="P1",
        answer_filename="student-answer.md",
        answer_stream=BytesIO(b"# Answer 1\n12"),
    )
    now = datetime.now(UTC)
    database.execute(
        "UPDATE paper_jobs SET status=?, stage=?, completed_at=?, updated_at=? WHERE id IN (?, ?)",
        (
            "completed",
            "completed",
            now,
            now,
            completed.job_id,
            completed_second.job_id,
        ),
    )
    database.execute(
        "UPDATE paper_jobs SET lease_token=?, lease_expires_at=? WHERE id=?",
        ("live-lease", now + timedelta(minutes=5), leased.job_id),
    )
    assessment_id = f"assessment-{unclaimed.job_id}"
    database.execute(
        """
        INSERT INTO assessments (
            id, subject_code, paper_job_id, question_position, rubric_set_id,
            knowledge_base_version_ids_json, graph_version_id, question_ref,
            answer_markdown, total_awarded, total_available, confidence, status,
            result_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assessment_id,
            "9660",
            unclaimed.job_id,
            0,
            None,
            "[]",
            None,
            "1",
            "4",
            1,
            1,
            1,
            "reviewed",
            "{}",
            now,
            now,
        ),
    )
    database.execute(
        """
        INSERT INTO reviews (
            assessment_id, reviewer, decision, override_mark, note, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (assessment_id, "teacher", "confirm", None, None, now),
    )
    database.execute(
        """
        INSERT INTO stored_objects (
            key, storage_backend, bucket, checksum_sha256, size_bytes,
            content_type, purpose, owner_type, owner_id, state, retain_until,
            created_at, updated_at, deleted_at, last_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"paper-jobs/{unclaimed.job_id}/source.md",
            "local",
            None,
            "0" * 64,
            4,
            "text/markdown",
            "paper_source",
            "paper_job",
            unclaimed.job_id,
            "active",
            now + timedelta(days=30),
            now,
            now,
            None,
            None,
        ),
    )
    try:
        listed = jobs.list_jobs(
            status="completed",
            unit_code="P1",
            query="completed-paper",
            created_after=now - timedelta(days=1),
            limit=10,
            offset=0,
        )
        assert listed.total == 2
        assert {item.job_id for item in listed.items} == {
            completed.job_id,
            completed_second.job_id,
        }

        active_jobs = jobs.list_jobs(status="active", limit=10, offset=0)
        assert {unclaimed.job_id, leased.job_id} <= {item.job_id for item in active_jobs.items}
        uploaded_jobs = jobs.list_jobs(answer_mode="uploaded", limit=10, offset=0)
        assert [item.job_id for item in uploaded_jobs.items] == [uploaded.job_id]
        assert uploaded_jobs.items[0].answer_mode == "uploaded"
        with pytest.raises(ValueError, match="仍由 Worker 处理"):
            jobs.delete_jobs((completed.job_id, leased.job_id))
        assert jobs.repository.get(completed.job_id) is not None
        assert jobs.repository.get(leased.job_id) is not None

        assert jobs.delete_job(unclaimed.job_id) is None
        assert jobs.repository.get(unclaimed.job_id) is None
        assert database.fetch_one("SELECT id FROM assessments WHERE id=?", (assessment_id,)) is None
        assert (
            database.fetch_one("SELECT id FROM reviews WHERE assessment_id=?", (assessment_id,))
            is None
        )
        retained = database.fetch_one(
            "SELECT state, retain_until FROM stored_objects WHERE owner_id=?",
            (unclaimed.job_id,),
        )
        assert retained is not None
        assert retained["state"] == "active"
        assert retained["retain_until"] <= datetime.now(UTC)

        database.execute(
            "UPDATE paper_jobs SET lease_expires_at=? WHERE id=?",
            (now - timedelta(seconds=1), leased.job_id),
        )
        assert jobs.delete_job(leased.job_id) is None
        assert jobs.repository.get(leased.job_id) is None

        assert jobs.delete_jobs((completed.job_id, completed_second.job_id)) == 2
        assert jobs.repository.get(completed.job_id) is None
        assert jobs.repository.get(completed_second.job_id) is None
        assert jobs.delete_job(uploaded.job_id) is None
        assert jobs.repository.get(uploaded.job_id) is None
    finally:
        database.execute("DELETE FROM stored_objects WHERE owner_id=?", (unclaimed.job_id,))
        database.execute("DELETE FROM reviews WHERE assessment_id=?", (assessment_id,))
        database.execute("DELETE FROM assessments WHERE id=?", (assessment_id,))
        database.execute(
            "DELETE FROM paper_jobs WHERE id IN (?, ?, ?, ?, ?)",
            (
                completed.job_id,
                completed_second.job_id,
                unclaimed.job_id,
                leased.job_id,
                uploaded.job_id,
            ),
        )
