from __future__ import annotations

import os
from io import BytesIO
from typing import Any

import pytest
from examtwin.assessment.answering_agent.contracts import AgentStep
from examtwin.assessment.paper_classification import PaperDocumentClassification
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_job_runtime import PaperJobRuntime
from examtwin.assessment.paper_jobs import PaperJobService
from examtwin.assessment.paper_sources import PaperSourceStore
from examtwin.contracts import (
    AnswerDiagram,
    Citation,
    DiagramElement,
    PaperJobCreated,
    PaperJobResponse,
    PaperQuestionAnswer,
)
from examtwin.platform.config import Settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import subject_context
from pypdf import PdfWriter
from sqlalchemy import text


def accept_question_paper(_markdown: str) -> PaperDocumentClassification:
    return PaperDocumentClassification(
        document_type="question_paper",
        confidence=0.99,
        evidence=["candidate-facing questions"],
        rationale="Test fixture represents a question paper.",
    )


class FakePaperJobs:
    def __init__(self) -> None:
        self.created: tuple[str, bytes, str | None] | None = None
        self.reads = 0

    def create_job(
        self,
        filename: str,
        content: bytes,
        *,
        unit_code: str | None = None,
    ) -> PaperJobCreated:
        self.created = (filename, content, unit_code)
        return PaperJobCreated(job_id="job-1", status="queued", stage="queued")

    def create_job_from_stream(
        self,
        filename: str,
        stream: BytesIO,
        *,
        unit_code: str | None = None,
    ) -> PaperJobCreated:
        return self.create_job(filename, stream.read(), unit_code=unit_code)

    def get_job(self, job_id: str) -> PaperJobResponse:
        if job_id != "job-1":
            raise LookupError("试卷任务不存在")
        self.reads += 1
        completed = self.reads >= 3
        return PaperJobResponse(
            job_id=job_id,
            filename="paper.md",
            subject_pack_id="oxfordaqa-mathematics-9660",
            subject_code="9660",
            unit_code="P2",
            status="completed" if completed else "queued",
            stage="completed" if completed else "queued",
            total_pages=0,
            parsed_pages=0,
            total_questions=0,
            completed_questions=0,
            failed_questions=0,
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
        )

    def retry(self, job_id: str) -> PaperJobCreated:
        if job_id != "job-1":
            raise LookupError("试卷任务不存在")
        return PaperJobCreated(job_id=job_id, status="queued", stage="queued")


class CapturingCreateJobRepository:
    def __init__(self) -> None:
        self.values: dict[str, Any] | None = None

    def create(self, values: dict[str, Any]) -> None:
        self.values = values


class FakeUpload:
    filename = "paper.md"
    file = BytesIO(b"# Question 1\nSolve it.")


class FakeAnswerService:
    def split_questions(
        self,
        _markdown: str,
        *,
        unit_code: str | None = None,
    ) -> list[dict[str, Any]]:
        assert unit_code == "P2"
        return [
            {
                "number": "1",
                "question_markdown": "Evaluate the integral, showing all working.",
                "source_pages": [1],
                "knowledge_codes": ["P2.7.O03"],
            }
        ]

    def answer_question(
        self,
        item: dict[str, Any],
        *,
        unit_code: str | None = None,
        event_sink: Any | None = None,
    ) -> PaperQuestionAnswer:
        assert unit_code == "P2"
        if event_sink:
            event_sink(
                AgentStep(
                    sequence=1,
                    phase="preparing",
                    status="completed",
                    message="已加载测试能力",
                )
            )
            event_sink(
                AgentStep(
                    sequence=2,
                    phase="finalizing",
                    status="completed",
                    message="测试作答完成",
                )
            )
        return PaperQuestionAnswer(
            number=item["number"],
            question_markdown=item["question_markdown"],
            answer_markdown="Use integration by parts. [S1]",
            diagrams=[
                AnswerDiagram(
                    title="Axes",
                    elements=[
                        DiagramElement(
                            kind="line",
                            x1=0,
                            y1=50,
                            x2=100,
                            y2=50,
                            arrow_end=True,
                        )
                    ],
                )
            ],
            citations=[Citation(source="spec.pdf", page=22, excerpt="Integration by parts.")],
            confidence=0.9,
            grounded=True,
        )


class PostgresHarness:
    """Test-only SQL access for fault injection around repository integration tests."""

    def __init__(self, url: str):
        self.database_url = url
        self.sessions = create_session_factory(url)

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> None:
        statement, values = _named_statement(query, parameters)
        with self.sessions.begin() as session:
            session.execute(text(statement), values)

    def fetch_one(self, query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        statement, values = _named_statement(query, parameters)
        with self.sessions() as session:
            row = session.execute(text(statement), values).mappings().first()
        return dict(row) if row else None


def _named_statement(query: str, parameters: tuple[Any, ...]) -> tuple[str, dict[str, Any]]:
    parts = query.split("?")
    if len(parts) - 1 != len(parameters):
        raise ValueError("test SQL placeholder count does not match parameters")
    values = {f"p{index}": value for index, value in enumerate(parameters)}
    statement = parts[0]
    for index, part in enumerate(parts[1:]):
        statement += f":p{index}{part}"
    return statement, values


def _test_database() -> PostgresHarness:
    url = os.environ.get("EXAMTWIN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EXAMTWIN_TEST_DATABASE_URL is required for PostgreSQL job tests")
    upgrade_database(url)
    return PostgresHarness(url)


def _job_service(database: PostgresHarness, settings: Settings) -> PaperJobService:
    return PaperJobService(
        settings,
        subject_context(settings).with_retrieval_snapshot(
            version_ids=("test-kb-v1",),
            collections=("test-collection",),
            graph_version_id=None,
        ),
        repository=PaperJobRepository(
            database.sessions,
            lease_seconds=settings.paper_lease_seconds,
        ),
    )


def _job_runtime(database: PostgresHarness, settings: Settings) -> PaperJobRuntime:
    return PaperJobRuntime(
        PaperJobRepository(
            database.sessions,
            lease_seconds=settings.paper_lease_seconds,
        ),
        PaperSourceStore(settings.object_store_root / "paper-jobs"),
    )


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=595, height=842)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
