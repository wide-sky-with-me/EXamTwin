from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from examtwin.assessment.paper_classification import PaperDocumentClassification
from examtwin.assessment.paper_parsing import (
    ExtractedPaperImage,
    ParsedPaperChunk,
    extract_paper_chunk,
)
from examtwin.assessment.paper_worker import PaperWorker
from examtwin.contracts import (
    PaperQuestionAnswer,
)
from examtwin.platform.config import Settings
from examtwin.subjects.public import subject_context

from backend.tests.paper_job_support import (
    FakeAnswerService,
)


def test_split_checkpoint_requires_matching_input_digest(tmp_path: Path) -> None:
    class CheckpointFiles:
        def resolve_file(self, relative_path: str) -> Path:
            return tmp_path / relative_path

        def write_file(self, relative_path: str, content: bytes | str) -> None:
            path = tmp_path / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())

    settings = Settings(object_store_local_root=tmp_path)
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=CheckpointFiles(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
    )
    questions = [{"number": "1", "question_markdown": "1 Find x."}]

    worker._save_split_checkpoint("job-1", 0, 2, "digest-a", questions, 25.0)

    assert worker._load_split_checkpoint("job-1", 0, "digest-a") == questions
    assert worker._load_split_checkpoint("job-1", 0, "digest-b") is None


def test_worker_persists_mineru_images_and_keeps_their_markdown_position(
    tmp_path: Path,
) -> None:
    class AssetFiles:
        def write_file(self, relative_path: str, content: bytes | str) -> None:
            path = tmp_path / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())

    content = b"extracted-image"
    parsed = ParsedPaperChunk(
        markdown="Before diagram.\n\n![Force diagram](images/figure.png)\n\nAfter diagram.",
        images=(
            ExtractedPaperImage(
                name="figure.png",
                path="images/figure.png",
                content=content,
                page_index=2,
            ),
        ),
    )
    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=AssetFiles(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
    )
    markdown = worker._persist_chunk_images("job-1", 7, 9, parsed)

    digest = hashlib.sha256(content).hexdigest()
    asset_name = f"p0009-{digest}.png"
    url = f"/api/v1/papers/jobs/job-1/question-images/{asset_name}"
    assert markdown == f"Before diagram.\n\n![Force diagram]({url})\n\nAfter diagram."
    assert (tmp_path / "job-1" / "question-images" / asset_name).read_bytes() == content

    with pytest.raises(ValueError, match="缺少物理页位置"):
        worker._persist_chunk_images(
            "job-2",
            7,
            9,
            ParsedPaperChunk(
                markdown="![Unmapped diagram](images/unmapped.png)",
                images=(
                    ExtractedPaperImage(
                        name="unmapped.png",
                        path="images/unmapped.png",
                        content=b"unmapped-image",
                    ),
                ),
            ),
        )


def test_paper_chunk_extraction_retains_mineru_image_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}

    class FakeMinerU:
        def __init__(self, *, token: str | None) -> None:
            calls["token"] = token

        def __enter__(self) -> FakeMinerU:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def set_source(self, source: str) -> None:
            calls["source"] = source

        def extract(self, source: str, **kwargs: object) -> object:
            calls["path"] = source
            calls["kwargs"] = kwargs
            return SimpleNamespace(
                state="done",
                error=None,
                markdown="Question\n\n![Graph](images/graph.png)",
                images=[
                    SimpleNamespace(
                        name="graph.png",
                        path="images/graph.png",
                        data=b"graph-bytes",
                    )
                ],
                content_list=[
                    {
                        "type": "image",
                        "img_path": "images/graph.png",
                        "page_idx": 2,
                    }
                ],
            )

    monkeypatch.setattr("examtwin.assessment.paper_parsing.MinerU", FakeMinerU)
    source = tmp_path / "chunk.pdf"
    source.write_bytes(b"pdf")

    result = extract_paper_chunk(
        Settings(mineru_token="secret", mineru_mode="precision"),
        source,
        timeout=123,
    )

    assert result.images == (
        ExtractedPaperImage(
            name="graph.png",
            path="images/graph.png",
            content=b"graph-bytes",
            page_index=2,
        ),
    )
    assert calls["token"] == "secret"
    assert calls["source"] == "examtwin-paper"
    assert calls["kwargs"] == {
        "language": "en",
        "ocr": True,
        "formula": True,
        "table": True,
        "timeout": 123,
    }


def test_worker_checkpoints_and_reuses_non_question_classification(tmp_path: Path) -> None:
    class ClassificationFiles:
        def resolve_file(self, relative_path: str) -> Path:
            return tmp_path / relative_path

        def write_file(self, relative_path: str, content: bytes | str) -> None:
            path = tmp_path / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())

    calls = 0

    def classify(_markdown: str) -> PaperDocumentClassification:
        nonlocal calls
        calls += 1
        return PaperDocumentClassification(
            document_type="mark_scheme",
            confidence=0.99,
            evidence=["MARK SCHEME"],
            rationale="The document contains scoring instructions.",
        )

    settings = Settings(object_store_local_root=tmp_path)
    worker = PaperWorker(
        settings,
        subject_context(settings),
        jobs=ClassificationFiles(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        document_classifier=classify,
    )

    for _ in range(2):
        with pytest.raises(ValueError, match="Mark Scheme"):
            worker._classify_document("job-1", "Parsed scoring guidance and acceptable answers.")

    assert calls == 1


def test_worker_activates_the_subject_persisted_on_each_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SnapshotRepository:
        def __init__(self, _sessions: object) -> None:
            pass

        def retrieval_snapshot_for_versions(
            self,
            subject_id: str,
            version_ids: list[str],
        ) -> dict[str, object]:
            assert subject_id
            assert version_ids == ["economics-version-1"]
            return {"collections": ["economics-collection-1"]}

    monkeypatch.setattr(
        "examtwin.assessment.paper_worker.WorkspaceRepository",
        SnapshotRepository,
    )
    settings = Settings(object_store_local_root=tmp_path)
    mathematics = subject_context(settings, "9660")
    economics = subject_context(settings, "9640")
    services: list[str] = []

    def answer_service_for(subject: Any) -> FakeAnswerService:
        services.append(subject.subject_code)
        return FakeAnswerService()

    worker = PaperWorker(
        settings,
        mathematics,
        jobs=object(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
        subject_resolver=lambda selector: subject_context(settings, selector),
        answer_service_factory=answer_service_for,  # type: ignore[arg-type]
    )

    worker._activate_job_subject(
        {
            "subject_pack_id": economics.pack.id,
            "subject_code": economics.subject_code,
            "knowledge_base_version_ids_json": '["economics-version-1"]',
            "graph_version_id": None,
        }
    )

    assert worker.subject.subject_code == "9640"
    assert services == ["9640"]


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
            "requires_visual_context": True,
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


def test_worker_rejects_legacy_placeholder_instead_of_rederiving_visual_flag(
    tmp_path: Path,
) -> None:
    job_id = "placeholder-pdf"

    class PlaceholderPdfJobs:
        def source_file(self, requested_job_id: str) -> tuple[Path, str, str]:
            assert requested_job_id == job_id
            return tmp_path / job_id / "source.pdf", "source.pdf", ".pdf"

    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=PlaceholderPdfJobs(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="来源完整性契约"):
        worker._load_question_images(
            {
                "job_id": job_id,
                "question_markdown": (
                    "$F(x)=\\text{[piecewise definition as printed]}$. Find $h$."
                ),
                "source_pages_json": "[16]",
                "requires_visual_context": False,
            }
        )


def test_worker_rejects_pdf_question_without_persisted_visual_decision(
    tmp_path: Path,
) -> None:
    job_id = "legacy-pdf"

    class LegacyPdfJobs:
        def source_file(self, requested_job_id: str) -> tuple[Path, str, str]:
            assert requested_job_id == job_id
            return tmp_path / job_id / "source.pdf", "source.pdf", ".pdf"

    worker = PaperWorker(
        Settings(object_store_local_root=tmp_path),
        subject_context(Settings(object_store_local_root=tmp_path)),
        jobs=LegacyPdfJobs(),  # type: ignore[arg-type]
        answer_service=FakeAnswerService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="视觉上下文判定"):
        worker._load_question_images(
            {
                "job_id": job_id,
                "question_markdown": "Find the probability.",
                "source_pages_json": "[8]",
                "requires_visual_context": None,
            }
        )


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
                "requires_visual_context": True,
            },
            "P2",
        )

    assert answer_service.calls == 2
    assert jobs.starts == 2
    assert jobs.requeues == 1
