from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import ValidationError

logger = logging.getLogger(__name__)
MAX_TOOL_ERROR_DETAIL_CHARS = 1_200


def safe_tool_error_observation(error: Exception) -> str:
    """Return bounded repair guidance without echoing raw tool inputs."""

    error_type = type(error).__name__
    if isinstance(error, ValidationError):
        detail = json.dumps(
            error.errors(include_url=False, include_input=False),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
    elif isinstance(error, (TypeError, ValueError)):
        detail = " ".join(str(error).split())
    else:
        detail = ""
    if not detail:
        return f"Tool failed: {error_type}"
    bounded = detail[:MAX_TOOL_ERROR_DETAIL_CHARS]
    if len(detail) > MAX_TOOL_ERROR_DETAIL_CHARS:
        bounded += "..."
    return f"Tool failed: {error_type}: {bounded}"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True)
class ToolCallResult:
    content: str
    is_error: bool = False
    replayed: bool = False
    error_type: str | None = None


class HarnessTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def invoke(self, arguments: Mapping[str, Any]) -> ToolCallResult: ...


@dataclass(frozen=True)
class PreparedToolCall:
    tool_name: str
    arguments: Mapping[str, Any]
    canonical_input: str
    signature: tuple[str, str]
    input_digest: str
    call_key: str

    @classmethod
    def from_input(
        cls,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> PreparedToolCall:
        canonical_input = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return cls(
            tool_name=tool_name,
            arguments=dict(arguments),
            canonical_input=canonical_input,
            signature=(tool_name, canonical_input),
            input_digest=hashlib.sha256(canonical_input.encode()).hexdigest(),
            call_key=hashlib.sha256(f"{tool_name}\0{canonical_input}".encode()).hexdigest(),
        )


class ToolCallDisposition(StrEnum):
    EXECUTE = "execute"
    UNKNOWN = "unknown"
    DUPLICATE_SUCCESS = "duplicate_success"
    SUPPRESSED_FAILURE = "suppressed_failure"
    RESERVED_FOR_MANDATORY = "reserved_for_mandatory"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True)
class ToolCallDecision:
    disposition: ToolCallDisposition
    call: PreparedToolCall
    missing_mandatory: tuple[str, ...] = ()


class ToolRunController:
    """Own bounded call governance independently from any model protocol."""

    def __init__(
        self,
        *,
        available_tool_names: set[str],
        mandatory_tool_names: set[str],
        max_tool_calls: int,
    ) -> None:
        if max_tool_calls < 0:
            raise ValueError("tool-call budget cannot be negative")
        unavailable = mandatory_tool_names - available_tool_names
        if unavailable:
            raise ValueError("mandatory tools are unavailable: " + ", ".join(sorted(unavailable)))
        self.available_tool_names = frozenset(available_tool_names)
        self.mandatory_tool_names = frozenset(mandatory_tool_names)
        self.max_tool_calls = max_tool_calls
        self.tool_calls = 0
        self.completed_tool_names: set[str] = set()
        self.completed_signatures: set[tuple[str, str]] = set()
        self.failed_tool_name: str | None = None
        self.failed_tool_streak = 0
        self.last_failed_signature: tuple[str, str] | None = None

    @property
    def missing_mandatory(self) -> tuple[str, ...]:
        return tuple(sorted(self.mandatory_tool_names - self.completed_tool_names))

    def decide(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ToolCallDecision:
        call = PreparedToolCall.from_input(tool_name, arguments)
        if call.signature == self.last_failed_signature or (
            tool_name == self.failed_tool_name and self.failed_tool_streak >= 2
        ):
            return ToolCallDecision(ToolCallDisposition.SUPPRESSED_FAILURE, call)
        if tool_name not in self.available_tool_names:
            return ToolCallDecision(ToolCallDisposition.UNKNOWN, call)
        if call.signature in self.completed_signatures:
            return ToolCallDecision(ToolCallDisposition.DUPLICATE_SUCCESS, call)
        missing = self.missing_mandatory
        remaining_calls = self.max_tool_calls - self.tool_calls
        if missing and tool_name not in missing and remaining_calls <= len(missing):
            return ToolCallDecision(
                ToolCallDisposition.RESERVED_FOR_MANDATORY,
                call,
                missing,
            )
        if self.tool_calls >= self.max_tool_calls:
            return ToolCallDecision(ToolCallDisposition.BUDGET_EXHAUSTED, call)
        return ToolCallDecision(ToolCallDisposition.EXECUTE, call)

    def mark_started(self) -> None:
        self.tool_calls += 1

    def record_success(self, call: PreparedToolCall) -> None:
        self.completed_tool_names.add(call.tool_name)
        self.completed_signatures.add(call.signature)
        self.failed_tool_name = None
        self.failed_tool_streak = 0
        self.last_failed_signature = None

    def record_failure(self, call: PreparedToolCall) -> None:
        self.failed_tool_streak = (
            self.failed_tool_streak + 1 if self.failed_tool_name == call.tool_name else 1
        )
        self.failed_tool_name = call.tool_name
        self.last_failed_signature = call.signature


class ToolExecutionLifecycle(Protocol):
    def replay(self, call: PreparedToolCall) -> ToolCallResult | None: ...

    def started(self, call: PreparedToolCall) -> None: ...

    def finished(self, call: PreparedToolCall, result: ToolCallResult) -> None: ...


class ToolExecutor:
    """Execute one validated tool call with pluggable persistence/effect hooks."""

    async def execute(
        self,
        call: PreparedToolCall,
        tool: HarnessTool,
        lifecycle: ToolExecutionLifecycle,
        *,
        allow_replay: bool = True,
    ) -> ToolCallResult:
        replay = lifecycle.replay(call) if allow_replay else None
        if replay is not None:
            return replay
        lifecycle.started(call)
        try:
            result = await tool.invoke(call.arguments)
        except Exception as error:
            observation = safe_tool_error_observation(error)
            logger.warning(
                "answering_tool_failed tool_name=%s error_type=%s detail=%s",
                call.tool_name,
                type(error).__name__,
                observation,
            )
            result = ToolCallResult(
                content=observation,
                is_error=True,
                error_type=type(error).__name__,
            )
        lifecycle.finished(call, result)
        return result
