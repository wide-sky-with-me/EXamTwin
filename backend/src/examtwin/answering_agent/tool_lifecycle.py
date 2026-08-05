from __future__ import annotations

import hashlib

from examtwin.agent_harness.tools import (
    PreparedToolCall,
    ToolCallResult,
    ToolExecutionLifecycle,
)
from examtwin.answering_agent.contracts import (
    AgentRunContext,
    SubjectSkill,
    ToolReplayPayload,
)
from examtwin.contracts.system import API_CONTRACT_VERSION

REPLAY_SAFE_TOOLS = frozenset(
    {
        "math_calculate",
        "probability_calculate",
        "math_plot",
        "math_diagram",
        "economics_calculate",
        "economics_diagram",
    }
)


class AnsweringToolLifecycle(ToolExecutionLifecycle):
    """Bind generic tool execution to typed answer effects and the durable ledger."""

    def __init__(self, context: AgentRunContext, skill: SubjectSkill) -> None:
        self.context = context
        self.skill = skill
        self._effect_starts: dict[str, tuple[int, int, int]] = {}

    def _fingerprint(self, call: PreparedToolCall) -> str:
        return hashlib.sha256(
            (
                f"{API_CONTRACT_VERSION}\0{self.skill.package_digest}\0"
                f"{call.tool_name}\0{call.canonical_input}"
            ).encode()
        ).hexdigest()

    def replay(self, call: PreparedToolCall) -> ToolCallResult | None:
        ledger = self.context.ledger
        if ledger is None or call.tool_name not in REPLAY_SAFE_TOOLS:
            return None
        replay = ledger.find_replay(
            call_key=call.call_key,
            execution_fingerprint=self._fingerprint(call),
        )
        if replay is None:
            return None
        for citation in replay.citations:
            self.context.add_citation(citation)
        for diagram in replay.diagrams:
            self.context.add_diagram(diagram)
        for image in replay.images:
            self.context.add_image(image)
        return ToolCallResult(content=replay.observation, replayed=True)

    def started(self, call: PreparedToolCall) -> None:
        self._effect_starts[call.call_key] = (
            len(self.context.citations),
            len(self.context.diagrams),
            len(self.context.images),
        )
        if self.context.ledger is not None:
            self.context.ledger.tool_started(
                call_key=call.call_key,
                tool_name=call.tool_name,
                input_digest=call.input_digest,
                execution_fingerprint=self._fingerprint(call),
                replay_safe=call.tool_name in REPLAY_SAFE_TOOLS,
            )

    def finished(self, call: PreparedToolCall, result: ToolCallResult) -> None:
        ledger = self.context.ledger
        if ledger is None:
            return
        citation_start, diagram_start, image_start = self._effect_starts.pop(
            call.call_key,
            (len(self.context.citations), len(self.context.diagrams), len(self.context.images)),
        )
        replay = (
            ToolReplayPayload(
                observation=result.content,
                citations=tuple(self.context.citations[citation_start:]),
                diagrams=tuple(self.context.diagrams[diagram_start:]),
                images=tuple(self.context.images[image_start:]),
            )
            if call.tool_name in REPLAY_SAFE_TOOLS and not result.is_error
            else None
        )
        ledger.tool_finished(
            call_key=call.call_key,
            status="failed" if result.is_error else "completed",
            result_digest=(
                None if result.is_error else hashlib.sha256(result.content.encode()).hexdigest()
            ),
            replay=replay,
            error_type=(result.error_type or "ToolOutputError") if result.is_error else None,
        )
