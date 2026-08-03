from __future__ import annotations

from typing import Any

import httpx
from examtwin.answering_agent.finalization import LiteLLMFinalAnswerProvider
from examtwin.answering_agent.tools.image_generate import (
    OpenAICompatibleImageProvider,
)
from examtwin.answering_agent.tools.question_vision import (
    LiteLLMQuestionVisionProvider,
)
from examtwin.config import Settings
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai_like import OpenAILike


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
    return OpenAIEmbedding(
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
