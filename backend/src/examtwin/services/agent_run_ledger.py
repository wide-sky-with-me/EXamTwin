from __future__ import annotations

import logging

from examtwin.answering_agent.contracts import AgentRunLedger, ToolReplayPayload
from examtwin.persistence.paper_job_repository import PaperJobRepository
from examtwin.persistence.session import utcnow

logger = logging.getLogger(__name__)


class PaperAgentRunLedger(AgentRunLedger):
    """Lease-safe durable run ledger bound to one paper question attempt."""

    def __init__(
        self,
        repository: PaperJobRepository,
        *,
        job_id: str,
        lease_token: str,
        question_position: int,
        run_attempt: int,
    ) -> None:
        self.repository = repository
        self.job_id = job_id
        self.lease_token = lease_token
        self.question_position = question_position
        self.run_attempt = run_attempt
        self._started = False

    def start_run(
        self,
        *,
        package_id: str,
        package_version: str,
        package_digest: str,
        skill_digest: str,
        prompt_digest: str,
        model_name: str,
        max_iterations: int,
        max_tool_calls: int,
    ) -> None:
        self.repository.start_agent_run(
            {
                "job_id": self.job_id,
                "question_position": self.question_position,
                "run_attempt": self.run_attempt,
                "package_id": package_id,
                "package_version": package_version,
                "package_digest": package_digest,
                "skill_digest": skill_digest,
                "prompt_digest": prompt_digest,
                "model_name": model_name,
                "max_iterations": max_iterations,
                "max_tool_calls": max_tool_calls,
                "status": "running",
                "started_at": utcnow(),
                "completed_at": None,
            },
            self.lease_token,
        )
        self._started = True

    def find_replay(
        self,
        *,
        call_key: str,
        execution_fingerprint: str,
    ) -> ToolReplayPayload | None:
        raw = self.repository.agent_tool_replay(
            self.job_id,
            self.lease_token,
            self.question_position,
            self.run_attempt,
            call_key,
            execution_fingerprint,
        )
        if raw is None:
            return None
        try:
            return ToolReplayPayload.model_validate_json(raw)
        except ValueError:
            logger.warning(
                "paper_job=%s question=%s attempt=%s invalid_tool_replay=%s",
                self.job_id,
                self.question_position,
                self.run_attempt,
                call_key,
            )
            return None

    def tool_started(
        self,
        *,
        call_key: str,
        tool_name: str,
        input_digest: str,
        execution_fingerprint: str,
        replay_safe: bool,
    ) -> None:
        self.repository.start_agent_tool_call(
            {
                "job_id": self.job_id,
                "question_position": self.question_position,
                "run_attempt": self.run_attempt,
                "call_key": call_key,
                "tool_name": tool_name,
                "input_digest": input_digest,
                "execution_fingerprint": execution_fingerprint,
                "replay_safe": replay_safe,
                "status": "running",
                "result_digest": None,
                "replay_json": None,
                "error_type": None,
                "started_at": utcnow(),
                "completed_at": None,
            },
            self.lease_token,
        )

    def tool_finished(
        self,
        *,
        call_key: str,
        status: str,
        result_digest: str | None,
        replay: ToolReplayPayload | None,
        error_type: str | None,
    ) -> None:
        self.repository.finish_agent_tool_call(
            self.job_id,
            self.lease_token,
            self.question_position,
            self.run_attempt,
            call_key,
            status=status,
            result_digest=result_digest,
            replay_json=None if replay is None else replay.model_dump_json(),
            error_type=error_type,
        )

    def finish_run(self, status: str) -> None:
        if not self._started:
            return
        self.repository.finish_agent_run(
            self.job_id,
            self.lease_token,
            self.question_position,
            self.run_attempt,
            status,
        )
