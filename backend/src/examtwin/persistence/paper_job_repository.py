from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import (
    PaperAgentStepModel,
    PaperJobChunkModel,
    PaperJobModel,
    PaperJobQuestionModel,
)
from examtwin.persistence.results import affected_rows
from examtwin.persistence.session import utcnow


class LostLeaseError(RuntimeError):
    pass


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class PaperJobRepository:
    """Own durable paper-job state, leases, checkpoints, and transitions."""

    def __init__(self, sessions: sessionmaker[Session], *, lease_seconds: int) -> None:
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    def create(self, values: Mapping[str, Any]) -> None:
        with self.sessions.begin() as session:
            session.add(PaperJobModel(**dict(values)))

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(PaperJobModel, job_id)
        return None if row is None else _row_dict(row)

    def source_record(self, job_id: str) -> dict[str, Any] | None:
        statement = select(
            PaperJobModel.filename,
            PaperJobModel.suffix,
            PaperJobModel.source_path,
        ).where(PaperJobModel.id == job_id)
        with self.sessions() as session:
            row = session.execute(statement).mappings().one_or_none()
        return None if row is None else dict(row)

    def chunks(self, job_id: str) -> list[dict[str, Any]]:
        statement = (
            select(PaperJobChunkModel)
            .where(PaperJobChunkModel.job_id == job_id)
            .order_by(PaperJobChunkModel.chunk_index)
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_row_dict(row) for row in rows]

    def questions(self, job_id: str) -> list[dict[str, Any]]:
        statement = (
            select(PaperJobQuestionModel)
            .where(PaperJobQuestionModel.job_id == job_id)
            .order_by(PaperJobQuestionModel.position)
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_row_dict(row) for row in rows]

    def steps(self, job_id: str) -> list[dict[str, Any]]:
        statement = (
            select(PaperAgentStepModel)
            .where(PaperAgentStepModel.job_id == job_id)
            .order_by(
                PaperAgentStepModel.question_position,
                PaperAgentStepModel.run_attempt,
                PaperAgentStepModel.sequence,
            )
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_row_dict(row) for row in rows]

    def claim_next(self) -> tuple[dict[str, Any], str] | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.lease_seconds)
        statement = (
            select(PaperJobModel)
            .where(
                PaperJobModel.status.in_(("queued", "parsing", "splitting", "answering")),
                (PaperJobModel.lease_token.is_(None) | (PaperJobModel.lease_expires_at < now)),
            )
            .order_by(PaperJobModel.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        with self.sessions.begin() as session:
            row = session.scalar(statement)
            if row is None:
                return None
            token = uuid4().hex
            row.lease_token = token
            row.lease_expires_at = expires
            row.started_at = row.started_at or now
            row.updated_at = now
            result = _row_dict(row)
        return result, token

    def heartbeat(self, job_id: str, token: str) -> bool:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            result = session.execute(
                update(PaperJobModel)
                .where(PaperJobModel.id == job_id, PaperJobModel.lease_token == token)
                .values(
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    updated_at=now,
                )
            )
        return affected_rows(result) == 1

    def recover_inflight(self, job_id: str, token: str) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            session.execute(
                update(PaperJobChunkModel)
                .where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.status == "parsing",
                )
                .values(status="pending")
            )
            session.execute(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.status == "answering",
                )
                .values(status="pending")
            )

    def set_stage(self, job_id: str, token: str, stage: str) -> None:
        self._leased_job_update(
            job_id,
            token,
            status=stage,
            stage=stage,
            error=None,
            updated_at=utcnow(),
        )

    def fail_job(self, job_id: str, token: str, stage: str, error: str) -> None:
        self._leased_job_update(
            job_id,
            token,
            status="failed",
            stage=stage,
            error=error,
            lease_token=None,
            lease_expires_at=None,
            updated_at=utcnow(),
        )

    def finish_job(self, job_id: str, token: str) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            total, completed, failed = self._question_counts(session, job_id)
            result = session.execute(
                update(PaperJobModel)
                .where(PaperJobModel.id == job_id, PaperJobModel.lease_token == token)
                .values(
                    status="partial_failed" if failed else "completed",
                    stage="completed",
                    total_questions=total,
                    completed_questions=completed,
                    failed_questions=failed,
                    error=None,
                    lease_token=None,
                    lease_expires_at=None,
                    completed_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            if affected_rows(result) != 1:
                raise LostLeaseError(f"paper job {job_id} lease is no longer valid")

    def retry_job(self, job_id: str) -> None:
        with self.sessions.begin() as session:
            job = session.scalar(
                select(PaperJobModel).where(PaperJobModel.id == job_id).with_for_update()
            )
            if job is None:
                raise LookupError("试卷任务不存在")
            if job.status not in {"failed", "partial_failed"}:
                raise ValueError("只有失败或部分失败的任务可以重试")
            session.execute(
                update(PaperJobChunkModel)
                .where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.status == "failed",
                )
                .values(status="pending", error=None)
            )
            session.execute(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.status == "failed",
                )
                .values(status="pending", error=None)
            )
            job.status = "queued"
            job.stage = "queued"
            job.error = None
            job.lease_token = None
            job.lease_expires_at = None
            job.completed_at = None
            job.failed_questions = 0
            job.updated_at = utcnow()

    def retry_candidate(self, job_id: str, position: int) -> dict[str, Any]:
        with self.sessions() as session:
            job = session.get(PaperJobModel, job_id)
            if job is None:
                raise LookupError("试卷任务不存在")
            if job.status not in {"completed", "partial_failed"} or job.stage != "completed":
                raise ValueError("进行中的试卷任务不能单独重试题目")
            if job.lease_token is not None:
                raise ValueError("仍被 Worker 持有的试卷任务不能单独重试题目")
            question = session.scalar(
                select(PaperJobQuestionModel).where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.position == position,
                )
            )
        if question is None:
            raise LookupError("试卷题目不存在")
        return _row_dict(question)

    def queue_question_retry(
        self,
        job_id: str,
        position: int,
        *,
        expected_status: str,
        expected_attempts: int,
        expected_answer_json: str | None,
    ) -> None:
        with self.sessions.begin() as session:
            job = session.scalar(
                select(PaperJobModel).where(PaperJobModel.id == job_id).with_for_update()
            )
            if job is None:
                raise LookupError("试卷任务不存在")
            if job.status not in {"completed", "partial_failed"} or job.stage != "completed":
                raise ValueError("进行中的试卷任务不能单独重试题目")
            if job.lease_token is not None:
                raise ValueError("仍被 Worker 持有的试卷任务不能单独重试题目")
            answer_is_unchanged = (
                PaperJobQuestionModel.answer_json.is_(None)
                if expected_answer_json is None
                else PaperJobQuestionModel.answer_json == expected_answer_json
            )
            result = session.execute(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.position == position,
                    PaperJobQuestionModel.status == expected_status,
                    PaperJobQuestionModel.attempts == expected_attempts,
                    answer_is_unchanged,
                )
                .values(
                    status="pending",
                    error=None,
                    started_at=None,
                    completed_at=None,
                )
            )
            if affected_rows(result) != 1:
                exists = session.scalar(
                    select(PaperJobQuestionModel.id).where(
                        PaperJobQuestionModel.job_id == job_id,
                        PaperJobQuestionModel.position == position,
                    )
                )
                if exists is None:
                    raise LookupError("试卷题目不存在")
                raise ValueError("题目状态已变化，请刷新后重试")
            total, completed, failed = self._question_counts(session, job_id)
            job.status = "queued"
            job.stage = "queued"
            job.total_questions = total
            job.completed_questions = completed
            job.failed_questions = failed
            job.error = None
            job.completed_at = None
            job.updated_at = utcnow()

    def ensure_chunks(
        self,
        job_id: str,
        token: str,
        total_pages: int,
        chunks: Sequence[Mapping[str, int]],
    ) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            for chunk in chunks:
                statement = insert(PaperJobChunkModel).values(
                    job_id=job_id,
                    status="pending",
                    **dict(chunk),
                )
                session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=[
                            PaperJobChunkModel.job_id,
                            PaperJobChunkModel.chunk_index,
                        ]
                    )
                )
            self._update_leased_job(session, job_id, token, total_pages=total_pages)

    def start_chunk(self, job_id: str, token: str, chunk_index: int) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            session.execute(
                update(PaperJobChunkModel)
                .where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.chunk_index == chunk_index,
                    PaperJobChunkModel.status.in_(("pending", "failed")),
                )
                .values(
                    status="parsing",
                    attempts=PaperJobChunkModel.attempts + 1,
                    error=None,
                    started_at=utcnow(),
                )
            )

    def complete_chunk(
        self,
        job_id: str,
        token: str,
        chunk_index: int,
        markdown_path: str,
    ) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            session.execute(
                update(PaperJobChunkModel)
                .where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.chunk_index == chunk_index,
                )
                .values(
                    status="completed",
                    markdown_path=markdown_path,
                    error=None,
                    completed_at=utcnow(),
                )
            )
            parsed_pages = session.scalar(
                select(
                    func.coalesce(
                        func.sum(PaperJobChunkModel.page_end - PaperJobChunkModel.page_start + 1),
                        0,
                    )
                ).where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.status == "completed",
                )
            )
            self._update_leased_job(
                session,
                job_id,
                token,
                parsed_pages=int(parsed_pages or 0),
            )

    def fail_chunk(
        self,
        job_id: str,
        token: str,
        chunk_index: int,
        error: str,
    ) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            session.execute(
                update(PaperJobChunkModel)
                .where(
                    PaperJobChunkModel.job_id == job_id,
                    PaperJobChunkModel.chunk_index == chunk_index,
                )
                .values(status="failed", error=error, completed_at=utcnow())
            )

    def store_questions(
        self,
        job_id: str,
        token: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            existing = session.scalar(
                select(func.count())
                .select_from(PaperJobQuestionModel)
                .where(PaperJobQuestionModel.job_id == job_id)
            )
            if existing:
                return
            session.add_all(
                [PaperJobQuestionModel(job_id=job_id, **dict(values)) for values in questions]
            )
            self._update_leased_job(
                session,
                job_id,
                token,
                total_questions=len(questions),
            )

    def start_question(self, job_id: str, token: str, position: int) -> int:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            attempts = session.scalar(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.position == position,
                    PaperJobQuestionModel.status == "pending",
                )
                .values(
                    status="answering",
                    attempts=PaperJobQuestionModel.attempts + 1,
                    error=None,
                    started_at=utcnow(),
                )
                .returning(PaperJobQuestionModel.attempts)
            )
            if attempts is None:
                raise RuntimeError(f"question {position} could not enter answering state")
        return int(attempts)

    def record_agent_step(self, values: Mapping[str, Any], token: str) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, str(values["job_id"]), token)
            statement = insert(PaperAgentStepModel).values(**dict(values))
            session.execute(
                statement.on_conflict_do_nothing(
                    index_elements=[
                        PaperAgentStepModel.job_id,
                        PaperAgentStepModel.question_position,
                        PaperAgentStepModel.run_attempt,
                        PaperAgentStepModel.sequence,
                    ]
                )
            )

    def complete_question(
        self,
        job_id: str,
        token: str,
        position: int,
        answer_json: str,
    ) -> None:
        self._finish_question(
            job_id,
            token,
            position,
            status="completed",
            answer_json=answer_json,
            error=None,
        )

    def fail_question(self, job_id: str, token: str, position: int, error: str) -> None:
        self._finish_question(
            job_id,
            token,
            position,
            status="failed",
            error=error,
        )

    def requeue_question(self, job_id: str, token: str, position: int, error: str) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            session.execute(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.position == position,
                    PaperJobQuestionModel.status == "answering",
                )
                .values(status="pending", error=error, completed_at=None)
            )

    def _finish_question(
        self,
        job_id: str,
        token: str,
        position: int,
        *,
        status: str,
        answer_json: str | None = None,
        error: str | None,
    ) -> None:
        with self.sessions.begin() as session:
            self._require_lease(session, job_id, token)
            values: dict[str, Any] = {
                "status": status,
                "error": error,
                "completed_at": utcnow(),
            }
            if answer_json is not None:
                values["answer_json"] = answer_json
            session.execute(
                update(PaperJobQuestionModel)
                .where(
                    PaperJobQuestionModel.job_id == job_id,
                    PaperJobQuestionModel.position == position,
                )
                .values(**values)
            )
            _, completed, failed = self._question_counts(session, job_id)
            self._update_leased_job(
                session,
                job_id,
                token,
                completed_questions=completed,
                failed_questions=failed,
            )

    def _leased_job_update(self, job_id: str, token: str, **values: Any) -> None:
        with self.sessions.begin() as session:
            self._update_leased_job(session, job_id, token, **values)

    @staticmethod
    def _update_leased_job(
        session: Session,
        job_id: str,
        token: str,
        **values: Any,
    ) -> None:
        values.setdefault("updated_at", utcnow())
        result = session.execute(
            update(PaperJobModel)
            .where(PaperJobModel.id == job_id, PaperJobModel.lease_token == token)
            .values(**values)
        )
        if affected_rows(result) != 1:
            raise LostLeaseError(f"paper job {job_id} lease is no longer valid")

    @staticmethod
    def _require_lease(session: Session, job_id: str, token: str) -> None:
        exists = session.scalar(
            select(PaperJobModel.id).where(
                PaperJobModel.id == job_id,
                PaperJobModel.lease_token == token,
            )
        )
        if exists is None:
            raise LostLeaseError(f"paper job {job_id} lease is no longer valid")

    @staticmethod
    def _question_counts(session: Session, job_id: str) -> tuple[int, int, int]:
        row = session.execute(
            select(
                func.count(),
                func.count().filter(PaperJobQuestionModel.status == "completed"),
                func.count().filter(PaperJobQuestionModel.status == "failed"),
            ).where(PaperJobQuestionModel.job_id == job_id)
        ).one()
        return int(row[0]), int(row[1]), int(row[2])
