from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from examtwin.api.errors import api_http_error, guarded_api_call
from examtwin.composition import (
    build_corpus_ingestor,
    corpus_repository,
    knowledge_repository,
    vector_index_repository,
)
from examtwin.config import Settings, get_settings
from examtwin.schemas.common import (
    ConvertRequest,
    IndexRequest,
    InventoryRequest,
    InventoryResponse,
    JobResult,
)
from examtwin.schemas.knowledge import (
    SourceContextResponse,
)
from examtwin.services.ingestion import build_vector_index
from examtwin.services.inventory import scan_corpus
from examtwin.services.source_context import source_context
from examtwin.services.subject_context import subject_context

router = APIRouter()


@router.post("/corpus/inventory", response_model=InventoryResponse)
def inventory(
    _request: InventoryRequest,
    settings: Settings = Depends(get_settings),
) -> InventoryResponse:
    def operation() -> InventoryResponse:
        subject = subject_context(settings)
        return InventoryResponse.model_validate(
            scan_corpus(corpus_repository(settings), subject.corpus_dir, subject.pack)
        )

    return guarded_api_call(
        operation,
        code="CORPUS_INVENTORY_FAILED",
        message="语料清点失败，请检查资料目录后重试",
    )


@router.get("/corpus/documents")
def documents(
    source_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    return guarded_api_call(
        lambda: corpus_repository(settings).list_for_api(
            source_type=source_type,
            status=status,
            limit=limit,
        ),
        code="CORPUS_DOCUMENTS_FAILED",
        message="资料列表暂时不可用，请稍后重试",
    )


@router.get("/sources/{document_id}/context", response_model=SourceContextResponse)
def source_document_context(
    document_id: str,
    page: int | None = Query(default=None, ge=1),
    query: str = Query(default="", max_length=500),
    settings: Settings = Depends(get_settings),
) -> SourceContextResponse:
    try:
        return source_context(
            corpus_repository(settings), settings, document_id, page=page, query=query
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise api_http_error(
            "SOURCE_CONTEXT_FAILED",
            "资料原文暂时不可用，请稍后重试",
            error,
            status_code=500,
        ) from error


@router.post("/corpus/convert", response_model=JobResult)
def convert(
    request: ConvertRequest,
    settings: Settings = Depends(get_settings),
) -> JobResult:
    return guarded_api_call(
        lambda: build_corpus_ingestor(settings).convert_batch(
            document_ids=request.document_ids,
            source_types=request.source_types,
            authority_tiers=request.authority_tiers,
            limit=request.limit,
            workers=request.workers,
            force=request.force,
        ),
        code="CORPUS_CONVERSION_FAILED",
        message="资料转换服务暂时不可用，请稍后重试",
        status_code=502,
    )


@router.post("/corpus/index", response_model=JobResult)
def index(
    request: IndexRequest,
    settings: Settings = Depends(get_settings),
) -> JobResult:
    return guarded_api_call(
        lambda: build_vector_index(
            settings,
            subject_context(settings),
            vector_index_repository(settings),
            knowledge_repository(settings),
            limit=request.limit,
        ),
        code="VECTOR_INDEX_FAILED",
        message="知识索引服务暂时不可用，请稍后重试",
        status_code=502,
    )
