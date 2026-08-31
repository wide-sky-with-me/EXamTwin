from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from examtwin.platform.agent_runtime.model import ChatModelPort, HarnessMessage


def configure_litellm() -> None:
    import litellm

    litellm.suppress_debug_info = True


def litellm_model_name(model: str, provider: str) -> str:
    """Route a provider model through LiteLLM without leaking the prefix to domain data."""

    resolved_model = model.strip()
    resolved_provider = provider.strip().rstrip("/")
    if not resolved_model:
        raise ValueError("LiteLLM model name is required")
    if not resolved_provider:
        raise ValueError("LiteLLM provider is required")
    prefix = f"{resolved_provider}/"
    return resolved_model if resolved_model.startswith(prefix) else f"{prefix}{resolved_model}"


def provider_model_name(model: str, provider: str) -> str:
    prefix = f"{provider.strip().rstrip('/')}/"
    return model[len(prefix) :] if prefix != "/" and model.startswith(prefix) else model


def completion_options(
    *,
    model: str,
    provider: str,
    api_base: str,
    api_key: str,
    reasoning_effort: str | None,
    timeout: float,
    max_retries: int,
) -> dict[str, Any]:
    if not api_base.strip():
        raise ValueError("LiteLLM API base is required")
    if not api_key:
        raise ValueError("LiteLLM API key is required")
    if timeout <= 0:
        raise ValueError("LiteLLM timeout must be positive")
    if max_retries < 0:
        raise ValueError("LiteLLM retries cannot be negative")
    options: dict[str, Any] = {
        "model": litellm_model_name(model, provider),
        "api_base": api_base.rstrip("/"),
        "api_key": api_key,
        "timeout": timeout,
        "max_retries": max_retries,
    }
    if reasoning_effort not in {None, "none"}:
        options["reasoning_effort"] = reasoning_effort
    return options


def response_message_content(response: Any) -> str:
    choices = response.get("choices") if isinstance(response, Mapping) else response.choices
    if not choices:
        raise ValueError("LiteLLM returned no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else first.message
    if message is None:
        raise ValueError("LiteLLM returned no message")
    content = message.get("content") if isinstance(message, Mapping) else message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LiteLLM returned no text content")
    return content


def retryable_provider_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code is None:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code is None:
        return True
    try:
        resolved_status = int(status_code)
    except (TypeError, ValueError):
        return True
    return resolved_status in {408, 429} or resolved_status >= 500


class LiteLLMChatModel(ChatModelPort):
    """Provider-neutral text chat surface backed by LiteLLM."""

    def __init__(
        self,
        *,
        model: str,
        provider: str,
        api_base: str,
        api_key: str,
        reasoning_effort: str | None,
        timeout: float,
        max_retries: int = 1,
    ) -> None:
        self._model_name = provider_model_name(model, provider)
        self._options = completion_options(
            model=model,
            provider=provider,
            api_base=api_base,
            api_key=api_key,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
            max_retries=max_retries,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, messages: Sequence[HarnessMessage]) -> str:
        configure_litellm()
        from litellm import acompletion

        response = await acompletion(
            **self._options,
            messages=[{"role": message.role, "content": message.content} for message in messages],
        )
        return response_message_content(response)
