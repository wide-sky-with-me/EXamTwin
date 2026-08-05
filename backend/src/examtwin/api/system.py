from __future__ import annotations

from fastapi import APIRouter, Depends

from examtwin.api.dependencies import get_subject_context
from examtwin.composition import dashboard_repository
from examtwin.config import Settings, get_settings
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.schemas.common import (
    HealthResponse,
    InfrastructureHealthResponse,
    PlatformStatusResponse,
    StatsResponse,
    SubjectPackResponse,
    SubjectStatusResponse,
    SubjectUnitResponse,
)
from examtwin.services.health import infrastructure_health
from examtwin.services.inventory import corpus_stats
from examtwin.services.subject_context import SubjectContext, all_subject_contexts
from examtwin.services.subject_status import subject_statuses

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


def _subject_response(subject: SubjectContext) -> SubjectPackResponse:
    package = subject.package
    pack = package.pack
    return SubjectPackResponse(
        id=pack.id,
        version=package.manifest.version,
        digest=package.digest,
        subject_code=pack.subject_code,
        title=pack.title,
        board_name=pack.board.name,
        answering_enabled=package.answering_enabled,
        answering_disabled_reason=package.answering_disabled_reason,
        units=[
            SubjectUnitResponse(code=unit.code, title=unit.title, strand=unit.strand)
            for unit in pack.unit_rules
        ],
    )


@router.get("/subjects", response_model=list[SubjectPackResponse])
def subjects(settings: Settings = Depends(get_settings)) -> list[SubjectPackResponse]:
    return [_subject_response(subject) for subject in all_subject_contexts(settings)]


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
    subject: SubjectContext = Depends(get_subject_context),
) -> SubjectPackResponse:
    return _subject_response(subject)


@router.get("/stats", response_model=StatsResponse)
def stats(
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> StatsResponse:
    return StatsResponse.model_validate(
        corpus_stats(dashboard_repository(settings), subject_code=subject.subject_code)
    )
