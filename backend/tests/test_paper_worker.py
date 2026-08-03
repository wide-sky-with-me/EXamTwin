from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from examtwin.config import Settings
from examtwin.schemas import (
    PaperQuestionAnswer,
)
from examtwin.services.paper_worker import PaperWorker
from examtwin.services.subject_context import subject_context

from backend.tests.paper_job_support import (
    FakeAnswerService,
)


def test_worker_carries_source_pages_and_trusted_jpegs_into_answer_service(
    tmp_path: Path,
) -> None:
    job_id = "job-with-images"
    image_root = tmp_path / job_id / "source-pages"
    image_root.mkdir(parents=True)
    for page_number in (2, 3):
        (image_root / f"{page_number:04d}.jpg").write_bytes(
            b"\xff\xd8" + f"page-{page_number}".encode()
        )

    class ImageJobs:
        root = tmp_path
        requested_pages: list[int] = []

        def source_file(self, requested_job_id: str) -> tuple[Path, str, str]:
            assert requested_job_id == job_id
            return tmp_path / job_id / "source.pdf", "source.pdf", ".pdf"

        def source_page(self, requested_job_id: str, page_number: int) -> Path:
            assert requested_job_id == job_id
            self.requested_pages.append(page_number)
            return image_root / f"{page_number:04d}.jpg"

        def source_page_root(self, requested_job_id: str) -> Path:
            assert requested_job_id == job_id
            return image_root

    class CapturingAnswerService(FakeAnswerService):
        item: dict[str, Any] | None = None

        def answer_question(
            self,
            item: dict[str, Any],
            *,
            unit_code: str | None = None,
            event_sink: Any | None = None,
        ) -> PaperQuestionAnswer:
            self.item = item
            return super().answer_question(
                item,
                unit_code=unit_code,
                event_sink=event_sink,
            )

    jobs = ImageJobs()
    answer_service = CapturingAnswerService()
    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=jobs,  # type: ignore[arg-type]
        answer_service=answer_service,  # type: ignore[arg-type]
    )

    worker._answer_question(
        {
            "job_id": job_id,
            "number": "8",
            "question_markdown": "Use the graph to find the probability.",
            "source_pages_json": "[2, 3]",
            "knowledge_codes_json": "[]",
        },
        "P2",
        event_sink=lambda _step: None,
    )

    assert jobs.requested_pages == [2, 3]
    assert answer_service.item is not None
    assert answer_service.item["source_pages"] == [2, 3]
    assert [
        (image.page_number, image.content) for image in answer_service.item["question_images"]
    ] == [
        (2, b"\xff\xd8page-2"),
        (3, b"\xff\xd8page-3"),
    ]


def test_worker_skips_page_pixels_for_text_only_pdf_question(tmp_path: Path) -> None:
    class TextOnlyPdfJobs:
        root = tmp_path

        def source_file(self, _job_id: str) -> tuple[Path, str, str]:
            return tmp_path / "source.pdf", "source.pdf", ".pdf"

        def source_page(self, _job_id: str, _page_number: int) -> Path:
            raise AssertionError("text-only questions must not invoke question vision")

    class CapturingAnswerService(FakeAnswerService):
        images: tuple[Any, ...] | None = None

        def answer_question(
            self,
            item: dict[str, Any],
            *,
            unit_code: str | None = None,
            event_sink: Any | None = None,
        ) -> PaperQuestionAnswer:
            self.images = item["question_images"]
            return super().answer_question(
                item,
                unit_code=unit_code,
                event_sink=event_sink,
            )

    answer_service = CapturingAnswerService()
    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=TextOnlyPdfJobs(),  # type: ignore[arg-type]
        answer_service=answer_service,  # type: ignore[arg-type]
    )

    worker._answer_question(
        {
            "job_id": "text-only-pdf",
            "number": "4",
            "question_markdown": "Find the probability that exactly 2 phones are faulty.",
            "source_pages_json": "[8, 9]",
            "requires_visual_context": False,
            "knowledge_codes_json": "[]",
        },
        "P2",
        event_sink=lambda _step: None,
    )

    assert answer_service.images == ()


def test_worker_does_not_fabricate_question_images_for_markdown(
    tmp_path: Path,
) -> None:
    job_id = "markdown-job"

    class MarkdownJobs:
        root = tmp_path

        def source_file(self, _job_id: str) -> tuple[Path, str, str]:
            return tmp_path / "source.md", "source.md", ".md"

        def source_page(self, _job_id: str, _page_number: int) -> Path:
            raise AssertionError("Markdown jobs must not render a source page")

    class CapturingAnswerService(FakeAnswerService):
        images: tuple[Any, ...] | None = None

        def answer_question(
            self,
            item: dict[str, Any],
            *,
            unit_code: str | None = None,
            event_sink: Any | None = None,
        ) -> PaperQuestionAnswer:
            self.images = item["question_images"]
            return super().answer_question(
                item,
                unit_code=unit_code,
                event_sink=event_sink,
            )

    answer_service = CapturingAnswerService()
    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=MarkdownJobs(),  # type: ignore[arg-type]
        answer_service=answer_service,  # type: ignore[arg-type]
    )

    worker._answer_question(
        {
            "job_id": job_id,
            "number": "1",
            "question_markdown": "A Markdown-only question.",
            "source_pages_json": "[1]",
            "knowledge_codes_json": "[]",
        },
        "P2",
        event_sink=lambda _step: None,
    )

    assert answer_service.images == ()


def test_worker_rejects_question_image_path_outside_safe_cache(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"\xff\xd8outside")

    class EscapingJobs:
        root = tmp_path / "paper-jobs"

        def source_file(self, _job_id: str) -> tuple[Path, str, str]:
            return self.root / "job-1" / "source.pdf", "source.pdf", ".pdf"

        def source_page(self, _job_id: str, _page_number: int) -> Path:
            return outside

        def source_page_root(self, _job_id: str) -> Path:
            return self.root / "job-1" / "source-pages"

    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path / "paper-jobs"),
        subject_context(Settings(object_store_local_root=tmp_path / "paper-jobs")),
        jobs=EscapingJobs(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="安全缓存目录"):
        worker._load_question_images(
            {
                "job_id": "job-1",
                "source_pages_json": "[1]",
                "requires_visual_context": True,
            }
        )


def test_question_vision_failure_is_retried_by_worker(tmp_path: Path) -> None:
    job_id = "vision-retry-job"
    image_root = tmp_path / job_id / "source-pages"
    image_root.mkdir(parents=True)
    (image_root / "0001.jpg").write_bytes(b"\xff\xd8page-1")

    class RetryJobs:
        root = tmp_path
        starts = 0
        requeues = 0

        def source_file(self, _job_id: str) -> tuple[Path, str, str]:
            return tmp_path / job_id / "source.pdf", "source.pdf", ".pdf"

        def source_page(self, _job_id: str, _page_number: int) -> Path:
            return image_root / "0001.jpg"

        def source_page_root(self, _job_id: str) -> Path:
            return image_root

        def start_question(
            self,
            _job_id: str,
            _token: str,
            _position: int,
        ) -> int:
            self.starts += 1
            return self.starts

        def record_agent_step(self, *_args: Any) -> None:
            return None

        def requeue_question(self, *_args: Any) -> None:
            self.requeues += 1

    class FailingVisionAnswerService:
        calls = 0

        def answer_question(self, *_args: Any, **_kwargs: Any) -> PaperQuestionAnswer:
            self.calls += 1
            raise RuntimeError("vision provider unavailable")

    jobs = RetryJobs()
    answer_service = FailingVisionAnswerService()
    worker = PaperWorker(
        Settings(
            object_store_local_root=tmp_path,
            paper_question_max_attempts=2,
            paper_question_retry_delay_seconds=0,
        ),
        subject_context(
            Settings(
                object_store_local_root=tmp_path,
                paper_question_max_attempts=2,
                paper_question_retry_delay_seconds=0,
            )
        ),
        jobs=jobs,  # type: ignore[arg-type]
        answer_service=answer_service,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="vision provider unavailable"):
        worker._answer_pending_question(
            job_id,
            "lease-token",
            {
                "job_id": job_id,
                "position": 0,
                "number": "1",
                "question_markdown": "Read the original graph.",
                "source_pages_json": "[1]",
                "knowledge_codes_json": "[]",
            },
            "P2",
        )

    assert answer_service.calls == 2
    assert jobs.starts == 2
    assert jobs.requeues == 1
