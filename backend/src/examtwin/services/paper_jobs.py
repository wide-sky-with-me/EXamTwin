from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

from examtwin.answering_agent.contracts import (
    required_answer_artifacts_are_present,
)
from examtwin.answering_agent.skills import (
    mathematics_source_plot_overlay_mode,
)
from examtwin.config import Settings
from examtwin.persistence.paper_job_repository import PaperJobRepository
from examtwin.persistence.session import utcnow
from examtwin.schemas.papers import (
    AgentStepSummary,
    PaperJobChunk,
    PaperJobCreated,
    PaperJobQuestion,
    PaperJobResponse,
    PaperQuestionAnswer,
)
from examtwin.services.inventory import classify_source, parse_exam_identity
from examtwin.services.model_json import repair_markdown_latex
from examtwin.services.paper_parsing import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_SUFFIXES,
    question_requires_visual_context,
    question_spec_from_item,
)
from examtwin.services.paper_sources import PaperSourceStore
from examtwin.services.subject_context import SubjectContext
from pydantic import ValidationError

ACTIVE_JOB_STATUSES = ("queued", "parsing", "splitting", "answering")
TERMINAL_JOB_STATUSES = ("completed", "partial_failed", "failed")


def _question_source_warnings(question: str) -> list[str]:
    if question_requires_visual_context(question):
        return ["本题依赖图形；请核对题干下方的原卷页图、坐标和阴影区域。"]
    return []


class PaperJobService:
    """Application use cases for paper uploads, status views, retries, and source assets."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        repository: PaperJobRepository,
        files: PaperSourceStore | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.repository = repository
        self.files = files or PaperSourceStore(settings.object_store_root / "paper-jobs")

    def _require_job(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get(job_id)
        if not job:
            raise LookupError("试卷任务不存在")
        try:
            self.subject.require(str(job.get("subject_code") or ""))
        except ValueError as error:
            raise LookupError("试卷任务不属于当前科目上下文") from error
        return job

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
    ) -> PaperJobCreated:
        self.subject.require_paper_capability()
        if not self.subject.knowledge_base_version_ids:
            raise ValueError("整卷作答前必须选择已发布的知识库版本")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("仅支持 Markdown（.md/.markdown）或 PDF 试卷")
        if classify_source(Path(filename)) == "mark_scheme":
            raise ValueError(
                "上传文件被识别为 Mark Scheme（评分标准），请选择 Question Paper（试题）文件"
            )
        resolved_unit_code = (
            unit_code
            or parse_exam_identity(
                Path(filename),
                "question_paper",
                self.subject.pack,
            )["unit_code"]
        )

        job_id = str(uuid4())
        source_rel = f"{job_id}/source{suffix}"
        source_path: Path | None = None
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
            now = utcnow()
            self.repository.create(
                {
                    "id": job_id,
                    "subject_pack_id": self.subject.pack.id,
                    "subject_code": self.subject.subject_code,
                    "filename": Path(filename).name,
                    "suffix": suffix,
                    "unit_code": resolved_unit_code,
                    "knowledge_base_version_ids_json": json.dumps(
                        self.subject.knowledge_base_version_ids, ensure_ascii=False
                    ),
                    "graph_version_id": self.subject.graph_version_id,
                    "source_path": source_rel,
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
                except (TypeError, ValueError, ValidationError):
                    answer_error = "保存的题目结果无法解析"
            questions.append(
                PaperJobQuestion(
                    position=row["position"],
                    status=row["status"],
                    attempts=row["attempts"],
                    number=row["number"],
                    question_markdown=row["question_markdown"],
                    source_pages=source_pages,
                    source_warnings=_question_source_warnings(row["question_markdown"]),
                    answer_requirements=requirements.get("subparts", []),
                    total_marks=requirements.get("total_marks"),
                    answer_markdown=repair_markdown_latex(
                        answer.answer_markdown if answer is not None else ""
                    ),
                    diagrams=answer.diagrams if answer is not None else [],
                    images=answer.images if answer is not None else [],
                    citations=answer.citations if answer is not None else [],
                    knowledge_points=answer.knowledge_points if answer is not None else [],
                    confidence=answer.confidence if answer is not None else 0,
                    grounded=answer.grounded if answer is not None else False,
                    warnings=answer.warnings if answer is not None else [],
                    agent_steps=steps_by_position.get(row["position"], []),
                    error=row["error"] or (answer.error if answer is not None else answer_error),
                )
            )
        return PaperJobResponse(
            job_id=job["id"],
            filename=job["filename"],
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

    def retry(self, job_id: str) -> PaperJobCreated:
        self._require_job(job_id)
        self.repository.retry_job(job_id)
        self.files.extend_retention(job_id)
        return PaperJobCreated(job_id=job_id, status="queued", stage="queued")

    def retry_question(self, job_id: str, position: int) -> PaperJobCreated:
        if position < 0:
            raise ValueError("题目位置不能为负数")
        self._require_job(job_id)
        question = self.repository.retry_candidate(job_id, position)
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
            requires_source_overlay = (
                self.subject.subject_code == "9660"
                and mathematics_source_plot_overlay_mode(question["question_markdown"]) is not None
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
