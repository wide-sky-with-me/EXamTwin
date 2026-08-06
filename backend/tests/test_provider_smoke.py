from types import SimpleNamespace
from typing import cast

import pytest
from examtwin.answering_agent.finalization import AgentFinalPayload
from examtwin.config import Settings
from examtwin.services import providers


class _FinalAnswerProvider:
    async def finalize(self, *_args: object, **_kwargs: object) -> AgentFinalPayload:
        return AgentFinalPayload(answer_markdown="EXAMTWIN_OK")


class _EmbeddingProvider:
    def get_text_embedding(self, _text: str) -> list[float]:
        return [0.25, -0.5, 0.75]


class _Reranker:
    def __init__(self, _settings: Settings) -> None:
        pass

    def rerank(self, _query: str, nodes: list, *, top_n: int) -> list:
        return nodes[:top_n]


def _settings() -> Settings:
    return cast(
        Settings,
        SimpleNamespace(
            llm_model="llm-smoke-model",
            embedding_model="embedding-smoke-model",
            rerank_model="rerank-smoke-model",
        ),
    )


def test_provider_smoke_checks_each_live_response_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        providers, "build_final_answer_provider", lambda _settings: _FinalAnswerProvider()
    )
    monkeypatch.setattr(providers, "build_embedding", lambda _settings: _EmbeddingProvider())
    monkeypatch.setattr(providers, "SiliconFlowReranker", _Reranker)

    result = providers.run_provider_smoke(_settings(), {"llm", "embedding", "rerank"})

    assert [item["provider"] for item in result] == ["embedding", "llm", "rerank"]
    assert all(item["status"] == "ok" for item in result)
    assert result[0]["dimensions"] == 3
    assert result[2]["top_node_id"] == "relevant"


def test_provider_smoke_rejects_unknown_provider_before_calling_cloud() -> None:
    with pytest.raises(ValueError, match="Unknown providers: image"):
        providers.run_provider_smoke(_settings(), {"image"})
