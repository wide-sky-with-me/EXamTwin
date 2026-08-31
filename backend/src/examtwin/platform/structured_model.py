from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.agent_runtime.structured import StructuredModelPort
from examtwin.platform.litellm_provider import (
    completion_options,
    configure_litellm,
    provider_model_name,
)
from examtwin.platform.model_json import validate_structured_response

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class LiteLLMStructuredModel(StructuredModelPort):
    """Schema-constrained LiteLLM adapter for bounded product tasks."""

    def __init__(
        self,
        *,
        model: str,
        provider: str,
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
        self.model = provider_model_name(model, provider)
        self.provider = provider
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries

    @property
    def model_name(self) -> str:
        return self.model

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
        configure_litellm()
        from litellm import completion

        request_options: dict[str, Any] = {
            **completion_options(
                model=self.model,
                provider=self.provider,
                api_base=self.api_base,
                api_key=self.api_key,
                reasoning_effort=self.reasoning_effort,
                timeout=timeout,
                max_retries=self.max_retries,
            ),
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "response_format": response_model,
        }
        response = completion(**request_options)
        return validate_structured_response(response, response_model)
