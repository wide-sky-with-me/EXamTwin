import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from examtwin.answering_agent.finalization import (
    AgentFinalPayload,
    FinalAnswerProviderUnavailable,
    LiteLLMFinalAnswerProvider,
)
from examtwin.config import Settings
from examtwin.services.providers import build_final_answer_provider
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from pydantic import ValidationError


def _completion_message(
    *,
    content: str | None = None,
    parsed: Any = None,
    reasoning_content: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    parsed=parsed,
                    reasoning_content=reasoning_content,
                )
            )
        ]
    )


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "answer_markdown": "Therefore, $x=2$. [S1]",
        "citation_ids": ["S1"],
        "confidence": 0.91,
        "grounded": True,
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def test_payload_defaults_to_not_grounded_when_model_omits_the_claim() -> None:
    payload = AgentFinalPayload.model_validate(
        {
            "answer_markdown": "A compatibility answer. [S1]",
            "citation_ids": ["S1"],
            "confidence": 0.5,
            "warnings": [],
        }
    )

    assert payload.grounded is False


def test_build_final_answer_provider_maps_settings_and_caps_timeout() -> None:
    settings = Settings(
        llm_model="factory-model",
        openai_compat_base_url="https://factory.invalid/compatible-mode/v1",
        openai_compat_api_key="factory-key",
        answer_agent_timeout=600,
    )

    provider = build_final_answer_provider(settings)

    assert provider.model == "openai/factory-model"
    assert provider.api_base == "https://factory.invalid/compatible-mode/v1"
    assert provider.api_key == "factory-key"
    assert provider.timeout == 45
    assert provider.max_retries == 0
    assert provider.reasoning_effort == settings.llm_reasoning_effort


@pytest.mark.parametrize(
    ("configured_model", "expected_model"),
    [
        ("qwen3.7-plus", "openai/qwen3.7-plus"),
        ("openai/qwen3.7-plus", "openai/qwen3.7-plus"),
    ],
)
async def test_finalize_routes_openai_compatible_model_and_forwards_schema(
    monkeypatch: pytest.MonkeyPatch,
    configured_model: str,
    expected_model: str,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _completion_message(content=json.dumps(_valid_payload()))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model=configured_model,
        api_base="https://models.invalid/compatible-mode/v1",
        api_key="test-key",
        timeout=37,
        max_retries=2,
    )

    result = await provider.finalize([ChatMessage(role=MessageRole.USER, content="Solve $x+1=3$.")])

    assert isinstance(result, AgentFinalPayload)
    assert captured["model"] == expected_model
    assert captured["api_base"] == "https://models.invalid/compatible-mode/v1"
    assert captured["api_key"] == "test-key"
    assert captured["timeout"] == 37
    assert captured["max_retries"] == 2
    assert captured["response_format"] is AgentFinalPayload


async def test_gpt56_finalizer_uses_reasoning_without_unsupported_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _completion_message(content=json.dumps(_valid_payload()))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="gpt-5.6-sol",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        reasoning_effort="medium",
    )

    await provider.finalize([ChatMessage(role=MessageRole.USER, content="Solve the question.")])

    assert captured["reasoning_effort"] == "medium"
    assert "temperature" not in captured


async def test_finalize_preserves_messages_and_appends_draft_for_public_finalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return _completion_message(content=json.dumps(_valid_payload()))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )
    original = [
        ChatMessage(role=MessageRole.SYSTEM, content="Use only supplied evidence."),
        ChatMessage(role=MessageRole.USER, content="Find the roots."),
    ]
    draft = "Private scratch work must not be exposed. Public candidate: $x=2$."

    await provider.finalize(original, draft=draft)

    sent = captured["messages"]
    assert sent[0]["role"] == "system"
    assert "public final answer" in sent[0]["content"].lower()
    assert sent[1:3] == [
        {"role": "system", "content": "Use only supplied evidence."},
        {"role": "user", "content": "Find the roots."},
    ]
    assert sent[3] == {"role": "assistant", "content": draft}
    assert sent[4]["role"] == "user"
    instruction = sent[4]["content"].lower()
    assert "public" in instruction
    assert "final" in instruction


async def test_finalize_validates_json_content_with_pydantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(content=json.dumps(_valid_payload(warnings=["Check units."])))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    result = await provider.finalize(
        [ChatMessage(role=MessageRole.USER, content="Solve the question.")]
    )

    assert result.model_dump() == _valid_payload(warnings=["Check units."])


async def test_finalize_prefers_raw_json_to_preserve_latex_backslashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_content = (
        r'{"answer_markdown":"Use $P(X=2)=\binom{20}{2}\times 0.015^2$. [S1]",'
        r'"citation_ids":["S1"],"confidence":0.9,"grounded":true,"warnings":[]}'
    )
    corrupted_parsed = AgentFinalPayload.model_validate(
        _valid_payload(answer_markdown="Use $P(X=2)=binom{20}{2}times 0.015^2$. [S1]")
    )

    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(content=raw_content, parsed=corrupted_parsed)

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
    )

    result = await provider.finalize(
        [ChatMessage(role=MessageRole.USER, content="Solve the question.")]
    )

    assert result.answer_markdown == (r"Use $P(X=2)=\binom{20}{2}\times 0.015^2$. [S1]")


def test_payload_repairs_legacy_missing_latex_commands_inside_math() -> None:
    payload = AgentFinalPayload.model_validate(
        _valid_payload(
            answer_markdown=("$lambda = 1.8$ and $frac{e^{-lambda} times lambda^2}{2}$. [S1]")
        )
    )

    assert payload.answer_markdown == (
        r"$\lambda = 1.8$ and $\frac{e^{-\lambda} \times \lambda^2}{2}$. [S1]"
    )


async def test_finalize_accepts_litellm_parsed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsed = AgentFinalPayload.model_validate(_valid_payload())

    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(parsed=parsed)

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    result = await provider.finalize(
        [ChatMessage(role=MessageRole.USER, content="Solve the question.")]
    )

    assert result == parsed


@pytest.mark.parametrize(
    "payload",
    [
        _valid_payload(unexpected="must be rejected"),
        _valid_payload(answer_markdown=""),
        _valid_payload(answer_markdown="   "),
        _valid_payload(answer_markdown="<think>private</think>\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="<THINK>private</THINK>\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="<AnAlYsIs>private</AnAlYsIs>\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="aNaLySiS: private\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="Thought: private\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="oBsErVaTiOn: private\nPublic answer. [S1]"),
        _valid_payload(answer_markdown="Action: knowledge_search\nPublic answer. [S1]"),
        _valid_payload(confidence=1.01),
        _valid_payload(warnings="not-a-list"),
    ],
)
async def test_finalize_rejects_invalid_payload_schema(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(content=json.dumps(payload))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    with pytest.raises(ValidationError):
        await provider.finalize([ChatMessage(role=MessageRole.USER, content="Solve the question.")])


@pytest.mark.parametrize("content", [None, "", "   ", "not valid JSON"])
async def test_finalize_rejects_empty_or_non_json_content(
    monkeypatch: pytest.MonkeyPatch,
    content: str | None,
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(content=content)

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    with pytest.raises((ValueError, ValidationError)):
        await provider.finalize([ChatMessage(role=MessageRole.USER, content="Solve the question.")])


@pytest.mark.parametrize(
    "payload",
    [
        _valid_payload(citation_ids=[]),
        _valid_payload(
            answer_markdown="A fabricated citation. [S2]",
            citation_ids=["S2"],
        ),
        _valid_payload(
            answer_markdown="An uncited answer.",
            citation_ids=[],
        ),
    ],
)
async def test_finalize_rejects_citations_outside_server_contract(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(content=json.dumps(payload))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=0,
    )

    with pytest.raises(ValueError):
        await provider.finalize(
            [ChatMessage(role=MessageRole.USER, content="Solve the question.")],
            allowed_citation_ids=("S1",),
        )


async def test_finalize_ignores_reasoning_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_reasoning = json.dumps(
        _valid_payload(answer_markdown="SECRET chain-of-thought must never be shown.")
    )

    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(
            content=json.dumps(_valid_payload(answer_markdown="Public answer. [S1]")),
            reasoning_content=private_reasoning,
        )

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    result = await provider.finalize(
        [ChatMessage(role=MessageRole.USER, content="Solve the question.")]
    )

    assert result.answer_markdown == "Public answer. [S1]"
    assert "SECRET" not in result.answer_markdown


async def test_finalize_does_not_fall_back_to_reasoning_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_acompletion(**_kwargs: Any) -> SimpleNamespace:
        return _completion_message(
            content=None,
            reasoning_content=json.dumps(_valid_payload()),
        )

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        fake_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=30,
        max_retries=1,
    )

    with pytest.raises((ValueError, ValidationError)):
        await provider.finalize([ChatMessage(role=MessageRole.USER, content="Solve the question.")])


async def test_repeated_failures_open_shared_provider_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def failing_acompletion(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        failing_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=1,
        max_retries=0,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60,
    )
    messages = [ChatMessage(role=MessageRole.USER, content="Solve the question.")]

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await provider.finalize(messages)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await provider.finalize(messages)
    with pytest.raises(FinalAnswerProviderUnavailable, match="temporarily disabled"):
        await provider.finalize(messages)

    assert calls == 2


async def test_provider_owned_timeouts_open_shared_provider_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def slow_acompletion(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        await asyncio.sleep(10)
        raise AssertionError("provider timeout did not cancel the request")

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        slow_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=1,
        max_retries=0,
        circuit_failure_threshold=2,
        circuit_cooldown_seconds=60,
    )
    messages = [ChatMessage(role=MessageRole.USER, content="Solve the question.")]

    with pytest.raises(TimeoutError):
        await provider.finalize(messages, timeout=0.01)
    with pytest.raises(TimeoutError):
        await provider.finalize(messages, timeout=0.01)
    with pytest.raises(FinalAnswerProviderUnavailable, match="temporarily disabled"):
        await provider.finalize(messages, timeout=0.01)

    assert calls == 2


async def test_external_task_cancellation_does_not_open_provider_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def cancellable_acompletion(**_kwargs: Any) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
        return _completion_message(content=json.dumps(_valid_payload()))

    monkeypatch.setattr(
        "examtwin.answering_agent.finalization.acompletion",
        cancellable_acompletion,
    )
    provider = LiteLLMFinalAnswerProvider(
        model="qwen3.7-plus",
        api_base="https://models.invalid/v1",
        api_key="test-key",
        timeout=1,
        max_retries=0,
        circuit_failure_threshold=1,
        circuit_cooldown_seconds=60,
    )
    messages = [ChatMessage(role=MessageRole.USER, content="Solve the question.")]
    task = asyncio.create_task(provider.finalize(messages, timeout=0.5))
    await asyncio.wait_for(started.wait(), timeout=0.5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    result = await provider.finalize(messages, timeout=0.5)

    assert result.answer_markdown == _valid_payload()["answer_markdown"]
    assert calls == 2
