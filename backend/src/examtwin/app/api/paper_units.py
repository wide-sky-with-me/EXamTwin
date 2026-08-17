from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from starlette.concurrency import run_in_threadpool

from examtwin.app.api.dependencies import get_paper_units, get_subject_context
from examtwin.app.composition import build_object_store, build_paper_job_service
from examtwin.assessment.paper_units import PaperUnitService
from examtwin.contracts.paper_units import (
    CreatePaperUnitAnswerRequest,
    CreatePaperUnitRequest,
    PaperUnitAnswerCreated,
    PaperUnitListResponse,
    PaperUnitSummary,
    UpdatePaperUnitRequest,
)
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import SubjectContext
from examtwin.subjects.workspace_repository import WorkspaceRepository

router = APIRouter()


def _require_workspace(workspace_id: str, subject: SubjectContext) -> None:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")


def _document_path(settings: Settings, document: dict[str, object]) -> Path:
    object_key = str(document.get("object_key") or "")
    if object_key:
        try:
            return build_object_store(settings).materialize(object_key)
        except LookupError as error:
            raise ValueError("Question Paper 原始文件不可用") from error
    path = Path(str(document.get("path") or ""))
    if not path.is_file():
        raise ValueError("Question Paper 原始文件不可用")
    return path


@router.get(
    "/subject-workspaces/{workspace_id}/paper-units",
    response_model=PaperUnitListResponse,
)
def list_paper_units(
    workspace_id: str,
    query: str | None = Query(default=None, alias="q", max_length=200),
    unit_code: str | None = Query(default=None, max_length=32),
    exam_year: int | None = Query(default=None, ge=1900, le=2200),
    exam_session: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitListResponse:
    _require_workspace(workspace_id, subject)
    items, total, facets = service.list_units(
        query=query,
        unit_code=unit_code,
        exam_year=exam_year,
        exam_session=exam_session,
        limit=limit,
        offset=offset,
    )
    return PaperUnitListResponse(
        items=[PaperUnitSummary.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        available_units=[str(item) for item in facets["units"]],
        available_years=[int(item) for item in facets["years"]],
        available_sessions=[str(item) for item in facets["sessions"]],
    )


@router.get(
    "/subject-workspaces/{workspace_id}/paper-units/trash",
    response_model=PaperUnitListResponse,
)
def list_trashed_paper_units(
    workspace_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitListResponse:
    _require_workspace(workspace_id, subject)
    items, total, facets = service.list_trash(limit=limit, offset=offset)
    return PaperUnitListResponse(
        items=[PaperUnitSummary.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        available_units=[str(item) for item in facets["units"]],
        available_years=[int(item) for item in facets["years"]],
        available_sessions=[str(item) for item in facets["sessions"]],
    )


@router.post(
    "/subject-workspaces/{workspace_id}/paper-units",
    response_model=PaperUnitSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_paper_unit(
    workspace_id: str,
    request: CreatePaperUnitRequest,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitSummary:
    _require_workspace(workspace_id, subject)
    try:
        return PaperUnitSummary.model_validate(
            service.create_unit(request.document_ids, display_name=request.display_name)
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
    response_model=PaperUnitSummary,
)
def get_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitSummary:
    _require_workspace(workspace_id, subject)
    try:
        return PaperUnitSummary.model_validate(service.get_unit(paper_unit_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
    response_model=PaperUnitSummary,
)
def update_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    request: UpdatePaperUnitRequest,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitSummary:
    _require_workspace(workspace_id, subject)
    try:
        return PaperUnitSummary.model_validate(
            service.update_unit(
                paper_unit_id,
                display_name=request.display_name,
                display_name_set="display_name" in request.model_fields_set,
                document_ids=request.document_ids,
            )
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def archive_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> Response:
    _require_workspace(workspace_id, subject)
    try:
        service.archive_unit(paper_unit_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}/restore",
    response_model=PaperUnitSummary,
)
def restore_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitSummary:
    _require_workspace(workspace_id, subject)
    try:
        return PaperUnitSummary.model_validate(service.restore_unit(paper_unit_id))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
)
def permanently_delete_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> Response:
    _require_workspace(workspace_id, subject)
    try:
        service.permanently_delete_unit(paper_unit_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}/answer",
    response_model=PaperUnitAnswerCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def answer_paper_unit(
    workspace_id: str,
    paper_unit_id: str,
    request: CreatePaperUnitAnswerRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitAnswerCreated:
    _require_workspace(workspace_id, subject)
    try:
        paper, booklet = service.answer_sources(
            paper_unit_id,
            question_paper_document_id=request.question_paper_document_id,
            source_booklet_document_id=request.source_booklet_document_id,
        )
        workspaces = WorkspaceRepository(create_session_factory(settings.database_url))
        snapshot = (
            workspaces.retrieval_snapshot_for_versions(
                subject.id,
                request.knowledge_base_version_ids,
            )
            if request.knowledge_base_version_ids
            else workspaces.active_retrieval_snapshot(
                subject.id,
                include_supplementary=request.include_supplementary,
            )
        )
        collections = tuple(str(item) for item in snapshot["collections"])
        if not collections:
            raise ValueError("整卷作答前必须先构建并发布知识库版本")
        selected_subject = subject.with_retrieval_snapshot(
            version_ids=tuple(str(item) for item in snapshot["version_ids"]),
            collections=collections,
            graph_version_id=snapshot.get("graph_version_id"),
        )
        source_path = _document_path(settings, paper)
        jobs = build_paper_job_service(settings, selected_subject)
        with source_path.open("rb") as stream:
            created = await run_in_threadpool(
                jobs.create_job_from_stream,
                str(paper.get("filename") or source_path.name),
                stream,
                unit_code=str(paper.get("unit_code") or "") or None,
                source_booklet=booklet,
                paper_unit_id=paper_unit_id,
                question_paper_document_id=str(paper["id"]),
            )
        return PaperUnitAnswerCreated(
            **created.model_dump(),
            paper_unit_id=paper_unit_id,
            question_paper_document_id=str(paper["id"]),
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}/import-answer",
    response_model=PaperUnitAnswerCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_paper_unit_answer(
    workspace_id: str,
    paper_unit_id: str,
    answer_file: UploadFile = File(...),
    question_paper_document_id: str = Form(...),
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
    service: PaperUnitService = Depends(get_paper_units),
) -> PaperUnitAnswerCreated:
    """Import a human/external answer against the exact managed paper unit."""

    _require_workspace(workspace_id, subject)
    try:
        paper, booklet = service.answer_sources(
            paper_unit_id,
            question_paper_document_id=question_paper_document_id,
            source_booklet_document_id=None,
        )
        workspaces = WorkspaceRepository(create_session_factory(settings.database_url))
        snapshot = workspaces.active_retrieval_snapshot(subject.id)
        collections = tuple(str(item) for item in snapshot["collections"])
        if not collections:
            raise ValueError("导入答卷前必须先构建并发布知识库版本")
        selected_subject = subject.with_retrieval_snapshot(
            version_ids=tuple(str(item) for item in snapshot["version_ids"]),
            collections=collections,
            graph_version_id=snapshot.get("graph_version_id"),
        )
        source_path = _document_path(settings, paper)
        jobs = build_paper_job_service(settings, selected_subject)
        with source_path.open("rb") as stream:
            created = await run_in_threadpool(
                jobs.create_job_from_stream,
                str(paper.get("filename") or source_path.name),
                stream,
                unit_code=str(paper.get("unit_code") or "") or None,
                answer_filename=answer_file.filename or "answers.pdf",
                answer_stream=answer_file.file,
                source_booklet=booklet,
                paper_unit_id=paper_unit_id,
                question_paper_document_id=str(paper["id"]),
            )
        return PaperUnitAnswerCreated(
            **created.model_dump(),
            paper_unit_id=paper_unit_id,
            question_paper_document_id=str(paper["id"]),
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
