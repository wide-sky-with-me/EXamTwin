from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.embeddings.openai import OpenAIEmbedding

from examtwin.platform.config import Settings
from examtwin.platform.litellm_provider import LiteLLMChatModel

logger = logging.getLogger(__name__)


def _is_retryable_embedding_parameter_error(error: Exception) -> bool:
    detail = str(error).lower()
    # SiliconFlow has intermittently returned its provider code 20015 for an
    # otherwise valid batch. Do not broaden this to arbitrary HTTP 400/model
    # errors: those are deterministic and must fail after one request.
    return "20015" in detail and "parameter" in detail and "invalid" in detail


def _embedding_batch_with_fallback(
    fetch: Callable[[list[str]], list[list[float]]],
    texts: list[str],
    *,
    max_attempts: int = 3,
    pause: Callable[[float], None] = time.sleep,
) -> list[list[float]]:
    """Retry a compatible provider's transient parameter rejection and isolate bad input."""

    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return fetch(texts)
        except Exception as error:
            if not _is_retryable_embedding_parameter_error(error):
                raise
            last_error = error
            logger.warning(
                "embedding_parameter_retry batch_size=%d attempt=%d",
                len(texts),
                attempt,
            )
            if attempt < max_attempts:
                pause(float(attempt))

    if len(texts) > 1:
        midpoint = len(texts) // 2
        return [
            *_embedding_batch_with_fallback(
                fetch,
                texts[:midpoint],
                max_attempts=max_attempts,
                pause=pause,
            ),
            *_embedding_batch_with_fallback(
                fetch,
                texts[midpoint:],
                max_attempts=max_attempts,
                pause=pause,
            ),
        ]

    fingerprint = hashlib.sha256(texts[0].encode("utf-8")).hexdigest()[:12]
    raise RuntimeError(
        "Embedding provider rejected one input after bounded retries: "
        f"chars={len(texts[0])}, sha256={fingerprint}"
    ) from last_error


class ResilientEmbedding(OpenAIEmbedding):
    """Embedding adapter with bounded provider-400 recovery."""

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return _embedding_batch_with_fallback(super()._get_text_embeddings, texts)


def required_secret(value: Any) -> str:
    if value is None:
        raise RuntimeError("Required API credential is not configured")
    return value.get_secret_value()


def build_chat_model(
    settings: Settings,
    *,
    model: str | None = None,
    timeout: float = 120,
    max_retries: int = 1,
    reasoning_effort: str | None = None,
) -> LiteLLMChatModel:
    return LiteLLMChatModel(
        model=model or settings.llm_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=required_secret(settings.llm_api_key),
        reasoning_effort=reasoning_effort or settings.llm_reasoning_effort,
        timeout=timeout,
        max_retries=max_retries,
    )


def build_embedding(
    settings: Settings,
    *,
    timeout: float | None = None,
    max_retries: int = 0,
) -> OpenAIEmbedding:
    return ResilientEmbedding(
        model_name=settings.embedding_model,
        api_base=settings.retrieval_base_url,
        api_key=required_secret(settings.retrieval_api_key),
        embed_batch_size=settings.embedding_batch_size,
        timeout=timeout if timeout is not None else settings.embedding_timeout,
        max_retries=max_retries,
    )


class IndexResultsReranker:
    def __init__(self, settings: Settings, *, timeout: float | None = None):
        self.url = f"{settings.retrieval_base_url.rstrip('/')}{settings.rerank_path}"
        self.api_key = required_secret(settings.retrieval_api_key)
        self.model = settings.rerank_model
        self.timeout = timeout if timeout is not None else settings.rerank_timeout
        self.document_max_chars = settings.rerank_document_max_chars

    def rerank(
        self,
        query: str | QueryBundle,
        nodes: list[NodeWithScore],
        *,
        top_n: int,
    ) -> list[NodeWithScore]:
        if not nodes:
            return []
        query_text = query.query_str if isinstance(query, QueryBundle) else query
        documents = [
            str(node.node.metadata.get("retrieval_text") or node.node.get_content())[
                : self.document_max_chars
            ]
            for node in nodes
        ]
        response = httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "query": query_text,
                "documents": documents,
                "top_n": min(top_n, len(documents)),
                "return_documents": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        reranked: list[NodeWithScore] = []
        for item in results:
            index = int(item["index"])
            if 0 <= index < len(nodes):
                reranked.append(
                    NodeWithScore(
                        node=nodes[index].node,
                        score=float(item.get("relevance_score", 0)),
                    )
                )
        return reranked
