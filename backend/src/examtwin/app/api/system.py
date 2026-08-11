from __future__ import annotations

from fastapi import APIRouter, Depends

from examtwin.app.api.dependencies import get_subject_context
from examtwin.app.composition import dashboard_repository
from examtwin.contracts.common import (
    HealthResponse,
    InfrastructureHealthResponse,
    PlatformStatusResponse,
    StatsResponse,
    SubjectKnowledgeBaseResponse,
    SubjectPackResponse,
    SubjectStatusResponse,
    SubjectUnitResponse,
)
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.knowledge.inventory import corpus_stats
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import create_session_factory
from examtwin.platform.health import infrastructure_health
from examtwin.subjects.public import SubjectContext, all_subject_contexts
from examtwin.subjects.status import subject_statuses
from examtwin.subjects.workspace_repository import WorkspaceRepository

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    infrastructure = infrastructure_health(settings)
    return HealthResponse(
        status="ok" if infrastructure.available else "degraded",
        subject_code=None,
        api_contract_version=API_CONTRACT_VERSION,
        capabilities=list(API_CAPABILITIES),
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        rerank_model=settings.rerank_model,
        credentials={
            "mineru": settings.mineru_token is not None,
            "llm": settings.llm_provider_api_key is not None,
            "image_generation": (
                settings.image_generation_enabled and settings.image_provider_api_key is not None
            ),
            "siliconflow": settings.siliconflow_api_key is not None,
        },
        object_storage_backend=settings.object_store_backend,
        infrastructure=InfrastructureHealthResponse(
            postgresql=infrastructure.postgresql,
            qdrant=infrastructure.qdrant,
            object_storage=infrastructure.object_storage,
        ),
    )


def _subject_response(subject: SubjectContext, settings: Settings) -> SubjectPackResponse:
    package = subject.package
    pack = package.pack
    workspace = WorkspaceRepository(create_session_factory(settings.database_url)).resolve_subject(
        subject.id
    ) or {"knowledge_bases": []}
    return SubjectPackResponse(
        id=subject.id,
        version=package.manifest.version,
        digest=package.digest,
        subject_code=pack.subject_code,
        title=str(workspace.get("title") or pack.title),
        board_name=str(workspace.get("board_name") or subject.board_name),
        icon=str(workspace.get("icon") or "book-open"),
        color=str(workspace.get("color") or "#2F6FED"),
        capability_profile_id=subject.capability_profile_id,
        generic_qa_enabled=True,
        answering_enabled=subject.paper_answering_enabled,
        answering_disabled_reason=subject.answering_disabled_reason,
        active_graph_version_id=subject.graph_version_id,
        knowledge_bases=[
            SubjectKnowledgeBaseResponse(
                id=str(base["id"]),
                name=str(base["name"]),
                kind=str(base["kind"]),
                active_version_id=(
                    str(base["active_version_id"]) if base.get("active_version_id") else None
                ),
                active_version_number=(base.get("active_version") or {}).get("version_number"),
                status=str((base.get("active_version") or {}).get("status", "empty")),
                vector_points=int((base.get("active_version") or {}).get("vector_points", 0)),
            )
            for base in workspace.get("knowledge_bases", [])
        ],
        units=[
            SubjectUnitResponse(code=unit.code, title=unit.title, strand=unit.strand)
            for unit in pack.unit_rules
        ],
    )


@router.get("/subjects", response_model=list[SubjectPackResponse])
def subjects(settings: Settings = Depends(get_settings)) -> list[SubjectPackResponse]:
    return [_subject_response(subject, settings) for subject in all_subject_contexts(settings)]


@router.get("/subjects/status", response_model=PlatformStatusResponse)
def platform_status(settings: Settings = Depends(get_settings)) -> PlatformStatusResponse:
    infrastructure = infrastructure_health(settings)
    return PlatformStatusResponse(
        infrastructure=InfrastructureHealthResponse(
            postgresql=infrastructure.postgresql,
            qdrant=infrastructure.qdrant,
            object_storage=infrastructure.object_storage,
        ),
        subjects=[
            SubjectStatusResponse.model_validate(item)
            for item in subject_statuses(settings, dashboard_repository(settings))
        ],
    )


@router.get("/subject", response_model=SubjectPackResponse)
def subject_metadata(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> SubjectPackResponse:
    return _subject_response(subject, settings)


@router.get("/stats", response_model=StatsResponse)
def stats(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> StatsResponse:
    return StatsResponse.model_validate(
        corpus_stats(dashboard_repository(settings), subject_code=subject.subject_code)
    )
