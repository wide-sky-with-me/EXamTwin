from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from collections.abc import Callable
from typing import Any

import httpx
from examtwin.agent_harness.model import HarnessMessage
from examtwin.answering_agent.finalization import LiteLLMFinalAnswerProvider
from examtwin.answering_agent.tools.image_generate import (
    OpenAICompatibleImageProvider,
)
from examtwin.answering_agent.tools.question_vision import (
    LiteLLMQuestionVisionProvider,
)
from examtwin.config import Settings
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai_like import OpenAILike

logger = logging.getLogger(__name__)


def _is_siliconflow_parameter_error(error: Exception) -> bool:
    detail = str(error).lower()
    return "20015" in detail or "parameter is invalid" in detail


def _embedding_batch_with_fallback(
    fetch: Callable[[list[str]], list[list[float]]],
    texts: list[str],
    *,
    max_attempts: int = 3,
    pause: Callable[[float], None] = time.sleep,
) -> list[list[float]]:
    """Retry SiliconFlow's transient 20015 and isolate a truly invalid input."""

    last_error: Exception | None = None
    for attempt in range(1, max(1, max_attempts) + 1):
        try:
            return fetch(texts)
        except Exception as error:
            if not _is_siliconflow_parameter_error(error):
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


class ResilientOpenAIEmbedding(OpenAIEmbedding):
    """OpenAI-compatible embedding adapter with bounded provider-400 recovery."""

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return _embedding_batch_with_fallback(super()._get_text_embeddings, texts)


def _secret(value: Any) -> str:
    if value is None:
        raise RuntimeError("Required API credential is not configured")
    return value.get_secret_value()


def build_llm(
    settings: Settings,
    *,
    grading: bool = False,
    model: str | None = None,
    timeout: float = 120,
    max_retries: int = 3,
    reasoning_effort: str | None = None,
    additional_kwargs: dict[str, Any] | None = None,
) -> OpenAILike:
    resolved_model = model or (settings.grading_model if grading else settings.llm_model)
    resolved_kwargs = dict(additional_kwargs or {})
    if resolved_model.startswith("gpt-5.6"):
        resolved_kwargs.setdefault(
            "reasoning_effort",
            reasoning_effort
            or (settings.grading_reasoning_effort if grading else settings.llm_reasoning_effort),
        )
    return OpenAILike(
        model=resolved_model,
        api_base=settings.llm_provider_base_url,
        api_key=_secret(settings.llm_provider_api_key),
        context_window=131072,
        is_chat_model=True,
        is_function_calling_model=False,
        temperature=1 if resolved_model.startswith("gpt-5.6") else (0.1 if grading else 0.2),
        additional_kwargs=resolved_kwargs,
        max_retries=max_retries,
        timeout=timeout,
    )


def build_final_answer_provider(settings: Settings) -> LiteLLMFinalAnswerProvider:
    return LiteLLMFinalAnswerProvider(
        model=settings.llm_model,
        api_base=settings.llm_provider_base_url,
        api_key=_secret(settings.llm_provider_api_key),
        timeout=min(settings.answer_agent_timeout / 3, 45),
        max_retries=0,
        reasoning_effort=settings.llm_reasoning_effort,
    )


def build_question_vision_provider(settings: Settings) -> LiteLLMQuestionVisionProvider:
    return LiteLLMQuestionVisionProvider(
        model=settings.paper_vision_model,
        api_base=settings.llm_provider_base_url,
        api_key=_secret(settings.llm_provider_api_key),
        timeout=settings.paper_vision_timeout,
        reasoning_effort=settings.paper_vision_reasoning_effort,
    )


def build_image_generation_provider(settings: Settings) -> OpenAICompatibleImageProvider:
    return OpenAICompatibleImageProvider(
        model=settings.image_generation_model,
        api_base=settings.image_provider_base_url,
        api_key=_secret(settings.image_provider_api_key),
        timeout=settings.image_generation_timeout,
        max_attempts=settings.image_generation_max_attempts,
        max_output_bytes=settings.image_generation_max_output_bytes,
    )


def build_embedding(settings: Settings) -> OpenAIEmbedding:
    return ResilientOpenAIEmbedding(
        model_name=settings.embedding_model,
        api_base=settings.siliconflow_base_url,
        api_key=_secret(settings.siliconflow_api_key),
        embed_batch_size=16,
        timeout=settings.embedding_timeout,
        max_retries=1,
    )


class SiliconFlowReranker:
    def __init__(self, settings: Settings):
        self.url = f"{settings.siliconflow_base_url.rstrip('/')}/rerank"
        self.api_key = _secret(settings.siliconflow_api_key)
        self.model = settings.rerank_model
        self.timeout = settings.rerank_timeout

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
            str(node.node.metadata.get("retrieval_text") or node.node.get_content())[:20_000]
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


def run_provider_smoke(
    settings: Settings,
    providers: set[str],
) -> list[dict[str, object]]:
    """Exercise configured core model providers with bounded, billable requests."""

    supported = {"llm", "embedding", "rerank"}
    unknown = providers - supported
    if unknown:
        raise ValueError(f"Unknown providers: {', '.join(sorted(unknown))}")

    results: list[dict[str, object]] = []
    for provider in sorted(providers):
        started = time.perf_counter()
        try:
            if provider == "llm":
                payload = asyncio.run(
                    build_final_answer_provider(settings).finalize(
                        (
                            HarnessMessage(
                                role="user",
                                content=(
                                    "Provider connectivity check. Return a concise public answer "
                                    "containing the word EXAMTWIN_OK and no citation."
                                ),
                            ),
                        ),
                        allowed_citation_ids=(),
                        timeout=30,
                    )
                )
                if "EXAMTWIN_OK" not in payload.answer_markdown:
                    raise ValueError("LLM response did not contain the smoke-test marker")
                detail: dict[str, object] = {
                    "model": settings.llm_model,
                    "answer_chars": len(payload.answer_markdown),
                }
            elif provider == "embedding":
                vector = build_embedding(settings).get_text_embedding(
                    "ExamTwin provider connectivity check"
                )
                if not vector or not all(math.isfinite(float(value)) for value in vector):
                    raise ValueError("Embedding response is empty or non-finite")
                detail = {
                    "model": settings.embedding_model,
                    "dimensions": len(vector),
                }
            else:
                nodes = [
                    NodeWithScore(
                        node=TextNode(id_="relevant", text="Algebra solves equations."),
                        score=0,
                    ),
                    NodeWithScore(
                        node=TextNode(id_="irrelevant", text="Clouds can produce rain."),
                        score=0,
                    ),
                ]
                ranked = SiliconFlowReranker(settings).rerank(
                    "How do I solve an algebra equation?",
                    nodes,
                    top_n=1,
                )
                if len(ranked) != 1:
                    raise ValueError("Reranker did not return exactly one result")
                detail = {
                    "model": settings.rerank_model,
                    "top_node_id": ranked[0].node.node_id,
                }
        except Exception as error:
            raise RuntimeError(
                f"{provider} provider smoke failed ({type(error).__name__})"
            ) from error

        results.append(
            {
                "provider": provider,
                "status": "ok",
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                **detail,
            }
        )
    return results
