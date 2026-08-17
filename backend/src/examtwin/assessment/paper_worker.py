from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Any, cast

import httpx
import pymupdf
from pypdf import PdfReader, PdfWriter

from examtwin.assessment.agent_run_ledger import PaperAgentRunLedger
from examtwin.assessment.answering_agent.contracts import AgentRunLedger, AgentStep, QuestionImage
from examtwin.assessment.paper_answering import SPLIT_CONTRACT_VERSION, PaperAnswerService
from examtwin.assessment.paper_classification import (
    PAPER_CLASSIFICATION_CONTRACT_VERSION,
    PaperDocumentClassification,
    PaperDocumentClassifier,
    PaperDocumentClassifierFn,
    require_question_paper,
)
from examtwin.assessment.paper_job_repository import LostLeaseError
from examtwin.assessment.paper_job_runtime import PaperJobRuntime
from examtwin.assessment.paper_parsing import (
    ParsedPaperChunk,
    extract_paper_chunk,
    question_has_unresolved_source_placeholder,
)
from examtwin.assessment.paper_vision import (
    VISION_REVIEW_CONTRACT_VERSION,
    PaperVisionReviewer,
    VisionReviewResult,
    format_physical_page_markdown,
    validate_page_classification_records,
    validate_physical_page_markdown,
)
from examtwin.assessment.task_events import PaperJobWakeup, SleepPaperJobWakeup
from examtwin.contracts.papers import PaperQuestionAnswer
from examtwin.knowledge.public import parse_exam_identity
from examtwin.platform.config import Settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import SubjectContext, WorkspaceRepository

logger = logging.getLogger(__name__)

_QUESTION_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
_QUESTION_IMAGE_MIN_AREA = 16_384
_QUESTION_IMAGE_MIN_LONG_EDGE = 160
_QUESTION_IMAGE_URL = re.compile(
    r"/api/v1/papers/jobs/(?P<job_id>[A-Za-z0-9-]+)/question-images/"
    r"(?P<asset>p(?P<page>\d{4})-[0-9a-f]{64}\.(?:bmp|gif|jpeg|jpg|png|webp))"
)
_UPLOADED_ANSWER_HEADING = re.compile(
    r"(?im)^(?:#{1,6}\s*(?:question|q)?\s*|(?:question|q)\s*)"
    r"(?P<number>\d+(?:\s*\([a-z0-9]+\))*)(?:\s*[:.)-]\s*)?"
)
_UPLOADED_ANSWER_NUMBER = re.compile(r"(?im)^(?P<number>\d+(?:\s*\([a-z0-9]+\))*)\s*[.)-]\s+")


def _answer_number(value: str) -> str:
    match = re.match(r"\d+", value.strip())
    return str(int(match.group(0))) if match is not None else value.strip()


def _is_substantive_question_image(content: bytes) -> bool:
    """Reject MinerU's small glyph/option-marker crops while failing open on unknown formats."""

    try:
        pixmap = pymupdf.Pixmap(content)
    except Exception:  # PyMuPDF raises format-specific exception classes across releases.
        return True
    return (
        pixmap.width * pixmap.height >= _QUESTION_IMAGE_MIN_AREA
        and max(pixmap.width, pixmap.height) >= _QUESTION_IMAGE_MIN_LONG_EDGE
    )


def _remove_markdown_image(markdown: str, targets: set[str]) -> str:
    cleaned = markdown
    for target in sorted((item for item in targets if item), key=len, reverse=True):
        cleaned = re.sub(
            rf"!\[[^\]]*\]\(\s*<?{re.escape(target)}>?(?:\s+['\"][^'\"]*['\"])?\s*\)",
            "",
            cleaned,
        )
        cleaned = re.sub(
            rf"<img\b[^>]*\bsrc=['\"]{re.escape(target)}['\"][^>]*>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _question_image_jpeg(content: bytes) -> bytes:
    if content.startswith(b"\xff\xd8"):
        return content
    pixmap = pymupdf.Pixmap(content)
    return pixmap.tobytes("jpeg", jpg_quality=88)


def _split_uploaded_answers(markdown: str) -> dict[str, str]:
    markers = sorted(
        [
            *list(_UPLOADED_ANSWER_HEADING.finditer(markdown)),
            *list(_UPLOADED_ANSWER_NUMBER.finditer(markdown)),
        ],
        key=lambda match: match.start(),
    )
    sections: dict[str, list[str]] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
        answer = markdown[marker.end() : end].strip()
        if not answer:
            continue
        sections.setdefault(_answer_number(marker.group("number")), []).append(answer)
    return {number: "\n\n".join(dict.fromkeys(parts)) for number, parts in sections.items()}


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
        chunk_parser: Callable[[Path, int, int], str | ParsedPaperChunk] | None = None,
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
        with self._heartbeat(job_id, token):
            try:
                self._activate_job_subject(job)
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
                        parsed = self.chunk_parser(
                            source_path,
                            chunk["page_start"],
                            chunk["page_end"],
                        )
                        markdown = (
                            self._persist_chunk_images(
                                job_id,
                                chunk["page_start"],
                                chunk["page_end"],
                                parsed,
                                source_path=source_path,
                            )
                            if isinstance(parsed, ParsedPaperChunk)
                            else parsed
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
                    review_path = markdown_path.with_suffix(".vision.json")
                    reviewed_is_valid = False
                    if reviewed_path.is_file():
                        cached = reviewed_path.read_text(encoding="utf-8")
                        try:
                            review_metadata = json.loads(review_path.read_text(encoding="utf-8"))
                            if (
                                review_metadata.get("contract_version")
                                != VISION_REVIEW_CONTRACT_VERSION
                            ):
                                raise ValueError("旧版视觉检查点需要重新复核")
                            source_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                            if review_metadata.get("source_digest") != source_digest:
                                raise ValueError("视觉检查点输入摘要不一致")
                            validate_page_classification_records(
                                review_metadata.get("page_classifications"),
                                chunk["page_start"],
                                chunk["page_end"],
                                min_confidence=self.settings.paper_vision_min_confidence,
                            )
                            validate_physical_page_markdown(
                                cached,
                                chunk["page_start"],
                                chunk["page_end"],
                            )
                            markdown = cached
                            reviewed_is_valid = True
                        except (OSError, TypeError, ValueError, json.JSONDecodeError):
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
                        ): (chunk, markdown, time.monotonic())
                        for chunk, markdown in pending_reviews
                    }
                    for future in as_completed(futures):
                        chunk, source_markdown, review_started = futures[future]
                        try:
                            review = future.result()
                            markdown = review.markdown
                            validate_physical_page_markdown(
                                markdown,
                                chunk["page_start"],
                                chunk["page_end"],
                            )
                            validate_page_classification_records(
                                [
                                    classification.as_dict()
                                    for classification in review.page_classifications
                                ],
                                chunk["page_start"],
                                chunk["page_end"],
                                min_confidence=self.settings.paper_vision_min_confidence,
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
                                        "contract_version": VISION_REVIEW_CONTRACT_VERSION,
                                        "model": review.model,
                                        "page_start": chunk["page_start"],
                                        "page_end": chunk["page_end"],
                                        "source_digest": hashlib.sha256(
                                            source_markdown.encode("utf-8")
                                        ).hexdigest(),
                                        "confidence": review.confidence,
                                        "repairs": list(review.repairs),
                                        "page_classifications": [
                                            classification.as_dict()
                                            for classification in review.page_classifications
                                        ],
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

    def _uploaded_answer_markdown(self, job: dict[str, Any]) -> str:
        relative_path = str(job.get("answer_source_path") or "")
        suffix = str(job.get("answer_suffix") or "").lower()
        if not relative_path:
            raise ValueError("外部答卷缺少答案文件")
        path = self.jobs.resolve_file(relative_path)
        if suffix in {".md", ".markdown"}:
            markdown = path.read_text(encoding="utf-8-sig")
        elif suffix == ".pdf":
            markdown = "\n\n".join(
                (page.extract_text() or "").strip() for page in PdfReader(path).pages
            )
        else:
            raise ValueError("答案文件格式不受支持")
        if len(markdown.strip()) < 3:
            raise ValueError("答案 PDF 没有可提取文字；当前不支持扫描件或手写答案 OCR")
        return markdown

    def _complete_uploaded_answers(
        self,
        job_id: str,
        token: str,
        pending: list[dict[str, Any]],
        markdown: str,
    ) -> None:
        answers = _split_uploaded_answers(markdown)
        if not answers:
            raise ValueError("答案文件未识别到以 Q1、Question 1 或“1.”开头的题号")
        for item in pending:
            number = _answer_number(str(item["number"]))
            answer = answers.get(number)
            self.jobs.start_question(job_id, token, item["position"])
            if not answer:
                self.jobs.fail_question(
                    job_id,
                    token,
                    item["position"],
                    ValueError(f"答案文件未找到第 {item['number']} 题答案"),
                )
                continue
            self.jobs.complete_question(
                job_id,
                token,
                item["position"],
                PaperQuestionAnswer(
                    number=str(item["number"]),
                    question_markdown=str(item["question_markdown"]),
                    answer_markdown=answer,
                    confidence=1,
                    grounded=False,
                    warnings=["答案来自用户上传文件，未执行自动作答。"],
                ),
            )

    def _answer(self, job: dict[str, Any], token: str) -> None:
        job_id = job["id"]
        pending = [item for item in self.jobs.list_questions(job_id) if item["status"] == "pending"]
        self.jobs.set_stage(job_id, token, "answering")
        if not pending:
            return
        if job.get("answer_mode") == "uploaded":
            self._complete_uploaded_answers(
                job_id,
                token,
                pending,
                self._uploaded_answer_markdown(job),
            )
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
        job_record = getattr(self.jobs, "job_record", None)
        raw_job = job_record(job_id) if callable(job_record) else {}
        job = raw_job if isinstance(raw_job, dict) else {}
        pair_key = (
            job.get("pair_key")
            or parse_exam_identity(Path(filename), "question_paper", self.subject.pack)["pair_key"]
        )
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
        if job.get("source_booklet_document_id"):
            call_options["source_booklet_document_id"] = job["source_booklet_document_id"]
            call_options["source_booklet_checksum"] = job["source_booklet_checksum"]
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
        question_markdown = str(row.get("question_markdown", ""))
        if question_has_unresolved_source_placeholder(question_markdown):
            raise ValueError("历史题目不满足来源完整性契约，请创建替代任务")
        requires_visual = row.get("requires_visual_context")
        if not isinstance(requires_visual, bool):
            raise ValueError("PDF 题目缺少持久化的视觉上下文判定，请创建替代任务")
        if not requires_visual:
            return pages, ()
        if not pages:
            raise ValueError("PDF 题目缺少可信的原卷来源页")
        if len(pages) > self.settings.paper_question_image_max_pages:
            raise ValueError("题目原卷页数超过视觉输入上限")

        embedded_matches = list(_QUESTION_IMAGE_URL.finditer(question_markdown))
        if embedded_matches:
            total_bytes = 0
            embedded_images: list[QuestionImage] = []
            seen_assets: set[str] = set()
            for match in embedded_matches:
                if match.group("job_id") != job_id:
                    raise ValueError("题目图片引用了其他试卷任务")
                image_page = int(match.group("page"))
                if image_page not in pages:
                    raise ValueError("题目图片页码不属于题目可信来源页")
                asset_name = match.group("asset")
                if asset_name in seen_assets:
                    continue
                seen_assets.add(asset_name)
                image_path = self.jobs.question_image(job_id, asset_name)
                content = _question_image_jpeg(image_path.read_bytes())
                total_bytes += len(content)
                if total_bytes > self.settings.paper_question_image_max_total_bytes:
                    raise ValueError("题目图片总大小超过视觉输入上限")
                embedded_images.append(QuestionImage(page_number=image_page, content=content))
            if embedded_images:
                return pages, tuple(embedded_images)

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

    def _persist_chunk_images(
        self,
        job_id: str,
        page_start: int,
        page_end: int,
        chunk: ParsedPaperChunk,
        *,
        source_path: Path | None = None,
    ) -> str:
        page_count = page_end - page_start + 1
        if chunk.page_markdown and len(chunk.page_markdown) <= page_count:
            markdown = format_physical_page_markdown(
                [
                    (
                        page_number,
                        chunk.page_markdown[page_number - page_start]
                        if page_number - page_start < len(chunk.page_markdown)
                        else "",
                    )
                    for page_number in range(page_start, page_end + 1)
                ]
            )
        else:
            markdown = chunk.markdown
        referenced_images: list[tuple[Any, str, list[str]]] = []
        for image in chunk.images:
            name = Path(image.name).name
            suffix = Path(name).suffix.lower()
            if suffix not in _QUESTION_IMAGE_SUFFIXES:
                continue
            image_source_path = image.path.replace("\\", "/").lstrip("/")
            targets = {
                image_source_path,
                image_source_path.removeprefix("./"),
                name,
                f"images/{name}",
                f"./images/{name}",
            }
            referenced = [target for target in targets if target and target in markdown]
            if not referenced:
                # MinerU also emits logos, option markers and decorative crops that are
                # absent from its Markdown. Without a source position in the Markdown we
                # cannot prove that an image belongs to a question, nor where it belongs.
                # Keep only explicitly referenced assets; the vision-review stage remains
                # the source-integrity fallback for genuinely missing visual content.
                continue
            if not _is_substantive_question_image(image.content):
                # MinerU sometimes references tiny option letters, page furniture or
                # isolated glyphs as standalone images. These do not carry enough visual
                # information to justify occupying the question layout.
                markdown = _remove_markdown_image(markdown, targets)
                continue
            referenced_images.append((image, suffix, referenced))

        fallback_page: int | None = None
        unpositioned_count = sum(
            image.page_index is None for image, _suffix, _referenced in referenced_images
        )
        if page_start != page_end and unpositioned_count:
            if source_path is not None:
                source = PdfReader(str(source_path))
                image_pages: list[tuple[int, int]] = []
                for page_number in range(page_start, page_end + 1):
                    image_count = len(list(source.pages[page_number - 1].images))
                    if image_count:
                        image_pages.append((page_number, image_count))
                if len(image_pages) == 1 and image_pages[0][1] == unpositioned_count:
                    fallback_page = image_pages[0][0]
            if fallback_page is None:
                raise ValueError("MinerU 题目图片缺少物理页位置")

        for image, suffix, referenced in referenced_images:
            digest = hashlib.sha256(image.content).hexdigest()
            if image.page_index is None:
                page_number = fallback_page or page_start
            else:
                page_number = page_start + image.page_index
                if page_number < page_start or page_number > page_end:
                    raise ValueError("MinerU 题目图片的物理页位置超出页段")
            asset_name = f"p{page_number:04d}-{digest}{suffix}"
            self.jobs.write_file(
                f"{job_id}/question-images/{asset_name}",
                image.content,
            )
            public_url = f"/api/v1/papers/jobs/{job_id}/question-images/{asset_name}"
            for target in sorted(referenced, key=len, reverse=True):
                markdown = markdown.replace(target, public_url)
        return markdown

    def _parse_pdf_chunk(
        self,
        source_path: Path,
        page_start: int,
        page_end: int,
    ) -> ParsedPaperChunk:
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
            for attempt in range(1, self.settings.paper_mineru_max_attempts + 1):
                try:
                    return extract_paper_chunk(
                        self.settings,
                        work_path,
                        timeout=self.settings.paper_mineru_timeout,
                    )
                except httpx.TransportError as error:
                    if attempt == self.settings.paper_mineru_max_attempts:
                        raise
                    delay = min(
                        self.settings.paper_mineru_retry_delay_seconds * (2 ** (attempt - 1)),
                        30,
                    )
                    logger.warning(
                        "paper_parse pages=%s-%s mineru_transport_retry=%s/%s delay=%.1fs error=%s",
                        page_start,
                        page_end,
                        attempt,
                        self.settings.paper_mineru_max_attempts,
                        delay,
                        type(error).__name__,
                    )
                    time.sleep(delay)
            raise RuntimeError("MinerU transport retry loop exhausted")
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
