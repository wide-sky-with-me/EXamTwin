from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Sequence
from typing import Annotated, Any, Protocol

from litellm import acompletion
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.model_json import (
    repair_markdown_latex,
    validate_structured_response,
)

CitationId = Annotated[str, StringConstraints(pattern=r"^S[1-9][0-9]*$")]
MAX_ANSWER_MARKDOWN_CHARS = 60_000
AnswerMarkdown = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_ANSWER_MARKDOWN_CHARS,
    ),
]
WarningText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
SubpartLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
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


def _subpart_instruction(required_subpart_labels: Sequence[str]) -> str:
    if not required_subpart_labels:
        return (
            "This question has no labelled subparts. Set subparts=[] and put the complete "
            "public answer in answer_markdown."
        )
    labels = json.dumps(list(required_subpart_labels), ensure_ascii=False)
    return (
        f"The required printed subpart labels, in order, are {labels}. "
        "Set answer_markdown to an empty string. Return exactly one subparts item for each "
        "required label, in that order, copying each label exactly. Put only that subpart's "
        "public answer and assessable working in its answer_markdown. The server owns final "
        "heading rendering; do not merge, rename, renumber, omit, or add subparts."
    )


def _validated_public_markdown(value: str) -> str:
    if _PRIVATE_PROTOCOL_MARKER.search(value):
        raise ValueError("answer_markdown contains private reasoning or tool protocol")
    return repair_markdown_latex(value)


class AgentSubpartAnswer(BaseModel):
    """One labelled answer body; the server renders the trusted printed label."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: SubpartLabel
    answer_markdown: AnswerMarkdown

    @field_validator("answer_markdown")
    @classmethod
    def reject_private_protocol(cls, value: str) -> str:
        return _validated_public_markdown(value)


PublicAnswerMarkdown = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=MAX_ANSWER_MARKDOWN_CHARS),
]


class AgentFinalPayload(BaseModel):
    """Strict, public-only result produced at the answering Agent boundary."""

    model_config = ConfigDict(extra="forbid", strict=True)

    answer_markdown: PublicAnswerMarkdown = ""
    subparts: list[AgentSubpartAnswer] = Field(default_factory=list, max_length=32)
    citation_ids: list[CitationId] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)
    grounded: bool = False
    warnings: list[WarningText] = Field(default_factory=list, max_length=16)

    @field_validator("answer_markdown")
    @classmethod
    def reject_private_protocol(cls, value: str) -> str:
        return _validated_public_markdown(value) if value else value

    @model_validator(mode="after")
    def require_public_answer(self) -> AgentFinalPayload:
        if not self.answer_markdown and not self.subparts:
            raise ValueError("final answer must contain answer_markdown or labelled subparts")
        return self


def materialize_final_answer(
    payload: AgentFinalPayload,
    *,
    required_subpart_labels: Sequence[str],
) -> AgentFinalPayload:
    """Render trusted labels around model-produced bodies and enforce exact coverage."""

    expected = tuple(label.strip() for label in required_subpart_labels)
    if any(not label for label in expected) or len(set(expected)) != len(expected):
        raise ValueError("required subpart labels must be non-empty and unique")
    if not expected:
        if payload.subparts:
            raise ValueError("final answer returned labelled subparts for an unlabelled question")
        return payload

    if payload.answer_markdown:
        raise ValueError("labelled questions must return structured subpart answer bodies")
    actual = tuple(subpart.label for subpart in payload.subparts)
    if actual != expected:
        raise ValueError(
            f"final answer subpart labels must exactly match {expected}; received {actual}"
        )
    answer_markdown = "\n\n".join(
        f"### {subpart.label}\n\n{subpart.answer_markdown}" for subpart in payload.subparts
    )
    if len(answer_markdown) > MAX_ANSWER_MARKDOWN_CHARS:
        raise ValueError("materialized final answer exceeds the public Markdown limit")
    return payload.model_copy(update={"answer_markdown": answer_markdown, "subparts": []})


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
        messages: Sequence[HarnessMessage],
        *,
        draft: str | None = None,
        allowed_citation_ids: Sequence[str] | None = None,
        required_subpart_labels: Sequence[str] = (),
        timeout: float | None = None,
    ) -> AgentFinalPayload: ...


class FinalAnswerProviderUnavailable(RuntimeError):
    """Raised while the provider circuit is open; callers should use their fallback."""


def _message_dict(message: HarnessMessage) -> dict[str, str]:
    role = message.role
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
        messages: Sequence[HarnessMessage],
        *,
        draft: str | None = None,
        required_subpart_labels: Sequence[str] = (),
        allowed_citation_ids: Sequence[str] | None = None,
        timeout: float | None = None,
    ) -> AgentFinalPayload:
        if timeout is not None and timeout <= 0:
            raise ValueError("Structured finalizer call timeout must be positive")
        effective_timeout = self.timeout if timeout is None else min(self.timeout, timeout)
        self._ensure_circuit_closed()
        request_messages = [
            {
                "role": "system",
                "content": (
                    f"{_FINALIZER_INSTRUCTION}\n\n{_subpart_instruction(required_subpart_labels)}"
                ),
            },
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
                materialized = materialize_final_answer(
                    payload,
                    required_subpart_labels=required_subpart_labels,
                )
                validate_citation_contract(
                    materialized,
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
