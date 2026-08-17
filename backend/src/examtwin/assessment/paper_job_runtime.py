from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from examtwin.assessment.answering_agent.contracts import AgentStep
from examtwin.assessment.paper_answering import SPLIT_CONTRACT_VERSION
from examtwin.assessment.paper_job_repository import PaperJobRepository
from examtwin.assessment.paper_parsing import question_spec_from_item
from examtwin.assessment.paper_sources import PaperSourceStore
from examtwin.contracts.papers import PaperQuestionAnswer
from examtwin.platform.database.session import utcnow


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:1000]


class PaperJobRuntime:
    """Worker-only lease, checkpoint, and artifact boundary for durable paper jobs."""

    def __init__(self, repository: PaperJobRepository, files: PaperSourceStore) -> None:
        self.repository = repository
        self.files = files

    def source_path(self, job: dict[str, Any]) -> Path:
        return self.files.resolve(str(job["source_path"]))

    def resolve_file(self, relative_path: str) -> Path:
        return self.files.resolve(relative_path)

    def write_file(self, relative_path: str, content: bytes | str) -> None:
        self.files.write(relative_path, content)

    def source_page_root(self, job_id: str) -> Path:
        return self.files.resolve(f"{job_id}/source-pages")

    def question_image(self, job_id: str, asset_name: str) -> Path:
        return self.files.question_image(job_id, asset_name)

    def source_file(self, job_id: str) -> tuple[Path, str, str]:
        record = self.repository.source_record(job_id)
        if not record:
            raise LookupError("试卷任务不存在")
        return self.files.source_file(record)

    def job_record(self, job_id: str) -> dict[str, Any]:
        record = self.repository.get(job_id)
        if record is None:
            raise LookupError("试卷任务不存在")
        return record

    def source_page(self, job_id: str, page_number: int) -> Path:
        record = self.repository.source_record(job_id)
        if not record:
            raise LookupError("试卷任务不存在")
        return self.files.source_page(record, job_id, page_number)

    def claim_next(self) -> tuple[dict[str, Any], str] | None:
        claimed = self.repository.claim_next()
        if claimed is not None:
            self.files.extend_retention(str(claimed[0]["id"]))
        return claimed

    def heartbeat(self, job_id: str, token: str) -> bool:
        return self.repository.heartbeat(job_id, token)

    def recover_inflight(self, job_id: str, token: str) -> None:
        self.repository.recover_inflight(job_id, token)

    def set_stage(self, job_id: str, token: str, stage: str) -> None:
        self.repository.set_stage(job_id, token, stage)

    def fail_job(self, job_id: str, token: str, stage: str, error: Exception) -> None:
        self.repository.fail_job(job_id, token, stage, _error_text(error))

    def finish_job(self, job_id: str, token: str) -> None:
        self.repository.finish_job(job_id, token)

    def ensure_chunks(
        self,
        job_id: str,
        token: str,
        total_pages: int,
        chunk_pages: int,
    ) -> None:
        chunks = [
            {
                "chunk_index": chunk_index,
                "page_start": page_start,
                "page_end": min(total_pages, page_start + chunk_pages - 1),
            }
            for chunk_index, page_start in enumerate(range(1, total_pages + 1, chunk_pages))
        ]
        self.repository.ensure_chunks(job_id, token, total_pages, chunks)

    def list_chunks(self, job_id: str) -> list[dict[str, Any]]:
        return self.repository.chunks(job_id)

    def start_chunk(self, job_id: str, token: str, chunk_index: int) -> None:
        self.repository.start_chunk(job_id, token, chunk_index)

    def complete_chunk(
        self,
        job_id: str,
        token: str,
        chunk_index: int,
        markdown_path: str,
    ) -> None:
        self.repository.complete_chunk(job_id, token, chunk_index, markdown_path)

    def fail_chunk(
        self,
        job_id: str,
        token: str,
        chunk_index: int,
        error: Exception,
    ) -> None:
        self.repository.fail_chunk(job_id, token, chunk_index, _error_text(error))

    def store_questions(
        self,
        job_id: str,
        token: str,
        questions: list[dict[str, Any]],
    ) -> None:
        job = self.repository.get(job_id)
        if job is None:
            raise LookupError("试卷任务不存在")
        total_pages = int(job["total_pages"] or 0)
        values: list[dict[str, Any]] = []
        source_digests: set[str] = set()
        for position, item in enumerate(questions):
            raw_codes = item.get("knowledge_codes", [])
            codes = raw_codes if isinstance(raw_codes, list) else []
            raw_pages = item.get("source_pages", [])
            pages: list[int] = []
            if isinstance(raw_pages, list):
                pages = sorted(
                    {
                        int(page)
                        for page in raw_pages
                        if isinstance(page, int)
                        and not isinstance(page, bool)
                        and 0 < page <= total_pages
                    }
                )
            requires_visual = item.get("requires_visual_context")
            if not isinstance(requires_visual, bool):
                raise ValueError("分题结果缺少唯一的视觉上下文判定")
            source_kind = item.get("source_kind")
            if source_kind != "primary":
                raise ValueError("分题结果没有通过主源升格")
            source_digest = str(item.get("source_digest") or "")
            if len(source_digest) != 64 or any(
                character not in "0123456789abcdef" for character in source_digest
            ):
                raise ValueError("分题结果缺少有效的主源摘要")
            source_digests.add(source_digest)
            spec = question_spec_from_item(item)
            values.append(
                {
                    "position": position,
                    "number": str(item.get("number", "?")),
                    "question_markdown": str(item.get("question_markdown", "")).strip(),
                    "source_pages_json": json.dumps(pages),
                    "requires_visual_context": requires_visual,
                    "source_kind": source_kind,
                    "source_digest": source_digest,
                    "knowledge_codes_json": json.dumps(codes, ensure_ascii=False),
                    "requirements_json": spec.model_dump_json(),
                    "status": "pending",
                    "answer_json": None,
                    "attempts": 0,
                    "error": None,
                    "started_at": None,
                    "completed_at": None,
                }
            )
        if len(source_digests) != 1:
            raise ValueError("同一试卷的分题结果必须绑定同一个主源摘要")
        self.repository.store_questions(
            job_id,
            token,
            values,
            split_contract_version=SPLIT_CONTRACT_VERSION,
            split_source_digest=next(iter(source_digests)),
        )

    def list_questions(self, job_id: str) -> list[dict[str, Any]]:
        return self.repository.questions(job_id)

    def start_question(self, job_id: str, token: str, position: int) -> int:
        return self.repository.start_question(job_id, token, position)

    def record_agent_step(
        self,
        job_id: str,
        token: str,
        position: int,
        run_attempt: int,
        step: AgentStep,
    ) -> None:
        self.repository.record_agent_step(
            {
                "job_id": job_id,
                "question_position": position,
                "run_attempt": run_attempt,
                "sequence": step.sequence,
                "phase": step.phase,
                "status": step.status,
                "tool_name": step.tool_name,
                "message": step.message,
                "created_at": utcnow(),
            },
            token,
        )

    def complete_question(
        self,
        job_id: str,
        token: str,
        position: int,
        answer: PaperQuestionAnswer,
    ) -> None:
        self.repository.complete_question(
            job_id,
            token,
            position,
            answer.model_dump_json(),
            json.dumps([point.code for point in answer.knowledge_points]),
        )

    def fail_question(
        self,
        job_id: str,
        token: str,
        position: int,
        error: Exception,
    ) -> None:
        self.repository.fail_question(job_id, token, position, _error_text(error))

    def requeue_question(
        self,
        job_id: str,
        token: str,
        position: int,
        error: Exception,
    ) -> None:
        self.repository.requeue_question(job_id, token, position, _error_text(error))
