from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, cast

from examtwin.answering_agent.contracts import AgentRunLedger, AgentStep, QuestionImage
from examtwin.config import Settings
from examtwin.persistence.paper_job_repository import LostLeaseError
from examtwin.persistence.session import create_session_factory
from examtwin.persistence.workspace_repository import WorkspaceRepository
from examtwin.schemas.papers import PaperQuestionAnswer
from examtwin.services.agent_run_ledger import PaperAgentRunLedger
from examtwin.services.corpus_ingestion import render_documents
from examtwin.services.inventory import parse_exam_identity
from examtwin.services.paper_answering import SPLIT_CONTRACT_VERSION, PaperAnswerService
from examtwin.services.paper_classification import (
    PAPER_CLASSIFICATION_CONTRACT_VERSION,
    PaperDocumentClassification,
    PaperDocumentClassifier,
    PaperDocumentClassifierFn,
    require_question_paper,
)
from examtwin.services.paper_job_runtime import PaperJobRuntime
from examtwin.services.paper_parsing import (
    mineru_reader,
    question_requires_visual_context,
)
from examtwin.services.paper_vision import (
    PaperVisionReviewer,
    VisionReviewResult,
    format_physical_page_markdown,
    validate_physical_page_markdown,
)
from examtwin.services.subject_context import SubjectContext
from examtwin.services.task_events import PaperJobWakeup, SleepPaperJobWakeup
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)


class StageFailure(RuntimeError):
    def __init__(self, stage: str, error: Exception):
        super().__init__(str(error))
        self.stage = stage
        self.error = error


def _provider_trace(error: Exception) -> str:
    trace_id = getattr(error, "trace_id", "")
    return str(trace_id) if trace_id else "-"


def _pdf_text_recovery(path: Path) -> str:
    pages: list[tuple[int, str]] = []
    for page_number, page in enumerate(PdfReader(path).pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append((page_number, text))
    return (
        "## PDF text-layer recovery appendix\n"
        "Use this only to restore wording omitted by MinerU; do not duplicate questions.\n\n"
        + format_physical_page_markdown(pages)
    )


class PaperWorker:
    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        jobs: PaperJobRuntime,
        answer_service: PaperAnswerService,
        document_classifier: PaperDocumentClassifierFn | None = None,
        chunk_parser: Callable[[Path, int, int], str] | None = None,
        vision_reviewer: (Callable[[Path, str, int, int], VisionReviewResult] | None) = None,
        wakeup: PaperJobWakeup | None = None,
        subject_resolver: Callable[[str], SubjectContext] | None = None,
        answer_service_factory: Callable[[SubjectContext], PaperAnswerService] | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.jobs = jobs
        self.answer_service = answer_service
        self.document_classifier = document_classifier
        self.chunk_parser = chunk_parser or self._parse_pdf_chunk
        self.vision_reviewer = vision_reviewer or PaperVisionReviewer(settings).review_chunk
        self.wakeup = wakeup or SleepPaperJobWakeup()
        self.subject_resolver = subject_resolver
        self.answer_service_factory = answer_service_factory

    def _activate_job_subject(self, job: dict[str, Any]) -> None:
        package_id = str(job.get("subject_pack_id") or "")
        if self.subject_resolver is not None:
            self.subject = self.subject_resolver(package_id)
            raw_version_ids = json.loads(str(job.get("knowledge_base_version_ids_json") or "[]"))
            if not isinstance(raw_version_ids, list) or not raw_version_ids:
                raise ValueError("试卷任务缺少已发布知识库版本快照")
            version_ids = [str(item) for item in raw_version_ids]
            snapshot = WorkspaceRepository(
                create_session_factory(self.settings.database_url)
            ).retrieval_snapshot_for_versions(self.subject.id, version_ids)
            self.subject = self.subject.with_retrieval_snapshot(
                version_ids=tuple(version_ids),
                collections=tuple(str(item) for item in snapshot["collections"]),
                graph_version_id=(
                    str(job["graph_version_id"]) if job.get("graph_version_id") else None
                ),
            )
            if self.answer_service_factory is None:
                raise RuntimeError("multi-subject worker is missing its answer service factory")
            self.answer_service = self.answer_service_factory(self.subject)
        self.subject.require(str(job.get("subject_code") or ""))

    def _classify_document(
        self,
        job_id: str,
        markdown: str,
    ) -> PaperDocumentClassification:
        classifier = self.document_classifier
        if classifier is None:
            model_classifier = PaperDocumentClassifier(self.settings)
            classifier = model_classifier.classify
            self.document_classifier = classifier
        classifier_owner = getattr(classifier, "__self__", None)
        model_name = str(getattr(classifier_owner, "model_name", self.settings.paper_split_model))
        input_digest = hashlib.sha256(
            json.dumps(
                {
                    "contract": PAPER_CLASSIFICATION_CONTRACT_VERSION,
                    "model": model_name,
                    "markdown": markdown,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        relative_path = f"{job_id}/classification.json"
        path = self.jobs.resolve_file(relative_path)
        classification: PaperDocumentClassification | None = None
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if (
                    payload.get("contract_version") != PAPER_CLASSIFICATION_CONTRACT_VERSION
                    or payload.get("input_digest") != input_digest
                    or payload.get("model") != model_name
                ):
                    raise ValueError("paper classification checkpoint provenance mismatch")
                classification = PaperDocumentClassification.model_validate(
                    payload["classification"]
                )
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                logger.warning(
                    "paper classification checkpoint rejected",
                    extra={
                        "event": "paper_classification_checkpoint_rejected",
                        "job_id": job_id,
                        "stage": "splitting",
                    },
                )
        if classification is None:
            classification = classifier(markdown)
            self.jobs.write_file(
                relative_path,
                json.dumps(
                    {
                        "contract_version": PAPER_CLASSIFICATION_CONTRACT_VERSION,
                        "input_digest": input_digest,
                        "model": model_name,
                        "classification": classification.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        logger.info(
            "paper content classified",
            extra={
                "event": "paper_content_classified",
                "job_id": job_id,
                "stage": "splitting",
                "document_type": classification.document_type,
                "confidence": classification.confidence,
                "model": model_name,
            },
        )
        require_question_paper(classification)
        return classification

    def run_once(self) -> bool:
        claimed = self.jobs.claim_next()
        if not claimed:
            return False
        job, token = claimed
        self._process(job, token)
        return True

    def run_forever(self) -> None:
        logger.info("paper worker started")
        while True:
            if not self.run_once():
                self.wakeup.wait(self.settings.paper_worker_poll_seconds)

    def _process(self, job: dict[str, Any], token: str) -> None:
        job_id = job["id"]
        self._activate_job_subject(job)
        with self._heartbeat(job_id, token):
            try:
                self.jobs.recover_inflight(job_id, token)
                self._parse(job, token)
                self._split(job, token)
                self._answer(job, token)
                self.jobs.finish_job(job_id, token)
                logger.info("paper_job=%s stage=completed", job_id)
            except LostLeaseError:
                logger.warning("paper_job=%s lease_lost=1", job_id)
            except StageFailure as failure:
                try:
                    self.jobs.fail_job(job_id, token, failure.stage, failure.error)
                except LostLeaseError:
                    logger.warning("paper_job=%s lease_lost_while_failing=1", job_id)
                    return
                logger.exception(
                    "paper_job=%s stage=%s failed=%s provider_trace=%s",
                    job_id,
                    failure.stage,
                    type(failure.error).__name__,
                    _provider_trace(failure.error),
                )
            except Exception as error:
                try:
                    self.jobs.fail_job(job_id, token, "queued", error)
                except LostLeaseError:
                    logger.warning("paper_job=%s lease_lost_while_failing=1", job_id)
                    return
                logger.exception(
                    "paper_job=%s stage=queued failed=%s provider_trace=%s",
                    job_id,
                    type(error).__name__,
                    _provider_trace(error),
                )

    def _parse(self, job: dict[str, Any], token: str) -> None:
        job_id = job["id"]
        source_path = self.jobs.source_path(job)
        try:
            if job["suffix"] in {".md", ".markdown"}:
                self.jobs.ensure_chunks(job_id, token, 1, 1)
            else:
                total_pages = len(PdfReader(str(source_path)).pages)
                if total_pages < 1:
                    raise ValueError("PDF 没有可解析页面")
                self.jobs.ensure_chunks(
                    job_id,
                    token,
                    total_pages,
                    self.settings.paper_chunk_pages,
                )
            self.jobs.set_stage(job_id, token, "parsing")
            for chunk in self.jobs.list_chunks(job_id):
                if chunk["status"] == "completed":
                    continue
                self.jobs.start_chunk(job_id, token, chunk["chunk_index"])
                started = time.monotonic()
                try:
                    if job["suffix"] in {".md", ".markdown"}:
                        markdown = source_path.read_text(encoding="utf-8-sig")
                    else:
                        markdown = self.chunk_parser(
                            source_path,
                            chunk["page_start"],
                            chunk["page_end"],
                        )
                    if len(markdown.strip()) < 10:
                        raise ValueError("MinerU 返回的页段内容过短")
                    markdown_rel = (
                        f"{job_id}/chunks/{chunk['chunk_index']:04d}-"
                        f"{chunk['page_start']}-{chunk['page_end']}.md"
                    )
                    self.jobs.write_file(markdown_rel, markdown)
                    self.jobs.complete_chunk(
                        job_id,
                        token,
                        chunk["chunk_index"],
                        markdown_rel,
                    )
                    logger.info(
                        "paper_job=%s stage=parsing chunk=%s pages=%s-%s duration=%.2fs",
                        job_id,
                        chunk["chunk_index"],
                        chunk["page_start"],
                        chunk["page_end"],
                        time.monotonic() - started,
                    )
                except Exception as error:
                    self.jobs.fail_chunk(job_id, token, chunk["chunk_index"], error)
                    raise StageFailure("parsing", error) from error
        except (LostLeaseError, StageFailure):
            raise
        except Exception as error:
            raise StageFailure("parsing", error) from error

    def _split(self, job: dict[str, Any], token: str) -> None:
        job_id = job["id"]
        if self.jobs.list_questions(job_id):
            return
        vision_review_enabled = job["suffix"] == ".pdf" and self.settings.paper_vision_enabled
        active_stage = "splitting"
        self.jobs.set_stage(job_id, token, active_stage)
        started = time.monotonic()
        try:
            chunks = self.jobs.list_chunks(job_id)
            source_path = self.jobs.source_path(job)
            reviewed_by_chunk: dict[int, str] = {}
            pending_reviews: list[tuple[dict[str, Any], str]] = []
            classification_sections: list[str] = []
            for chunk in chunks:
                if chunk["status"] != "completed" or not chunk["markdown_path"]:
                    raise ValueError("仍有未完成的 PDF 页段")
                markdown_path = self.jobs.resolve_file(chunk["markdown_path"])
                markdown = markdown_path.read_text(encoding="utf-8")
                classification_sections.append(markdown)
                if vision_review_enabled:
                    reviewed_path = markdown_path.with_suffix(".vision.md")
                    reviewed_is_valid = False
                    if reviewed_path.is_file():
                        cached = reviewed_path.read_text(encoding="utf-8")
                        try:
                            validate_physical_page_markdown(
                                cached,
                                chunk["page_start"],
                                chunk["page_end"],
                            )
                            markdown = cached
                            reviewed_is_valid = True
                        except ValueError:
                            logger.warning(
                                "paper_job=%s stage=vision_review "
                                "pages=%s-%s invalid_cached_provenance=1",
                                job_id,
                                chunk["page_start"],
                                chunk["page_end"],
                            )
                    if not reviewed_is_valid:
                        pending_reviews.append((chunk, markdown))
                    else:
                        reviewed_by_chunk[chunk["chunk_index"]] = markdown
                else:
                    reviewed_by_chunk[chunk["chunk_index"]] = markdown
            self._classify_document(job_id, "\n\n".join(classification_sections))
            if vision_review_enabled:
                active_stage = "vision_review"
                self.jobs.set_stage(job_id, token, active_stage)

            first_review_error: Exception | None = None
            if pending_reviews:
                with ThreadPoolExecutor(
                    max_workers=min(
                        self.settings.paper_vision_concurrency,
                        len(pending_reviews),
                    )
                ) as executor:
                    futures = {
                        executor.submit(
                            self.vision_reviewer,
                            source_path,
                            markdown,
                            chunk["page_start"],
                            chunk["page_end"],
                        ): (chunk, time.monotonic())
                        for chunk, markdown in pending_reviews
                    }
                    for future in as_completed(futures):
                        chunk, review_started = futures[future]
                        try:
                            review = future.result()
                            markdown = review.markdown
                            validate_physical_page_markdown(
                                markdown,
                                chunk["page_start"],
                                chunk["page_end"],
                            )
                            reviewed_rel = str(
                                Path(chunk["markdown_path"]).with_suffix(".vision.md")
                            )
                            review_rel = str(
                                Path(chunk["markdown_path"]).with_suffix(".vision.json")
                            )
                            self.jobs.write_file(reviewed_rel, markdown)
                            self.jobs.write_file(
                                review_rel,
                                json.dumps(
                                    {
                                        "model": review.model,
                                        "page_start": chunk["page_start"],
                                        "page_end": chunk["page_end"],
                                        "confidence": review.confidence,
                                        "repairs": list(review.repairs),
                                    },
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                            )
                            reviewed_by_chunk[chunk["chunk_index"]] = markdown
                            logger.info(
                                "paper vision review completed",
                                extra={
                                    "event": "paper_vision_review_completed",
                                    "job_id": job_id,
                                    "stage": "vision_review",
                                    "page_start": chunk["page_start"],
                                    "page_end": chunk["page_end"],
                                    "duration_ms": round(
                                        (time.monotonic() - review_started) * 1000,
                                        2,
                                    ),
                                },
                            )
                        except Exception as error:
                            first_review_error = first_review_error or error
            if first_review_error is not None:
                raise first_review_error

            sections = [
                f"<!-- pages {chunk['page_start']}-{chunk['page_end']} -->\n"
                f"{reviewed_by_chunk[chunk['chunk_index']]}"
                for chunk in chunks
            ]
            primary_markdown = "\n\n".join(sections)
            if job["suffix"] == ".pdf":
                recovery = _pdf_text_recovery(source_path)
                if recovery:
                    sections.append(recovery)
            if vision_review_enabled:
                active_stage = "splitting"
                self.jobs.set_stage(job_id, token, active_stage)
            paper_markdown = "\n\n".join(sections)
            checkpointed_split = getattr(
                self.answer_service,
                "split_questions_checkpointed",
                None,
            )
            if callable(checkpointed_split):
                questions = cast(
                    list[dict[str, Any]],
                    checkpointed_split(
                        paper_markdown,
                        unit_code=job["unit_code"],
                        source_markdown=primary_markdown,
                        load_checkpoint=partial(self._load_split_checkpoint, job_id),
                        save_checkpoint=partial(self._save_split_checkpoint, job_id),
                    ),
                )
            else:
                questions = self.answer_service.split_questions(
                    paper_markdown,
                    unit_code=job["unit_code"],
                )
            self.jobs.store_questions(job_id, token, questions)
            logger.info(
                "paper_job=%s stage=splitting questions=%s duration=%.2fs",
                job_id,
                len(questions),
                time.monotonic() - started,
            )
        except LostLeaseError:
            raise
        except Exception as error:
            raise StageFailure(active_stage, error) from error

    def _load_split_checkpoint(
        self,
        job_id: str,
        batch_index: int,
        input_digest: str,
    ) -> list[dict[str, Any]] | None:
        relative_path = f"{job_id}/split/{batch_index:04d}.json"
        path = self.jobs.resolve_file(relative_path)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            questions = payload["questions"]
            if (
                payload.get("contract_version") != SPLIT_CONTRACT_VERSION
                or payload.get("input_digest") != input_digest
                or payload.get("batch_index") != batch_index
                or not isinstance(questions, list)
                or not all(isinstance(item, dict) for item in questions)
            ):
                raise ValueError("split checkpoint provenance mismatch")
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning(
                "paper split checkpoint rejected",
                extra={
                    "event": "paper_split_checkpoint_rejected",
                    "job_id": job_id,
                    "stage": "splitting",
                    "batch_index": batch_index,
                },
            )
            return None
        logger.info(
            "paper split checkpoint reused",
            extra={
                "event": "paper_split_batch_reused",
                "job_id": job_id,
                "stage": "splitting",
                "batch_index": batch_index,
                "cache_hit": True,
            },
        )
        return questions

    def _save_split_checkpoint(
        self,
        job_id: str,
        batch_index: int,
        batch_count: int,
        input_digest: str,
        questions: list[dict[str, Any]],
        duration_ms: float,
    ) -> None:
        relative_path = f"{job_id}/split/{batch_index:04d}.json"
        self.jobs.write_file(
            relative_path,
            json.dumps(
                {
                    "contract_version": SPLIT_CONTRACT_VERSION,
                    "input_digest": input_digest,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                    "questions": questions,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        logger.info(
            "paper split batch completed",
            extra={
                "event": "paper_split_batch_completed",
                "job_id": job_id,
                "stage": "splitting",
                "batch_index": batch_index,
                "batch_count": batch_count,
                "cache_hit": False,
                "duration_ms": round(duration_ms, 2),
            },
        )

    def _answer(self, job: dict[str, Any], token: str) -> None:
        job_id = job["id"]
        pending = [item for item in self.jobs.list_questions(job_id) if item["status"] == "pending"]
        self.jobs.set_stage(job_id, token, "answering")
        if not pending:
            return
        with ThreadPoolExecutor(
            max_workers=min(self.settings.paper_question_concurrency, len(pending))
        ) as executor:
            futures = {
                executor.submit(
                    self._answer_pending_question,
                    job_id,
                    token,
                    item,
                    job["unit_code"],
                ): (
                    item,
                    time.monotonic(),
                )
                for item in pending
            }
            for future in as_completed(futures):
                item, started = futures[future]
                try:
                    self.jobs.complete_question(
                        job_id,
                        token,
                        item["position"],
                        future.result(),
                    )
                    logger.info(
                        "paper_job=%s stage=answering question=%s duration=%.2fs",
                        job_id,
                        item["number"],
                        time.monotonic() - started,
                    )
                except LostLeaseError:
                    raise
                except Exception as error:
                    self.jobs.fail_question(job_id, token, item["position"], error)
                    logger.exception(
                        "paper_job=%s stage=answering question=%s failed=%s provider_trace=%s",
                        job_id,
                        item["number"],
                        type(error).__name__,
                        _provider_trace(error),
                    )

    def _answer_pending_question(
        self,
        job_id: str,
        token: str,
        row: dict[str, Any],
        unit_code: str | None,
    ) -> PaperQuestionAnswer:
        for attempt in range(1, self.settings.paper_question_max_attempts + 1):
            run_attempt = self.jobs.start_question(job_id, token, row["position"])
            repository = getattr(self.jobs, "repository", None)
            ledger = (
                None
                if repository is None
                else PaperAgentRunLedger(
                    repository,
                    job_id=job_id,
                    lease_token=token,
                    question_position=row["position"],
                    run_attempt=run_attempt,
                )
            )
            try:
                return self._answer_question(
                    row,
                    unit_code,
                    event_sink=lambda step, run_attempt=run_attempt: self.jobs.record_agent_step(
                        job_id,
                        token,
                        row["position"],
                        run_attempt,
                        step,
                    ),
                    ledger=ledger,
                )
            except LostLeaseError:
                raise
            except Exception as error:
                if attempt >= self.settings.paper_question_max_attempts:
                    raise
                self.jobs.requeue_question(job_id, token, row["position"], error)
                delay = self.settings.paper_question_retry_delay_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "paper_job=%s stage=answering question=%s retry=%s/%s "
                    "delay=%.1fs failed=%s provider_trace=%s",
                    job_id,
                    row["number"],
                    attempt,
                    self.settings.paper_question_max_attempts,
                    delay,
                    type(error).__name__,
                    _provider_trace(error),
                )
                if delay:
                    time.sleep(delay)
        raise RuntimeError("question retry loop exhausted")

    def _answer_question(
        self,
        row: dict[str, Any],
        unit_code: str | None,
        *,
        event_sink: Callable[[AgentStep], None],
        ledger: AgentRunLedger | None = None,
    ) -> PaperQuestionAnswer:
        source_pages, question_images = self._load_question_images(row)
        job_id = str(row.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("题目缺少所属试卷任务")
        _source_path, filename, _suffix = self.jobs.source_file(job_id)
        pair_key = parse_exam_identity(
            Path(filename),
            "question_paper",
            self.subject.pack,
        )["pair_key"]
        try:
            requirements = json.loads(row.get("requirements_json") or "{}")
        except json.JSONDecodeError as error:
            raise ValueError("题目答案要求数据损坏") from error
        call_options: dict[str, Any] = {
            "unit_code": unit_code,
            "event_sink": event_sink,
        }
        if ledger is not None and isinstance(self.answer_service, PaperAnswerService):
            call_options["ledger"] = ledger
        if pair_key:
            call_options["pair_key"] = pair_key
        return self.answer_service.answer_question(
            {
                "number": row["number"],
                "question_markdown": row["question_markdown"],
                "source_pages": source_pages,
                "question_images": question_images,
                "knowledge_codes": json.loads(row["knowledge_codes_json"]),
                "answer_requirements": requirements.get("subparts", []),
                "total_marks": requirements.get("total_marks"),
            },
            **call_options,
        )

    def _load_question_images(
        self,
        row: dict[str, Any],
    ) -> tuple[list[int], tuple[QuestionImage, ...]]:
        try:
            raw_pages = json.loads(row["source_pages_json"] or "[]")
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("题目来源页数据损坏") from error
        if not isinstance(raw_pages, list):
            raise ValueError("题目来源页必须是数组")
        pages: list[int] = []
        for value in raw_pages:
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("题目来源页必须是正整数")
            if value not in pages:
                pages.append(value)

        job_id = str(row.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("题目缺少所属试卷任务")
        _source_path, _filename, suffix = self.jobs.source_file(job_id)
        if suffix != ".pdf":
            return pages, ()
        requires_visual = row.get("requires_visual_context")
        if requires_visual is None:
            requires_visual = question_requires_visual_context(
                str(row.get("question_markdown", ""))
            )
        if not requires_visual:
            return pages, ()
        if not pages:
            raise ValueError("PDF 题目缺少可信的原卷来源页")
        if len(pages) > self.settings.paper_question_image_max_pages:
            raise ValueError("题目原卷页数超过视觉输入上限")

        safe_root = self.jobs.source_page_root(job_id)
        total_bytes = 0
        images: list[QuestionImage] = []
        for page_number in pages:
            image_path = self.jobs.source_page(job_id, page_number).resolve()
            if not image_path.is_relative_to(safe_root):
                raise ValueError("题目原卷页图路径越过安全缓存目录")
            content = image_path.read_bytes()
            total_bytes += len(content)
            if total_bytes > self.settings.paper_question_image_max_total_bytes:
                raise ValueError("题目原卷页图总大小超过视觉输入上限")
            images.append(
                QuestionImage(
                    page_number=page_number,
                    content=content,
                )
            )
        return pages, tuple(images)

    def _parse_pdf_chunk(self, source_path: Path, page_start: int, page_end: int) -> str:
        source = PdfReader(str(source_path))
        writer = PdfWriter()
        for page_index in range(page_start - 1, page_end):
            writer.add_page(source.pages[page_index])
        work_path = source_path.parent / "work" / f"pages-{page_start:04d}-{page_end:04d}.pdf"
        work_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = work_path.with_suffix(".pdf.tmp")
        try:
            with temporary.open("wb") as output:
                writer.write(output)
            temporary.replace(work_path)
            documents = mineru_reader(
                self.settings,
                timeout=self.settings.paper_mineru_timeout,
            ).load_data(
                work_path,
                extra_info={
                    "source": source_path.name,
                    "source_type": "uploaded_question_paper",
                    "page_start": page_start,
                    "page_end": page_end,
                },
            )
            return render_documents(documents)
        finally:
            temporary.unlink(missing_ok=True)
            work_path.unlink(missing_ok=True)

    @contextmanager
    def _heartbeat(self, job_id: str, token: str) -> Iterator[None]:
        stopped = threading.Event()

        def renew() -> None:
            interval = max(10.0, self.settings.paper_lease_seconds / 3)
            while not stopped.wait(interval):
                try:
                    if not self.jobs.heartbeat(job_id, token):
                        logger.warning("paper_job=%s heartbeat_lost=1", job_id)
                        return
                except Exception:
                    logger.exception("paper_job=%s heartbeat_failed=1", job_id)

        thread = threading.Thread(target=renew, daemon=True, name=f"paper-heartbeat-{job_id}")
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(timeout=1)
