from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from examtwin.api.errors import upstream_http_error
from examtwin.composition import build_rag_service, knowledge_repository
from examtwin.config import Settings, get_settings
from examtwin.schemas.knowledge import (
    AskRequest,
    AskResponse,
    DifficultyFeatures,
    DifficultyResult,
    KnowledgePointResponse,
    KnowledgeRelationResponse,
)
from examtwin.services.difficulty import calculate_difficulty
from examtwin.services.knowledge import list_knowledge_points, list_relations
from examtwin.services.subject_context import subject_context

router = APIRouter()


@router.get("/knowledge/points", response_model=list[KnowledgePointResponse])
def knowledge_points(
    unit_code: str | None = None,
    strand: str | None = None,
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    subject = subject_context(settings)
    return list_knowledge_points(
        knowledge_repository(settings),
        subject_code=subject.subject_code,
        unit_code=unit_code,
        strand=strand,
    )


@router.get("/knowledge/relations", response_model=list[KnowledgeRelationResponse])
def knowledge_relations(
    settings: Settings = Depends(get_settings),
) -> list[KnowledgeRelationResponse]:
    subject = subject_context(settings)
    return [
        KnowledgeRelationResponse.model_validate(item)
        for item in list_relations(
            knowledge_repository(settings),
            subject_code=subject.subject_code,
        )
    ]


@router.post("/knowledge/difficulty", response_model=DifficultyResult)
def difficulty(features: DifficultyFeatures) -> DifficultyResult:
    return calculate_difficulty(features)


@router.post("/rag/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    try:
        return build_rag_service(settings).ask(request)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=409,
            detail="知识索引尚未准备完成，请先构建索引",
        ) from error
    except Exception as error:
        raise upstream_http_error(
            "RAG_PROVIDER_FAILED",
            "知识检索服务暂时不可用，请稍后重试",
            error,
        ) from error
