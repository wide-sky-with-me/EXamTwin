from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pypdf import PdfReader

from examtwin.api.dependencies import get_subject_context
from examtwin.api.system import _subject_response
from examtwin.composition import (
    build_corpus_ingestor,
    build_object_store,
    corpus_repository,
    knowledge_repository,
    vector_index_repository,
)
from examtwin.config import Settings, get_settings
from examtwin.persistence.session import create_session_factory
from examtwin.persistence.workspace_repository import (
    ASSESSMENT_SOURCE_TYPES,
    KNOWLEDGE_SOURCE_TYPES,
    WorkspaceRepository,
)
from examtwin.schemas.common import SubjectPackResponse
from examtwin.schemas.workspaces import (
    CreateSubjectRequest,
    KnowledgeBaseBuildResponse,
    KnowledgeBaseVersionResponse,
    SourceDocumentResponse,
)
from examtwin.services.ingestion import build_vector_index
from examtwin.services.inventory import parse_exam_identity
from examtwin.services.subject_context import SubjectContext, subject_context
from examtwin.storage import ObjectMetadata
from examtwin.subject_packages import subject_package_registry

router = APIRouter()
SUPPORTED_UPLOAD_SUFFIXES = frozenset({".pdf", ".md", ".markdown", ".ppt", ".pptx"})


def _workspaces(settings: Settings) -> WorkspaceRepository:
    return WorkspaceRepository(create_session_factory(settings.database_url))


def _authority_tier(source_type: str, license_confirmed: bool) -> str:
    if source_type in {"syllabus", "question_paper", "insert", "mark_scheme", "examiner_report"}:
        return "official"
    if source_type == "textbook" and license_confirmed:
        return "licensed_core"
    return "supplementary"


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
        created = _workspaces(settings).create_subject(**request.model_dump())
        context = subject_context(settings, str(created["id"]))
        return _subject_response(context, settings)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


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
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> SourceDocumentResponse:
    if workspace_id != subject.id:
        raise HTTPException(status_code=404, detail="科目工作区不存在")
    if source_type not in KNOWLEDGE_SOURCE_TYPES | ASSESSMENT_SOURCE_TYPES | {"other"}:
        raise HTTPException(status_code=422, detail="未知资料类型")
    workspace = _workspaces(settings).require_subject(workspace_id)
    role = "excluded"
    if source_type in ASSESSMENT_SOURCE_TYPES:
        knowledge_base_id = None
        role = "assessment_only"
    elif source_type in KNOWLEDGE_SOURCE_TYPES:
        if knowledge_base_id is None:
            expected_kind = "core" if source_type in {"syllabus", "textbook"} else "supplementary"
            knowledge_base_id = next(
                base["id"] for base in workspace["knowledge_bases"] if base["kind"] == expected_kind
            )
        selected_base = next(
            (base for base in workspace["knowledge_bases"] if base["id"] == knowledge_base_id),
            None,
        )
        if selected_base is None:
            raise HTTPException(status_code=422, detail="知识库不存在于当前科目")
        role = "core_knowledge" if selected_base["kind"] == "core" else "supplementary_knowledge"
    if source_type == "textbook" and not license_confirmed:
        raise HTTPException(status_code=422, detail="教材必须确认已获授权后才能进入知识库")
    if role == "core_knowledge" and source_type not in {"syllabus", "textbook"}:
        raise HTTPException(status_code=422, detail="核心知识库只接受考纲和已授权教材")
    if role == "supplementary_knowledge" and source_type == "syllabus":
        raise HTTPException(status_code=422, detail="考纲必须归属核心知识库")
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=422, detail="仅支持 PDF、Markdown、PPT 或 PPTX 资料")

    digest = hashlib.sha256()
    size = 0
    while chunk := file.file.read(1024 * 1024):
        size += len(chunk)
        if size > settings.knowledge_upload_max_bytes:
            raise HTTPException(status_code=422, detail="资料文件超过允许的上传大小")
        digest.update(chunk)
    if size == 0:
        raise HTTPException(status_code=422, detail="上传文件为空")
    checksum = digest.hexdigest()
    file.file.seek(0)

    repository = corpus_repository(settings)
    existing = repository.find_by_checksum(
        subject_code=subject.subject_code,
        source_type=source_type,
        checksum=checksum,
    )
    identity = {
        "pair_key": None,
        "unit_code": None,
        "exam_year": None,
        "exam_session": None,
        "identity_status": "not_applicable",
        "identity_error": None,
    }
    if source_type in ASSESSMENT_SOURCE_TYPES:
        identity = parse_exam_identity(Path(filename), source_type, subject.pack)
        if existing is not None and existing.get("identity_status") == "complete":
            incoming_pair = identity.get("pair_key")
            existing_pair = existing.get("pair_key")
            if identity.get("identity_status") == "complete" and incoming_pair != existing_pair:
                raise HTTPException(
                    status_code=422,
                    detail="重复资料的考试身份与已有记录冲突",
                )
            identity = {
                "pair_key": existing_pair,
                "unit_code": existing.get("unit_code"),
                "exam_year": existing.get("exam_year"),
                "exam_session": existing.get("exam_session"),
                "identity_status": existing.get("identity_status"),
                "identity_error": existing.get("identity_error"),
            }

    object_key = f"corpus-sources/{subject.id}/{source_type}/{checksum}{suffix}"
    object_store = build_object_store(settings)
    object_already_existed = object_store.exists(object_key)
    try:
        stored = object_store.put_stream(
            object_key,
            file.file,
            max_bytes=settings.knowledge_upload_max_bytes,
            metadata=ObjectMetadata(
                purpose="corpus-source",
                owner_type="source_document",
                owner_id=hashlib.sha256(
                    f"{subject.subject_code}:{source_type}:{checksum}".encode()
                ).hexdigest(),
                content_type=file.content_type,
            ),
        )
        source_path = object_store.materialize(stored.key)
        page_count = None
        if suffix == ".pdf":
            try:
                page_count = len(PdfReader(source_path).pages)
            except Exception:
                page_count = None
        object_uri = f"object://{stored.key}"
        document_id = repository.register_discovery(
            {
                "subject_code": subject.subject_code,
                "subject_id": workspace_id,
                "knowledge_base_id": knowledge_base_id,
                "path": object_uri,
                "object_key": stored.key,
                "filename": filename,
                "source_type": source_type,
                "source_role": role,
                "authority_tier": _authority_tier(source_type, license_confirmed),
                "license_confirmed": license_confirmed,
                "checksum": stored.checksum_sha256,
                "page_count": page_count,
                **identity,
                "metadata_json": {
                    "upload_name": filename,
                    "workspace_id": workspace_id,
                    "knowledge_base_id": knowledge_base_id,
                    "object_key": stored.key,
                },
            },
            relative_path=stored.key,
            size_bytes=stored.size_bytes,
            current_paths={str(existing["path"]) if existing is not None else object_uri},
        )
        _workspaces(settings).assign_document(
            document_id,
            subject_id=workspace_id,
            knowledge_base_id=knowledge_base_id,
            source_type=source_type,
            license_confirmed=license_confirmed,
        )
        row = repository.get(document_id)
        if row is None:
            raise RuntimeError("上传资料注册失败")
        return SourceDocumentResponse.model_validate(row)
    except (LookupError, ValueError) as error:
        if not object_already_existed:
            object_store.delete(object_key)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception:
        if not object_already_existed:
            object_store.delete(object_key)
        raise


@router.post(
    "/knowledge-bases/{knowledge_base_id}/build",
    response_model=KnowledgeBaseBuildResponse,
)
def build_knowledge_base(
    knowledge_base_id: str,
    settings: Settings = Depends(get_settings),
    subject: SubjectContext = Depends(get_subject_context),
) -> KnowledgeBaseBuildResponse:
    workspaces = _workspaces(settings)
    base = workspaces.require_base(knowledge_base_id, subject_id=subject.id)
    version = workspaces.create_version(knowledge_base_id)
    version_id = str(version["id"])
    document_ids = workspaces.documents_for_version(version_id)
    build_context = subject.with_index_target(
        version_id=version_id,
        alias_name=str(version["alias_name"]),
    )
    runtime_settings = build_context.runtime_settings(settings)
    try:
        conversion = build_corpus_ingestor(settings, subject).convert_batch(
            document_ids=document_ids,
            workers=2,
        )
        if conversion.failed:
            raise ValueError("资料转换失败：" + "；".join(conversion.errors[:5]))
        index_result = build_vector_index(
            runtime_settings,
            build_context,
            vector_index_repository(settings),
            knowledge_repository(settings),
            knowledge_base_version_id=version_id,
            source_document_ids=document_ids,
        )
        published = workspaces.require_version(version_id)
        return KnowledgeBaseBuildResponse(
            version=KnowledgeBaseVersionResponse.model_validate(published),
            processed=index_result.processed,
            succeeded=index_result.succeeded,
            failed=index_result.failed,
            errors=index_result.errors,
        )
    except Exception as error:
        workspaces.fail_version(version_id, str(error))
        raise HTTPException(
            status_code=502,
            detail=f"{base['name']}构建失败：{str(error)[:500]}",
        ) from error
