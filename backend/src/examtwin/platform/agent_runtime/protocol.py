from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.agent_runtime.tools import HarnessTool


@dataclass(frozen=True)
class ToolCallEvent:
    thought: str
    tool_name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ToolObservationEvent:
    content: str


ProtocolEvent = ToolCallEvent | ToolObservationEvent


@dataclass(frozen=True)
class ProtocolToolCall:
    thought: str
    tool_name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class ProtocolFinal:
    draft: str
    output_json: str | None = None


@dataclass(frozen=True)
class ProtocolInvalid:
    reason: str


ProtocolTurn = ProtocolToolCall | ProtocolFinal | ProtocolInvalid


class AgentProtocolPort(Protocol):
    """Translate between provider-neutral harness state and a model protocol."""

    def format_messages(
        self,
        *,
        system_prompt: str,
        question: str,
        tools: Sequence[HarnessTool],
        events: Sequence[ProtocolEvent],
        corrections: Sequence[HarnessMessage],
    ) -> tuple[HarnessMessage, ...]: ...

    def parse(
        self,
        content: str,
        *,
        tools: Sequence[HarnessTool],
        grounded: bool,
    ) -> ProtocolTurn: ...
