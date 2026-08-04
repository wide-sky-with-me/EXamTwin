from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from examtwin.agent_harness.model import HarnessMessage
from examtwin.agent_harness.structured import StructuredModelPort
from examtwin.services.model_json import validate_structured_response
from pydantic import BaseModel

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class LiteLLMStructuredModel(StructuredModelPort):
    """Schema-constrained LiteLLM adapter for bounded product tasks."""

    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        reasoning_effort: str | None = None,
        max_retries: int = 1,
    ) -> None:
        if not model.strip():
            raise ValueError("structured model name is required")
        if not api_base.strip():
            raise ValueError("structured model API base is required")
        if not api_key:
            raise ValueError("structured model API key is required")
        if max_retries < 0:
            raise ValueError("structured model retries cannot be negative")
        self.model = model if model.startswith("openai/") else f"openai/{model}"
        self.api_base = api_base
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries

    @property
    def model_name(self) -> str:
        return self.model.removeprefix("openai/")

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        if timeout <= 0:
            raise ValueError("structured model timeout must be positive")
        # Keep LiteLLM's optional model-cost refresh out of deterministic imports.
        from litellm import completion

        request_options: dict[str, Any] = {
            "model": self.model,
            "api_base": self.api_base,
            "api_key": self.api_key,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "response_format": response_model,
            "timeout": timeout,
            "max_retries": self.max_retries,
        }
        if self.reasoning_effort not in {None, "none"}:
            request_options["reasoning_effort"] = self.reasoning_effort
        response = completion(**request_options)
        return validate_structured_response(response, response_model)
