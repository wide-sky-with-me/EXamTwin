from __future__ import annotations

import asyncio
import math
import time

from llama_index.core.schema import NodeWithScore, TextNode

from examtwin.assessment.answering_agent.finalization import LiteLLMFinalAnswerProvider
from examtwin.assessment.answering_agent.tools.image_generate import LiteLLMImageProvider
from examtwin.assessment.answering_agent.tools.question_vision import LiteLLMQuestionVisionProvider
from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.config import Settings
from examtwin.platform.providers import IndexResultsReranker, build_embedding, required_secret


def build_final_answer_provider(settings: Settings) -> LiteLLMFinalAnswerProvider:
    return LiteLLMFinalAnswerProvider(
        model=settings.llm_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=required_secret(settings.llm_api_key),
        timeout=min(
            settings.answer_agent_timeout / 3,
            settings.answer_agent_finalization_timeout,
        ),
        draft_max_chars=settings.answer_agent_finalization_draft_max_chars,
        max_retries=0,
        reasoning_effort=settings.llm_reasoning_effort,
    )


def build_question_vision_provider(settings: Settings) -> LiteLLMQuestionVisionProvider:
    return LiteLLMQuestionVisionProvider(
        model=settings.paper_vision_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=required_secret(settings.llm_api_key),
        timeout=settings.paper_vision_timeout,
        question_max_chars=settings.question_vision_question_max_chars,
        max_output_tokens=settings.question_vision_max_output_tokens,
        reasoning_effort=settings.paper_vision_reasoning_effort,
    )


def build_image_generation_provider(settings: Settings) -> LiteLLMImageProvider:
    return LiteLLMImageProvider(
        model=settings.image_generation_model,
        provider=settings.litellm_provider,
        api_base=settings.image_provider_base_url,
        api_key=required_secret(settings.image_provider_api_key),
        timeout=settings.image_generation_timeout,
        max_attempts=settings.image_generation_max_attempts,
        max_output_bytes=settings.image_generation_max_output_bytes,
    )


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
                        timeout=settings.answer_agent_finalization_timeout,
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
                ranked = IndexResultsReranker(settings).rerank(
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
