from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from pydantic import ValidationError

from examtwin.assessment.answering_agent.contracts import (
    required_answer_artifacts_are_present,
)
from examtwin.assessment.answering_agent.finalization import compact_cited_evidence
from examtwin.assessment.paper_answering import SPLIT_CONTRACT_VERSION
from examtwin.assessment.paper_export import inspect_answer_layout
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_parsing import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_SUFFIXES,
    question_has_unresolved_source_placeholder,
    question_spec_from_item,
)
from examtwin.assessment.paper_sources import PaperSourceStore
from examtwin.contracts.paper_export import PaperExportLayout
from examtwin.contracts.papers import (
    AgentStepSummary,
    PaperAnswerMode,
    PaperJobChunk,
    PaperJobCreated,
    PaperJobFilterStatus,
    PaperJobListResponse,
    PaperJobQuestion,
    PaperJobResponse,
    PaperJobSummary,
    PaperQuestionAnswer,
)
from examtwin.contracts.strategy import StrategyPlan, StrategyRequest
from examtwin.knowledge.public import CorpusRepository, classify_source, parse_exam_identity
from examtwin.platform.config import Settings
from examtwin.platform.database.session import utcnow
from examtwin.platform.model_json import repair_markdown_latex
from examtwin.subjects.public import SubjectContext

ACTIVE_JOB_STATUSES = ("queued", "parsing", "vision_review", "splitting", "answering")
TERMINAL_JOB_STATUSES = ("completed", "partial_failed", "failed")


def _question_source_warnings(
    question: str,
    requires_visual_context: bool | None,
    source_integrity_status: str,
) -> list[str]:
    if source_integrity_status != "verified":
        return ["该题来自旧版未验证分题契约；请创建替代任务后再使用。"]
    if question_has_unresolved_source_placeholder(question):
        return ["题干提取不完整；该任务不满足来源完整性契约。"]
    if requires_visual_context:
        return ["本题依赖图形；请核对题干下方的原卷页图、坐标和阴影区域。"]
    return []


def _requires_replacement(job: Mapping[str, Any]) -> bool:
    integrity = str(job.get("source_integrity_status") or "")
    return integrity in {"legacy_unverified", "replacement_queued"} or (
        integrity == "verified" and job.get("split_contract_version") != SPLIT_CONTRACT_VERSION
    )


class PaperJobService:
    """Application use cases for paper uploads, status views, retries, and source assets."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        repository: PaperJobRepository,
        files: PaperSourceStore | None = None,
        documents: CorpusRepository | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.repository = repository
        self.files = files or PaperSourceStore(settings.object_store_root / "paper-jobs")
        self.documents = documents

    def _require_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get(job_id)
        if not job:
            raise LookupError("试卷任务不存在")
        try:
            self.subject.require(str(job.get("subject_code") or ""))
        except ValueError as error:
            raise LookupError("试卷任务不属于当前科目上下文") from error
        return job

    def list_jobs(
        self,
        *,
        status: PaperJobFilterStatus | None = None,
        answer_mode: PaperAnswerMode | None = None,
        unit_code: str | None = None,
        query: str | None = None,
        paper_unit_id: str | None = None,
        created_after: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> PaperJobListResponse:
        statuses = (
            ACTIVE_JOB_STATUSES if status == "active" else (status,) if status is not None else None
        )
        rows, total = self.repository.list_for_subject(
            self.subject.subject_code,
            statuses=statuses,
            answer_mode=answer_mode,
            unit_code=unit_code,
            query=query,
            paper_unit_id=paper_unit_id,
            created_after=created_after,
            limit=limit,
            offset=offset,
        )
        job_ids = [str(row["id"]) for row in rows]
        replacement_ids = self.repository.replacement_ids(job_ids)
        grading_progress = self.repository.grading_progress(job_ids)
        return PaperJobListResponse(
            items=[
                PaperJobSummary(
                    job_id=row["id"],
                    filename=row["filename"],
                    display_name=row.get("display_name"),
                    answer_mode=row.get("answer_mode") or "generated",
                    pair_key=row.get("pair_key"),
                    paper_unit_id=row.get("paper_unit_id"),
                    question_paper_document_id=row.get("question_paper_document_id"),
                    source_booklet_document_id=row.get("source_booklet_document_id"),
                    source_booklet_checksum=row.get("source_booklet_checksum"),
                    source_booklet_filename=row.get("source_booklet_filename"),
                    unit_code=row["unit_code"],
                    status=row["status"],
                    stage=row["stage"],
                    total_questions=row["total_questions"],
                    completed_questions=row["completed_questions"],
                    failed_questions=row["failed_questions"],
                    source_integrity_status=row["source_integrity_status"],
                    split_contract_version=row["split_contract_version"],
                    replacement_for_job_id=row["replacement_for_job_id"],
                    replaced_by_job_id=replacement_ids.get(str(row["id"])),
                    graded_questions=grading_progress.get(str(row["id"]), (0, 0))[0],
                    pending_review_count=grading_progress.get(str(row["id"]), (0, 0))[1],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )

    def delete_jobs(self, job_ids: Sequence[str]) -> int:
        unique_ids = tuple(dict.fromkeys(job_ids))
        if not unique_ids:
            raise ValueError("至少选择一条试卷作答记录")
        if len(unique_ids) != len(job_ids):
            raise ValueError("批量删除不能包含重复的试卷任务")
        return self.repository.delete_releasable(
            unique_ids,
            self.subject.subject_code,
            terminal_statuses=TERMINAL_JOB_STATUSES,
        )

    def delete_job(self, job_id: str) -> None:
        self.delete_jobs((job_id,))

    def rename_job(self, job_id: str, display_name: str) -> PaperJobResponse:
        normalized = display_name.strip()
        if not normalized:
            raise ValueError("显示名称不能为空")
        if len(normalized) > 200:
            raise ValueError("显示名称不能超过 200 个字符")
        self._require_job(job_id)
        self.repository.rename(
            job_id,
            subject_code=self.subject.subject_code,
            display_name=normalized,
        )
        return self.get_job(job_id)

    def create_job(
        self,
        filename: str,
        content: bytes,
        *,
        unit_code: str | None = None,
    ) -> PaperJobCreated:
        return self.create_job_from_stream(
            filename,
            BytesIO(content),
            unit_code=unit_code,
        )

    def create_job_from_stream(
        self,
        filename: str,
        stream: BinaryIO,
        *,
        unit_code: str | None = None,
        answer_filename: str | None = None,
        answer_stream: BinaryIO | None = None,
        source_booklet: Mapping[str, Any] | None = None,
        paper_unit_id: str | None = None,
        question_paper_document_id: str | None = None,
        strategy: StrategyRequest | None = None,
    ) -> PaperJobCreated:
        self.subject.require_paper_capability()
        if strategy is not None and answer_stream is not None:
            raise ValueError("目标分数策略仅适用于 AI 作答")
        if not self.subject.knowledge_base_version_ids:
            raise ValueError("整卷作答前必须选择已发布的知识库版本")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("仅支持 Markdown（.md/.markdown）或 PDF 试卷")
        if (answer_filename is None) != (answer_stream is None):
            raise ValueError("上传外部答案时必须同时提供答案文件名和内容")
        if (paper_unit_id is None) != (question_paper_document_id is None):
            raise ValueError("受管试卷作答必须同时提供试卷单元和 Question Paper 文档")
        answer_suffix = Path(answer_filename).suffix.lower() if answer_filename else None
        if answer_suffix is not None and answer_suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("答案文件仅支持 Markdown（.md/.markdown）或 PDF")
        if classify_source(Path(filename)) == "mark_scheme":
            raise ValueError(
                "上传文件被识别为 Mark Scheme（评分标准），请选择 Question Paper（试题）文件"
            )
        paper_identity = parse_exam_identity(Path(filename), "question_paper", self.subject.pack)
        pair_key = str(paper_identity.get("pair_key") or "") or None
        if (
            self.subject.package.manifest.answering.requires_source_booklet
            and source_booklet is None
        ):
            raise ValueError("该科目整卷作答必须上传与试卷完全配对的 Source Booklet")
        if source_booklet is not None:
            booklet_pair = str(source_booklet.get("pair_key") or "")
            booklet_checksum = str(source_booklet.get("checksum") or "")
            if source_booklet.get("subject_code") != self.subject.subject_code:
                raise ValueError("Source Booklet 不属于当前科目")
            if source_booklet.get("source_type") != "insert":
                raise ValueError("配套材料必须识别为 Source Booklet 或 Insert")
            if not pair_key or paper_identity.get("identity_status") != "complete":
                raise ValueError("Question Paper 缺少完整考试身份，无法验证 Source Booklet 配对")
            if source_booklet.get("identity_status") != "complete" or not booklet_pair:
                raise ValueError("Source Booklet 缺少完整考试身份")
            if pair_key != booklet_pair:
                raise ValueError("Source Booklet 与试卷的年份、考季或 Unit 不匹配")
            if (
                source_booklet.get("status") != "converted"
                or not booklet_checksum
                or source_booklet.get("converted_source_checksum") != booklet_checksum
            ):
                raise ValueError("Source Booklet 尚未按当前文件版本完成转换")
        resolved_unit_code = unit_code or paper_identity["unit_code"]

        job_id = str(uuid4())
        source_rel = f"{job_id}/source{suffix}"
        answer_source_rel = (
            f"{job_id}/answer-source{answer_suffix}" if answer_suffix is not None else None
        )
        source_path: Path | None = None
        answer_source_path: Path | None = None
        try:
            source_path, _size = self.files.write_upload(
                source_rel,
                stream,
                max_bytes=MAX_UPLOAD_BYTES,
            )
            if suffix in {".md", ".markdown"}:
                try:
                    with source_path.open("r", encoding="utf-8-sig") as markdown:
                        while markdown.read(1024 * 1024):
                            pass
                except UnicodeDecodeError as error:
                    raise ValueError("Markdown 必须使用 UTF-8 编码") from error
            if answer_source_rel is not None and answer_stream is not None:
                answer_source_path, _answer_size = self.files.write_upload(
                    answer_source_rel,
                    answer_stream,
                    max_bytes=MAX_UPLOAD_BYTES,
                )
                if answer_suffix in {".md", ".markdown"}:
                    try:
                        answer_source_path.read_text(encoding="utf-8-sig")
                    except UnicodeDecodeError as error:
                        raise ValueError("答案 Markdown 必须使用 UTF-8 编码") from error
            now = utcnow()
            self.repository.create(
                {
                    "id": job_id,
                    "subject_pack_id": self.subject.pack.id,
                    "subject_code": self.subject.subject_code,
                    "filename": Path(filename).name,
                    "suffix": suffix,
                    "answer_mode": "uploaded" if answer_source_rel else "generated",
                    "strategy_request_json": strategy.model_dump_json() if strategy else None,
                    "answer_filename": Path(answer_filename).name if answer_filename else None,
                    "answer_suffix": answer_suffix,
                    "answer_source_path": answer_source_rel,
                    "pair_key": pair_key,
                    "paper_unit_id": paper_unit_id,
                    "question_paper_document_id": question_paper_document_id,
                    "source_booklet_document_id": (
                        str(source_booklet["id"]) if source_booklet is not None else None
                    ),
                    "source_booklet_checksum": (
                        str(source_booklet["checksum"]) if source_booklet is not None else None
                    ),
                    "source_booklet_filename": (
                        str(source_booklet.get("filename") or "")
                        if source_booklet is not None
                        else None
                    ),
                    "unit_code": resolved_unit_code,
                    "knowledge_base_version_ids_json": json.dumps(
                        self.subject.knowledge_base_version_ids, ensure_ascii=False
                    ),
                    "graph_version_id": self.subject.graph_version_id,
                    "source_path": source_rel,
                    "source_integrity_status": "pending",
                    "split_contract_version": None,
                    "split_source_digest": None,
                    "replacement_for_job_id": None,
                    "status": "queued",
                    "stage": "queued",
                    "total_pages": 0,
                    "parsed_pages": 0,
                    "total_questions": 0,
                    "completed_questions": 0,
                    "failed_questions": 0,
                    "error": None,
                    "lease_token": None,
                    "lease_expires_at": None,
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "completed_at": None,
                }
            )
        except Exception:
            if source_path is not None:
                self.files.remove(source_rel)
            if answer_source_rel is not None and answer_source_path is not None:
                self.files.remove(answer_source_rel)
            raise
        return PaperJobCreated(job_id=job_id, status="queued", stage="queued")

    def get_job(self, job_id: str) -> PaperJobResponse:
        job = self._require_job(job_id)
        chunk_rows = self.repository.chunks(job_id)
        rows = self.repository.questions(job_id)
        step_rows = self.repository.steps(job_id)
        steps_by_position: dict[int, list[AgentStepSummary]] = {}
        for step in step_rows:
            steps_by_position.setdefault(step["question_position"], []).append(
                AgentStepSummary(
                    run_attempt=step["run_attempt"],
                    sequence=step["sequence"],
                    phase=step["phase"],
                    status=step["status"],
                    tool_name=step["tool_name"],
                    message=step["message"],
                    created_at=str(step["created_at"]),
                )
            )
        questions: list[PaperJobQuestion] = []
        for row in rows:
            answer: PaperQuestionAnswer | None = None
            display_answer_markdown = ""
            display_citations = []
            answer_error: str | None = None
            source_pages: list[int] = []
            requirements: dict[str, Any] = {}
            try:
                raw_pages = json.loads(row["source_pages_json"] or "[]")
                if isinstance(raw_pages, list):
                    source_pages = [
                        int(page)
                        for page in raw_pages
                        if isinstance(page, int) and not isinstance(page, bool) and page > 0
                    ]
            except (TypeError, ValueError, json.JSONDecodeError):
                source_pages = []
            try:
                raw_requirements = json.loads(row["requirements_json"] or "{}")
                if isinstance(raw_requirements, dict):
                    requirements = raw_requirements
            except (TypeError, json.JSONDecodeError):
                requirements = {}
            if row["status"] == "completed" and row["answer_json"]:
                try:
                    answer = PaperQuestionAnswer.model_validate_json(row["answer_json"])
                    display_answer_markdown, compact_citations = compact_cited_evidence(
                        answer.answer_markdown,
                        answer.citations,
                    )
                    display_citations = list(compact_citations)
                except (TypeError, ValueError, ValidationError):
                    answer_error = "保存的题目结果无法解析"
            questions.append(
                PaperJobQuestion(
                    skipped_by_strategy=answer.skipped_by_strategy if answer is not None else False,
                    position=row["position"],
                    status=row["status"],
                    attempts=row["attempts"],
                    number=row["number"],
                    question_markdown=row["question_markdown"],
                    source_pages=source_pages,
                    source_warnings=_question_source_warnings(
                        row["question_markdown"],
                        row["requires_visual_context"],
                        job["source_integrity_status"],
                    ),
                    source_kind=row["source_kind"],
                    source_digest=row["source_digest"],
                    requires_visual_context=row["requires_visual_context"],
                    answer_requirements=requirements.get("subparts", []),
                    total_marks=requirements.get("total_marks"),
                    answer_markdown=repair_markdown_latex(display_answer_markdown),
                    diagrams=answer.diagrams if answer is not None else [],
                    images=answer.images if answer is not None else [],
                    citations=display_citations,
                    knowledge_points=answer.knowledge_points if answer is not None else [],
                    confidence=answer.confidence if answer is not None else 0,
                    grounded=answer.grounded if answer is not None else False,
                    warnings=answer.warnings if answer is not None else [],
                    agent_steps=steps_by_position.get(row["position"], []),
                    error=row["error"] or (answer.error if answer is not None else answer_error),
                )
            )
        return PaperJobResponse(
            strategy_request=(
                StrategyRequest.model_validate_json(job["strategy_request_json"])
                if job.get("strategy_request_json")
                else None
            ),
            strategy_plan=(
                StrategyPlan.model_validate_json(job["strategy_plan_json"])
                if job.get("strategy_plan_json")
                else None
            ),
            job_id=job["id"],
            filename=job["filename"],
            display_name=job.get("display_name"),
            answer_mode=job.get("answer_mode") or "generated",
            pair_key=job.get("pair_key"),
            paper_unit_id=job.get("paper_unit_id"),
            question_paper_document_id=job.get("question_paper_document_id"),
            source_booklet_document_id=job.get("source_booklet_document_id"),
            source_booklet_checksum=job.get("source_booklet_checksum"),
            source_booklet_filename=job.get("source_booklet_filename"),
            subject_pack_id=job["subject_pack_id"],
            subject_code=job["subject_code"],
            unit_code=job["unit_code"],
            knowledge_base_version_ids=json.loads(
                job.get("knowledge_base_version_ids_json") or "[]"
            ),
            graph_version_id=job.get("graph_version_id"),
            status=job["status"],
            stage=job["stage"],
            total_pages=job["total_pages"],
            parsed_pages=job["parsed_pages"],
            total_questions=job["total_questions"],
            completed_questions=job["completed_questions"],
            failed_questions=job["failed_questions"],
            error=job["error"],
            source_integrity_status=job["source_integrity_status"],
            split_contract_version=job["split_contract_version"],
            split_source_digest=job["split_source_digest"],
            replacement_for_job_id=job["replacement_for_job_id"],
            replaced_by_job_id=self.repository.replacement_id(job_id),
            created_at=str(job["created_at"]),
            updated_at=str(job["updated_at"]),
            chunks=[
                PaperJobChunk(
                    chunk_index=row["chunk_index"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    status=row["status"],
                    attempts=row["attempts"],
                    error=row["error"],
                )
                for row in chunk_rows
            ],
            questions=questions,
        )

    def source_file(self, job_id: str) -> tuple[Path, str, str]:
        self._require_job(job_id)
        job = self.repository.source_record(job_id)
        if not job:
            raise LookupError("试卷任务不存在")
        return self.files.source_file(job)

    def source_page(self, job_id: str, page_number: int) -> Path:
        self._require_job(job_id)
        job = self.repository.source_record(job_id)
        if not job:
            raise LookupError("试卷任务不存在")
        return self.files.source_page(job, job_id, page_number)

    def answer_pdf_layout(self, job_id: str) -> PaperExportLayout:
        snapshot = self.get_job(job_id)
        if snapshot.status not in TERMINAL_JOB_STATUSES:
            raise ValueError("请在作答任务结束后导出 PDF")
        if snapshot.source_integrity_status != "verified":
            raise ValueError("请先完成原卷来源核对后再导出 PDF")
        source, _filename, suffix = self.source_file(job_id)
        if suffix != ".pdf":
            raise ValueError("原卷作答导出仅支持 PDF 试卷")
        if not any(q.status == "completed" and q.answer_markdown for q in snapshot.questions):
            raise ValueError("当前没有可导出的已完成答案")
        return inspect_answer_layout(source, snapshot.questions)

    def question_image(self, job_id: str, asset_name: str) -> Path:
        self._require_job(job_id)
        return self.files.question_image(job_id, asset_name)

    def retry(self, job_id: str) -> PaperJobCreated:
        job = self._require_job(job_id)
        if _requires_replacement(job):
            raise ValueError("旧版来源完整性契约的任务不能原地重试，请创建替代任务")
        self.repository.retry_job(job_id)
        self.files.extend_retention(job_id)
        return PaperJobCreated(job_id=job_id, status="queued", stage="queued")

    def create_replacement(self, job_id: str) -> PaperJobCreated:
        job = self._require_job(job_id)
        if job["status"] not in TERMINAL_JOB_STATUSES:
            raise ValueError("只有已结束的试卷任务可以创建替代任务")
        if not _requires_replacement(job) and job["source_integrity_status"] == "verified":
            raise ValueError("该试卷任务已通过当前来源完整性契约")
        existing = self.repository.replacement_id(job_id)
        if existing is not None:
            raise ValueError(f"该试卷已有替代任务：{existing}")
        source_booklet: Mapping[str, Any] | None = None
        source_booklet_id = str(job.get("source_booklet_document_id") or "")
        if source_booklet_id:
            if self.documents is None:
                raise RuntimeError("替代任务缺少受管资料仓库")
            source_booklet = self.documents.get_active(source_booklet_id)
            if source_booklet is None:
                raise ValueError("原任务配套的 Source Booklet 已删除或不可用")
        source_path, filename, _suffix = self.source_file(job_id)
        with ExitStack() as stack:
            source = stack.enter_context(source_path.open("rb"))
            answer_stream = None
            answer_filename = None
            if job.get("answer_mode") == "uploaded":
                answer_source = str(job.get("answer_source_path") or "")
                answer_filename = str(job.get("answer_filename") or "")
                if not answer_source or not answer_filename:
                    raise ValueError("原任务缺少外部答案文件，无法创建替代任务")
                try:
                    answer_stream = stack.enter_context(
                        self.files.resolve(answer_source).open("rb")
                    )
                except (LookupError, FileNotFoundError) as error:
                    raise ValueError("原任务外部答案文件不可用，无法创建替代任务") from error
            replacement = self.create_job_from_stream(
                filename,
                source,
                unit_code=job["unit_code"],
                source_booklet=source_booklet,
                paper_unit_id=job.get("paper_unit_id"),
                question_paper_document_id=job.get("question_paper_document_id"),
                answer_filename=answer_filename,
                answer_stream=answer_stream,
                strategy=(
                    StrategyRequest.model_validate_json(job["strategy_request_json"])
                    if job.get("strategy_request_json")
                    else None
                ),
            )
        self.repository.link_replacement(job_id, replacement.job_id)
        return replacement

    def retry_question(self, job_id: str, position: int) -> PaperJobCreated:
        if position < 0:
            raise ValueError("题目位置不能为负数")
        job = self._require_job(job_id)
        if _requires_replacement(job):
            raise ValueError("旧版来源完整性契约的任务不能原地重试，请创建替代任务")
        question = self.repository.retry_candidate(job_id, position)
        if job.get("strategy_plan_json") and question["status"] == "completed":
            raise ValueError("已完成的策略答卷不可单题重做；请保留首次结果并新建策略任务")
        if question["status"] == "completed":
            try:
                requirements = json.loads(question["requirements_json"] or "{}")
            except json.JSONDecodeError:
                requirements = {}
            spec = question_spec_from_item(
                {
                    "answer_requirements": requirements.get("subparts", []),
                    "total_marks": requirements.get("total_marks"),
                }
            )
            required_tools = spec.required_tool_names
            if not required_tools:
                skill = self.subject.package.require_skill()
                fallback = skill.required_visual_tool(question["question_markdown"])
                required_tools = () if fallback is None else (fallback,)
            try:
                answer = PaperQuestionAnswer.model_validate_json(question["answer_json"] or "{}")
            except ValueError:
                answer = None
            skill = self.subject.package.require_skill()
            requires_source_overlay = (
                skill.source_plot_overlay_mode(question["question_markdown"]) is not None
            )
            source_overlay_present = answer is not None and any(
                diagram.tool_name == "math_plot" and diagram.source is not None
                for diagram in answer.diagrams
            )
            if (
                answer is not None
                and required_answer_artifacts_are_present(
                    answer.diagrams,
                    answer.images,
                    required_tools,
                )
                and (not requires_source_overlay or source_overlay_present)
            ):
                raise ValueError("已完成题目的答案图产物完整，无需重试")
            if not required_tools:
                raise ValueError("已完成题目的答案图产物完整，无需重试")
        elif question["status"] != "failed":
            raise ValueError("只有失败或答案图产物缺失的题目可以单独重试")

        self.repository.queue_question_retry(
            job_id,
            position,
            expected_status=str(question["status"]),
            expected_attempts=int(question["attempts"]),
            expected_answer_json=question.get("answer_json"),
        )
        self.files.extend_retention(job_id)
        return PaperJobCreated(job_id=job_id, status="queued", stage="queued")
