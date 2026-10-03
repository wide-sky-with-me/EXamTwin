from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from pypdf import PdfReader

from examtwin.contracts.common import JobResult
from examtwin.knowledge.corpus_ingestion import CorpusIngestor
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.knowledge.ingestion import build_vector_index
from examtwin.knowledge.knowledge_repository import KnowledgeRepository
from examtwin.knowledge.vector_index_repository import VectorIndexRepository
from examtwin.platform.config import Settings
from examtwin.platform.storage import ManagedObjectStore, ObjectMetadata
from examtwin.subjects.public import (
    SubjectContext,
    resolve_document_assignment_after_file_validation,
    resolve_document_assignment_before_file_validation,
    validate_document_source_type,
)

SUPPORTED_UPLOAD_SUFFIXES = frozenset({".pdf", ".md", ".markdown", ".ppt", ".pptx"})


class WorkspacePort(Protocol):
    def require_subject(self, selector: str) -> dict[str, Any]: ...

    def require_base(
        self,
        base_id: str,
        *,
        subject_id: str | None = None,
    ) -> dict[str, Any]: ...

    def create_version(self, base_id: str) -> dict[str, Any]: ...

    def documents_for_version(self, version_id: str) -> list[str]: ...

    def require_version(self, version_id: str) -> dict[str, Any]: ...

    def fail_version(self, version_id: str, error: str) -> None: ...


@dataclass(frozen=True)
class KnowledgeBaseBuildResult:
    version: Mapping[str, Any]
    index_result: JobResult


class WorkspaceNotFoundError(LookupError):
    pass


class KnowledgeBaseBuildError(RuntimeError):
    pass


class CorpusWorkspaceService:
    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        workspaces: WorkspacePort,
        documents: CorpusRepository,
        object_store: ManagedObjectStore,
        ingestor: CorpusIngestor,
        vector_indexes: VectorIndexRepository,
        knowledge: KnowledgeRepository,
        index_builder: Callable[..., JobResult] = build_vector_index,
    ) -> None:
        self.settings = settings
        self.subject = subject
        self.workspaces = workspaces
        self.documents = documents
        self.object_store = object_store
        self.ingestor = ingestor
        self.vector_indexes = vector_indexes
        self.knowledge = knowledge
        self.index_builder = index_builder

    def upload_document(
        self,
        workspace_id: str,
        stream: BinaryIO,
        *,
        filename: str,
        content_type: str | None,
        source_type: str,
        knowledge_base_id: str | None,
        license_confirmed: bool,
    ) -> dict[str, Any]:
        if workspace_id != self.subject.id:
            raise WorkspaceNotFoundError("科目工作区不存在")

        validate_document_source_type(source_type)
        workspace = self.workspaces.require_subject(workspace_id)
        assignment = resolve_document_assignment_before_file_validation(
            workspace,
            source_type=source_type,
            knowledge_base_id=knowledge_base_id,
            license_confirmed=license_confirmed,
        )
        safe_filename = Path(filename or "upload").name
        suffix = Path(safe_filename).suffix.lower()
        if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
            raise ValueError("仅支持 PDF、Markdown、PPT 或 PPTX 资料")

        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > self.settings.knowledge_upload_max_bytes:
                raise ValueError("资料文件超过允许的上传大小")
            digest.update(chunk)
        if size == 0:
            raise ValueError("上传文件为空")
        assignment = resolve_document_assignment_after_file_validation(
            assignment,
            source_type=source_type,
            knowledge_base_id=knowledge_base_id,
        )
        checksum = digest.hexdigest()
        stream.seek(0)

        existing = self.documents.find_by_checksum(
            subject_code=self.subject.subject_code,
            source_type=source_type,
            checksum=checksum,
        )
        identity: dict[str, object] = {
            "pair_key": None,
            "unit_code": None,
            "exam_year": None,
            "exam_session": None,
            "identity_status": "not_applicable",
            "identity_error": None,
        }
        if assignment.source_role == "assessment_only":
            from examtwin.knowledge.inventory import (
                parse_exam_identity,
                read_printed_subject_code,
            )

            printed_code = read_printed_subject_code(stream) if suffix == ".pdf" else None
            stream.seek(0)
            identity = parse_exam_identity(
                Path(safe_filename),
                source_type,
                self.subject.pack,
                printed_subject_code=printed_code,
            )
            if existing is not None and existing.get("identity_status") == "complete":
                incoming_pair = identity.get("pair_key")
                existing_pair = existing.get("pair_key")
                if identity.get("identity_status") == "complete" and incoming_pair != existing_pair:
                    raise ValueError("重复资料的考试身份与已有记录冲突")
                identity = {
                    "pair_key": existing_pair,
                    "unit_code": existing.get("unit_code"),
                    "exam_year": existing.get("exam_year"),
                    "exam_session": existing.get("exam_session"),
                    "identity_status": existing.get("identity_status"),
                    "identity_error": existing.get("identity_error"),
                }

        object_key = f"corpus-sources/{self.subject.id}/{source_type}/{checksum}{suffix}"
        object_already_existed = self.object_store.exists(object_key)
        try:
            stored = self.object_store.put_stream(
                object_key,
                stream,
                max_bytes=self.settings.knowledge_upload_max_bytes,
                metadata=ObjectMetadata(
                    purpose="corpus-source",
                    owner_type="source_document",
                    owner_id=hashlib.sha256(
                        f"{self.subject.subject_code}:{source_type}:{checksum}".encode()
                    ).hexdigest(),
                    content_type=content_type,
                ),
            )
            source_path = self.object_store.materialize(stored.key)
            page_count = None
            if suffix == ".pdf":
                try:
                    page_count = len(PdfReader(source_path).pages)
                except Exception:
                    page_count = None
            object_uri = f"object://{stored.key}"
            document_id = self.documents.register_discovery(
                {
                    "subject_code": self.subject.subject_code,
                    "subject_id": workspace_id,
                    "knowledge_base_id": assignment.knowledge_base_id,
                    "path": object_uri,
                    "object_key": stored.key,
                    "filename": safe_filename,
                    "source_type": source_type,
                    "source_role": assignment.source_role,
                    "authority_tier": assignment.authority_tier,
                    "license_confirmed": license_confirmed,
                    "checksum": stored.checksum_sha256,
                    "page_count": page_count,
                    **identity,
                    "metadata_json": {
                        "upload_name": safe_filename,
                        "workspace_id": workspace_id,
                        "knowledge_base_id": assignment.knowledge_base_id,
                        "object_key": stored.key,
                    },
                },
                relative_path=stored.key,
                size_bytes=stored.size_bytes,
                current_paths={str(existing["path"]) if existing is not None else object_uri},
            )
            row = self.documents.get(document_id)
            if row is None:
                raise RuntimeError("上传资料注册失败")
            # Uploads dedupe by checksum; callers that roll back must only remove new rows.
            created = existing is None or existing.get("status") == "deleted"
            return {**row, "created": created}
        except Exception:
            if not object_already_existed:
                self.object_store.delete(object_key)
            raise

    def build_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBaseBuildResult:
        base = self.workspaces.require_base(knowledge_base_id, subject_id=self.subject.id)
        version = self.workspaces.create_version(knowledge_base_id)
        version_id = str(version["id"])
        document_ids = self.workspaces.documents_for_version(version_id)
        build_context = self.subject.with_index_target(
            version_id=version_id,
            alias_name=str(version["alias_name"]),
        )
        runtime_settings = build_context.runtime_settings(self.settings)
        try:
            conversion = self.ingestor.convert_batch(document_ids=document_ids, workers=2)
            if conversion.failed:
                raise ValueError("资料转换失败：" + "；".join(conversion.errors[:5]))
            index_result = self.index_builder(
                runtime_settings,
                build_context,
                self.vector_indexes,
                self.knowledge,
                knowledge_base_version_id=version_id,
                source_document_ids=document_ids,
            )
            persisted_version = self.workspaces.require_version(version_id)
            if persisted_version.get("status") != "published":
                raise RuntimeError("知识库版本未发布")
            return KnowledgeBaseBuildResult(
                version=persisted_version,
                index_result=index_result,
            )
        except Exception as error:
            self.workspaces.fail_version(version_id, str(error))
            raise KnowledgeBaseBuildError(f"{base['name']}构建失败：{str(error)[:500]}") from error

    def resume_knowledge_base_version(self, version_id: str) -> KnowledgeBaseBuildResult:
        version = self.workspaces.require_version(version_id)
        base = self.workspaces.require_base(
            str(version["knowledge_base_id"]),
            subject_id=self.subject.id,
        )
        if version.get("status") != "failed":
            raise ValueError("只有构建失败的知识库版本可以恢复")
        document_ids = self.workspaces.documents_for_version(version_id)
        build_context = self.subject.with_index_target(
            version_id=version_id,
            alias_name=str(version["alias_name"]),
        )
        runtime_settings = build_context.runtime_settings(self.settings)
        try:
            index_result = self.index_builder(
                runtime_settings,
                build_context,
                self.vector_indexes,
                self.knowledge,
                resume=True,
                knowledge_base_version_id=version_id,
                source_document_ids=document_ids,
            )
            persisted_version = self.workspaces.require_version(version_id)
            if persisted_version.get("status") != "published":
                raise RuntimeError("知识库版本未发布")
            return KnowledgeBaseBuildResult(
                version=persisted_version,
                index_result=index_result,
            )
        except Exception as error:
            self.workspaces.fail_version(version_id, str(error))
            raise KnowledgeBaseBuildError(f"{base['name']}恢复失败：{str(error)[:500]}") from error
