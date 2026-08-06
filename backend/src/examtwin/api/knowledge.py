from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from examtwin.api.dependencies import get_subject_context
from examtwin.api.errors import upstream_http_error
from examtwin.composition import build_rag_service, knowledge_repository
from examtwin.config import Settings, get_settings
from examtwin.persistence.session import create_session_factory
from examtwin.persistence.workspace_repository import WorkspaceRepository
from examtwin.schemas.knowledge import (
    AskRequest,
    AskResponse,
    KnowledgePointResponse,
    KnowledgeRelationResponse,
)
from examtwin.services.knowledge import list_knowledge_points, list_relations
from examtwin.services.subject_context import SubjectContext

router = APIRouter()


@router.get("/knowledge/points", response_model=list[KnowledgePointResponse])
def knowledge_points(
    unit_code: str | None = None,
    strand: str | None = None,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> list[dict]:
    return list_knowledge_points(
        knowledge_repository(settings),
        subject_code=subject.subject_code,
        unit_code=unit_code,
        strand=strand,
    )


@router.get("/knowledge/relations", response_model=list[KnowledgeRelationResponse])
def knowledge_relations(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> list[KnowledgeRelationResponse]:
    return [
        KnowledgeRelationResponse.model_validate(item)
        for item in list_relations(
            knowledge_repository(settings),
            subject_code=subject.subject_code,
        )
    ]


@router.post("/rag/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> AskResponse:
    try:
        subject.require(request.subject_code)
        repository = WorkspaceRepository(create_session_factory(settings.database_url))
        snapshot = (
            repository.retrieval_snapshot_for_versions(
                subject.id, request.knowledge_base_version_ids
            )
            if request.knowledge_base_version_ids
            else repository.active_retrieval_snapshot(
                subject.id, include_supplementary=request.include_supplementary
            )
        )
        collections = tuple(str(item) for item in snapshot["collections"])
        if not collections:
            raise FileNotFoundError("当前科目没有已发布的知识库版本")
        selected_subject = subject.with_retrieval_snapshot(
            version_ids=tuple(str(item) for item in snapshot["version_ids"]),
            collections=collections,
            graph_version_id=snapshot.get("graph_version_id"),
        )
        return build_rag_service(settings, selected_subject).ask(request)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
