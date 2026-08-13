from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from examtwin.app.api.dependencies import (
    get_corpus_workspace_service,
    get_subject_context,
)
from examtwin.app.api.system import _subject_response
from examtwin.app.composition import build_object_store, corpus_repository
from examtwin.contracts.common import SubjectPackResponse
from examtwin.contracts.workspaces import (
    BatchDeleteSubjectsRequest,
    BatchDeleteSubjectsResponse,
    CreateSubjectRequest,
    KnowledgeBaseBuildResponse,
    KnowledgeBaseVersionResponse,
    RenameSourceDocumentRequest,
    SourceDocumentResponse,
    UpdateSubjectRequest,
)
from examtwin.knowledge.workspace_service import (
    CorpusWorkspaceService,
    KnowledgeBaseBuildError,
    WorkspaceNotFoundError,
)
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.public import SubjectContext, subject_context, subject_package_registry
from examtwin.subjects.workspace_repository import WorkspaceRepository

router = APIRouter()


def _workspaces(settings: Settings) -> WorkspaceRepository:
    return WorkspaceRepository(create_session_factory(settings.database_url))


@router.get("/capability-profiles")
def capability_profiles(settings: Settings = Depends(get_settings)) -> list[dict[str, object]]:
    return [
        {
            "id": package.pack.id,
            "subject_code": package.pack.subject_code,
            "title": package.pack.title,
            "version": package.manifest.version,
            "answering_enabled": package.answering_enabled,
        }
        for package in subject_package_registry(settings.subject_packages_dir).all()
    ]


@router.post(
    "/subject-workspaces",
    response_model=SubjectPackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subject_workspace(
    request: CreateSubjectRequest,
    settings: Settings = Depends(get_settings),
) -> SubjectPackResponse:
    if request.capability_profile_id:
        try:
            profile = subject_package_registry(settings.subject_packages_dir).require(
                request.capability_profile_id
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if profile.pack.subject_code != request.subject_code:
            raise HTTPException(
                status_code=422,
                detail="能力模板只能绑定到相同科目代码，避免复用错误的试卷和评分规则",
            )
    try:
        values = request.model_dump(exclude={"id"})
        created = _workspaces(settings).create_subject(subject_id=request.id, **values)
        context = subject_context(settings, str(created["id"]))
        return _subject_response(context, settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch(
    "/subject-workspaces/{workspace_id}",
    response_model=SubjectPackResponse,
)
def update_subject_workspace(
    workspace_id: str,
    request: UpdateSubjectRequest,
    settings: Settings = Depends(get_settings),
) -> SubjectPackResponse:
    try:
        _workspaces(settings).update_subject_presentation(workspace_id, **request.model_dump())
        return _subject_response(subject_context(settings, workspace_id), settings)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/subject-workspaces/batch-delete",
    response_model=BatchDeleteSubjectsResponse,
)
def batch_delete_subject_workspaces(
    request: BatchDeleteSubjectsRequest,
    settings: Settings = Depends(get_settings),
) -> BatchDeleteSubjectsResponse:
    installed_ids = {
        package.pack.id for package in subject_package_registry(settings.subject_packages_dir).all()
    }
    protected = installed_ids.intersection(request.subject_ids)
    if protected:
        raise HTTPException(
            status_code=409,
            detail="内置科目工作区不能删除",
        )
    try:
        deleted_ids = _workspaces(settings).delete_subjects(request.subject_ids)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return BatchDeleteSubjectsResponse(
        deleted_ids=deleted_ids,
        deleted_count=len(deleted_ids),
    )


@router.get(
    "/subject-workspaces/{workspace_id}/documents",
    response_model=list[SourceDocumentResponse],
)
def workspace_documents(
    workspace_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> list[SourceDocumentResponse]:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")
    rows = corpus_repository(settings).list_for_api(
        source_type=None,
        status=None,
        limit=1000,
        subject_code=subject.subject_code,
    )
    return [SourceDocumentResponse.model_validate(row) for row in rows]


@router.get("/subject-workspaces/{workspace_id}/documents/{document_id}/content")
def workspace_document_content(
    workspace_id: str,
    document_id: str,
    download: bool = Query(default=False),
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> FileResponse:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")
    row = corpus_repository(settings).get_active(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    document_subject_id = str(row.get("subject_id") or "")
    if document_subject_id and document_subject_id != workspace_id:
        raise HTTPException(status_code=404, detail="资料不存在")
    if str(row.get("subject_code") or "") != subject.subject_code:
        raise HTTPException(status_code=404, detail="资料不存在")

    object_key = str(row.get("object_key") or "")
    try:
        source = (
            build_object_store(settings).materialize(object_key)
            if object_key
            else Path(str(row.get("path") or ""))
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="原文件不可用") from error
    if not source.is_file():
        raise HTTPException(status_code=404, detail="原文件不可用")

    filename = str(row.get("filename") or source.name)
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(
        source,
        filename=filename,
        media_type=media_type,
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete(
    "/subject-workspaces/{workspace_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workspace_document(
    workspace_id: str,
    document_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> None:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")
    try:
        corpus_repository(settings).archive(document_id, subject_code=subject.subject_code)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch(
    "/subject-workspaces/{workspace_id}/documents/{document_id}",
    response_model=SourceDocumentResponse,
)
def rename_workspace_document(
    workspace_id: str,
    document_id: str,
    request: RenameSourceDocumentRequest,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> SourceDocumentResponse:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")
    normalized = request.display_name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="显示名称不能为空")
    try:
        row = corpus_repository(settings).rename(
            document_id,
            subject_code=subject.subject_code,
            display_name=normalized,
        )
        return SourceDocumentResponse.model_validate(row)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/subject-workspaces/{workspace_id}/documents",
    response_model=SourceDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_workspace_document(
    workspace_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    knowledge_base_id: str | None = Form(default=None),
    license_confirmed: bool = Form(default=False),
    service: CorpusWorkspaceService = Depends(get_corpus_workspace_service),
) -> SourceDocumentResponse:
    try:
        row = service.upload_document(
            workspace_id,
            file.file,
            filename=file.filename or "upload",
            content_type=file.content_type,
            source_type=source_type,
            knowledge_base_id=knowledge_base_id,
            license_confirmed=license_confirmed,
        )
        return SourceDocumentResponse.model_validate(row)
    except WorkspaceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post(
    "/knowledge-bases/{knowledge_base_id}/build",
    response_model=KnowledgeBaseBuildResponse,
)
def build_knowledge_base(
    knowledge_base_id: str,
    service: CorpusWorkspaceService = Depends(get_corpus_workspace_service),
) -> KnowledgeBaseBuildResponse:
    try:
        result = service.build_knowledge_base(knowledge_base_id)
    except KnowledgeBaseBuildError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return KnowledgeBaseBuildResponse(
        version=KnowledgeBaseVersionResponse.model_validate(result.version),
        processed=result.index_result.processed,
        succeeded=result.index_result.succeeded,
        failed=result.index_result.failed,
        errors=result.index_result.errors,
    )
