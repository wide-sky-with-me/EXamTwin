from __future__ import annotations

from fastapi import APIRouter, Depends

from examtwin.composition import dashboard_repository
from examtwin.config import Settings, get_settings
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.schemas.common import (
    HealthResponse,
    InfrastructureHealthResponse,
    StatsResponse,
    SubjectPackResponse,
    SubjectUnitResponse,
)
from examtwin.services.health import infrastructure_health
from examtwin.services.inventory import corpus_stats
from examtwin.services.subject_context import subject_context

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    subject = subject_context(settings)
    infrastructure = infrastructure_health(settings)
    return HealthResponse(
        status="ok" if infrastructure.available else "degraded",
        subject_code=subject.subject_code,
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


@router.get("/subject", response_model=SubjectPackResponse)
def subject_metadata(settings: Settings = Depends(get_settings)) -> SubjectPackResponse:
    package = subject_context(settings).package
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


@router.get("/stats", response_model=StatsResponse)
def stats(settings: Settings = Depends(get_settings)) -> StatsResponse:
    return StatsResponse.model_validate(corpus_stats(dashboard_repository(settings)))
