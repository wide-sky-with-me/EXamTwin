from __future__ import annotations

import asyncio
import re
import threading
import time
from collections.abc import Sequence
from typing import Annotated, Any, Protocol

from litellm import acompletion
from llama_index.core.llms import ChatMessage
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from examtwin.services.model_json import (
    repair_markdown_latex,
    validate_structured_response,
)

CitationId = Annotated[str, StringConstraints(pattern=r"^S[1-9][0-9]*$")]
AnswerMarkdown = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60_000),
]
WarningText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
_PRIVATE_PROTOCOL_MARKER = re.compile(
    r"(?:<\s*/?\s*(?:think|analysis)\b|"
    r"^[ \t]*(?:think|analysis|thought|action|action input|observation)[ \t]*:)",
    re.IGNORECASE | re.MULTILINE,
)
_CITATION_MARKER = re.compile(r"\[S([1-9][0-9]*)\]")

_FINALIZER_INSTRUCTION = """
Produce the public final answer for an examination candidate.

Return only the structured response requested by the response schema. Do not expose,
repeat, or summarize hidden chain-of-thought or any `Thought:` text. The
answer_markdown may contain concise, assessable mathematical working.

Use only [S#] evidence identifiers that occur in the supplied tool observations.
citation_ids must exactly list the distinct [S#] identifiers used in answer_markdown,
in first-appearance order. Set grounded=false when the available evidence does not
support the answer. Do not return SVG, HTML, JavaScript, base64, or diagrams; those
are server-owned tool artifacts.
""".strip()

_DRAFT_INSTRUCTION = """
Convert the preceding draft into the public final answer. Preserve the mathematical
result and useful assessable working, but discard protocol text, hidden reasoning,
and tool-call syntax. Obey the response schema and citation rules exactly.
""".strip()


class AgentFinalPayload(BaseModel):
    """Strict, public-only result produced at the answering Agent boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)

    answer_markdown: AnswerMarkdown
    citation_ids: list[CitationId] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)
    grounded: bool = False
    warnings: list[WarningText] = Field(default_factory=list, max_length=16)

    @field_validator("answer_markdown")
    @classmethod
    def reject_private_protocol(cls, value: str) -> str:
        if _PRIVATE_PROTOCOL_MARKER.search(value):
            raise ValueError("answer_markdown contains private reasoning or tool protocol")
        return repair_markdown_latex(value)


def citation_ids_in_markdown(answer_markdown: str) -> list[str]:
    return list(
        dict.fromkeys(f"S{match.group(1)}" for match in _CITATION_MARKER.finditer(answer_markdown))
    )


def validate_citation_contract(
    payload: AgentFinalPayload,
    *,
    allowed_citation_ids: Sequence[str] | None,
) -> None:
    marker_ids = citation_ids_in_markdown(payload.answer_markdown)
    if payload.citation_ids != marker_ids:
        raise ValueError(
            "citation_ids must exactly match answer_markdown citations in first-appearance order"
        )
    if allowed_citation_ids is None:
        return
    allowed = set(allowed_citation_ids)
    invalid = set(marker_ids) - allowed
    if invalid:
        raise ValueError("Final answer referenced citation identifiers that were not retrieved")
    if allowed and not marker_ids:
        raise ValueError("Final answer did not cite its retrieved evidence")


class FinalAnswerProvider(Protocol):
    async def finalize(
        self,
        messages: Sequence[ChatMessage],
        *,
        draft: str | None = None,
        allowed_citation_ids: Sequence[str] | None = None,
        timeout: float | None = None,
    ) -> AgentFinalPayload: ...


class FinalAnswerProviderUnavailable(RuntimeError):
    """Raised while the provider circuit is open; callers should use their fallback."""


def _message_dict(message: ChatMessage) -> dict[str, str]:
    role_value = getattr(message.role, "value", message.role)
    role = str(role_value)
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError(f"Unsupported finalizer message role: {role}")
    content = message.content
    if not isinstance(content, str):
        raise ValueError("Structured finalizer accepts text messages only")
    return {"role": role, "content": content}


class LiteLLMFinalAnswerProvider:
    """Generate one provider-constrained public answer and validate it again locally."""

    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: str,
        *,
        timeout: float = 60,
        max_retries: int = 0,
        reasoning_effort: str | None = None,
        circuit_failure_threshold: int = 2,
        circuit_cooldown_seconds: float = 60,
    ) -> None:
        if not model.strip():
            raise ValueError("Structured finalizer model is required")
        if not api_base.strip():
            raise ValueError("Structured finalizer API base is required")
        if not api_key:
            raise ValueError("Structured finalizer API key is required")
        if timeout <= 0:
            raise ValueError("Structured finalizer timeout must be positive")
        if max_retries < 0:
            raise ValueError("Structured finalizer max_retries cannot be negative")
        if reasoning_effort not in {None, "none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Structured finalizer reasoning effort is invalid")
        if circuit_failure_threshold < 1:
            raise ValueError("Structured finalizer circuit threshold must be positive")
        if circuit_cooldown_seconds <= 0:
            raise ValueError("Structured finalizer circuit cooldown must be positive")

        self.model = model if model.startswith("openai/") else f"openai/{model}"
        self.api_base = api_base
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.reasoning_effort = reasoning_effort
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self._circuit_lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    async def finalize(
        self,
        messages: Sequence[ChatMessage],
        *,
        draft: str | None = None,
        allowed_citation_ids: Sequence[str] | None = None,
        timeout: float | None = None,
    ) -> AgentFinalPayload:
        if timeout is not None and timeout <= 0:
            raise ValueError("Structured finalizer call timeout must be positive")
        effective_timeout = self.timeout if timeout is None else min(self.timeout, timeout)
        self._ensure_circuit_closed()
        request_messages = [
            {"role": "system", "content": _FINALIZER_INSTRUCTION},
            *(_message_dict(message) for message in messages),
        ]
        if draft and draft.strip():
            request_messages.extend(
                (
                    {"role": "assistant", "content": draft[-24_000:]},
                    {"role": "user", "content": _DRAFT_INSTRUCTION},
                )
            )
        else:
            request_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Finish from the supplied question and observations now. "
                        "Return only the structured public answer."
                    ),
                }
            )

        try:
            async with asyncio.timeout(effective_timeout):
                request_options: dict[str, Any] = {
                    "model": self.model,
                    "api_base": self.api_base,
                    "api_key": self.api_key,
                    "messages": request_messages,
                    "response_format": AgentFinalPayload,
                    "timeout": effective_timeout,
                    "max_retries": self.max_retries,
                }
                if self.reasoning_effort is not None:
                    request_options["reasoning_effort"] = self.reasoning_effort
                if not self.model.removeprefix("openai/").startswith("gpt-5.6"):
                    request_options["temperature"] = 0.1
                response = await acompletion(**request_options)
                payload = self._validated_payload(response)
                validate_citation_contract(
                    payload,
                    allowed_citation_ids=allowed_citation_ids,
                )
        except Exception:
            self._record_failure()
            raise
        self._record_success()
        return payload

    def _ensure_circuit_closed(self) -> None:
        now = time.monotonic()
        with self._circuit_lock:
            if self._circuit_open_until and now >= self._circuit_open_until:
                self._consecutive_failures = 0
                self._circuit_open_until = 0.0
            if self._circuit_open_until > now:
                raise FinalAnswerProviderUnavailable(
                    "Structured finalizer is temporarily disabled after repeated failures"
                )

    def _record_failure(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.circuit_failure_threshold:
                self._circuit_open_until = time.monotonic() + self.circuit_cooldown_seconds

    def _record_success(self) -> None:
        with self._circuit_lock:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0

    @staticmethod
    def _validated_payload(response: Any) -> AgentFinalPayload:
        return validate_structured_response(response, AgentFinalPayload)
