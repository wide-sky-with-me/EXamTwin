from typing import Any

import pytest
from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.config import Settings
from examtwin.platform.providers import (
    IndexResultsReranker,
    _embedding_batch_with_fallback,
    build_chat_model,
)
from llama_index.core.schema import NodeWithScore, TextNode


@pytest.mark.asyncio
async def test_chat_model_routes_through_litellm_without_model_family_hardcoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "EXAMTWIN_OK"}}]}

    monkeypatch.setattr("litellm.acompletion", fake_completion)
    settings = Settings(
        llm_base_url="https://models.invalid/v1",
        llm_api_key="test-key",
        llm_model="gpt-5.6-sol",
        llm_reasoning_effort="medium",
    )

    model = build_chat_model(settings, max_retries=0)
    result = await model.complete((HarnessMessage(role="user", content="ping"),))

    assert result == "EXAMTWIN_OK"
    assert model.model_name == "gpt-5.6-sol"
    assert captured["model"] == "openai/gpt-5.6-sol"
    assert captured["reasoning_effort"] == "medium"
    assert captured["api_base"] == "https://models.invalid/v1"
    assert "temperature" not in captured


def test_reranker_limits_table_projection_without_mutating_full_table(
    monkeypatch: Any,
) -> None:
    table = (
        "<table>"
        + "".join(
            f"<tr><td>Original row {index:04d}</td><td>{'x' * 80}</td></tr>" for index in range(500)
        )
        + "</table>"
    )
    projection = "\n".join(
        f"Projected row {index:04d} with searchable content" for index in range(700)
    )
    node = NodeWithScore(
        node=TextNode(
            text=table,
            metadata={
                "block_kind": "table",
                "retrieval_text": projection,
            },
        ),
        score=0.1,
    )
    posted: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"results": [{"index": 0, "relevance_score": 0.91}]}

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: int,
    ) -> FakeResponse:
        posted.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("examtwin.platform.providers.httpx.post", fake_post)
    reranker = object.__new__(IndexResultsReranker)
    reranker.url = "https://reranker.invalid/rerank"
    reranker.api_key = "placeholder"
    reranker.model = "test-reranker"
    reranker.timeout = 30
    reranker.document_max_chars = 20_000

    reranked = reranker.rerank("searchable content", [node], top_n=1)

    assert posted["json"]["documents"] == [projection[:20_000]]
    assert posted["timeout"] == 30
    assert len(posted["json"]["documents"][0]) == 20_000
    assert node.node.get_content() == table
    assert reranked[0].node.get_content() == table
    assert reranked[0].score == 0.91


def test_embedding_batch_replays_transient_provider_parameter_error() -> None:
    calls = 0

    def fetch(texts: list[str]) -> list[list[float]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("code 20015: The parameter is invalid")
        return [[float(len(text))] for text in texts]

    result = _embedding_batch_with_fallback(
        fetch,
        ["first", "second"],
        pause=lambda _seconds: None,
    )

    assert result == [[5.0], [6.0]]
    assert calls == 2


def test_embedding_batch_does_not_retry_deterministic_invalid_parameter() -> None:
    calls = 0

    def fetch(_texts: list[str]) -> list[list[float]]:
        nonlocal calls
        calls += 1
        raise RuntimeError("Invalid model parameter: unsupported dimensions")

    with pytest.raises(RuntimeError, match="unsupported dimensions"):
        _embedding_batch_with_fallback(
            fetch,
            ["first", "second"],
            pause=lambda _seconds: None,
        )

    assert calls == 1
