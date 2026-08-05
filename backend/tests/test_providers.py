from typing import Any

from examtwin.config import Settings
from examtwin.services.providers import (
    SiliconFlowReranker,
    _embedding_batch_with_fallback,
    build_llm,
)
from llama_index.core.schema import NodeWithScore, TextNode


def test_gpt56_llamaindex_adapter_uses_supported_sampling_and_reasoning() -> None:
    settings = Settings(
        openai_compat_base_url="https://models.invalid/v1",
        openai_compat_api_key="test-key",
        llm_model="gpt-5.6-sol",
        llm_reasoning_effort="medium",
    )

    llm = build_llm(settings, max_retries=0)

    assert llm.temperature == 1
    assert llm.additional_kwargs["reasoning_effort"] == "medium"
    assert llm.api_base == "https://models.invalid/v1"


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

    monkeypatch.setattr("examtwin.services.providers.httpx.post", fake_post)
    reranker = object.__new__(SiliconFlowReranker)
    reranker.url = "https://reranker.invalid/rerank"
    reranker.api_key = "placeholder"
    reranker.model = "test-reranker"
    reranker.timeout = 30

    reranked = reranker.rerank("searchable content", [node], top_n=1)

    assert posted["json"]["documents"] == [projection[:20_000]]
    assert posted["timeout"] == 30
    assert len(posted["json"]["documents"][0]) == 20_000
    assert node.node.get_content() == table
    assert reranked[0].node.get_content() == table
    assert reranked[0].score == 0.91


def test_embedding_batch_replays_transient_siliconflow_parameter_error() -> None:
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
