from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

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


@router.post("/corpus/inventory")
def inventory(
    _request: InventoryRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    subject = subject_context(settings)
    return scan_corpus(corpus_repository(settings), subject.corpus_dir, subject.pack)


@router.get("/corpus/documents")
def documents(
    source_type: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    return corpus_repository(settings).list_for_api(
        source_type=source_type,
        status=status,
        limit=limit,
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


@router.post("/corpus/convert", response_model=JobResult)
def convert(
    request: ConvertRequest,
    settings: Settings = Depends(get_settings),
) -> JobResult:
    return build_corpus_ingestor(settings).convert_batch(
        document_ids=request.document_ids,
        source_types=request.source_types,
        authority_tiers=request.authority_tiers,
        limit=request.limit,
        workers=request.workers,
        force=request.force,
    )


@router.post("/corpus/index", response_model=JobResult)
def index(
    request: IndexRequest,
    settings: Settings = Depends(get_settings),
) -> JobResult:
    return build_vector_index(
        settings,
        subject_context(settings),
        vector_index_repository(settings),
        knowledge_repository(settings),
        limit=request.limit,
    )
