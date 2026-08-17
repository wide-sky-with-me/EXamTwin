from __future__ import annotations

import hashlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest
from examtwin.app.api import workspaces as workspace_api_module
from examtwin.app.api.dependencies import get_corpus_workspace_service, get_subject_context
from examtwin.app.api.workspaces import router as workspace_router
from examtwin.contracts.common import JobResult
from examtwin.knowledge.workspace_service import (
    CorpusWorkspaceService,
    KnowledgeBaseBuildError,
    WorkspaceNotFoundError,
)
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.storage import LocalObjectStore, ManagedObjectStore, ObjectMetadata
from examtwin.subjects.public import subject_context
from fastapi import FastAPI
from fastapi.testclient import TestClient


class WorkspaceRecords:
    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id
        self.failed_version: tuple[str, str] | None = None
        self.base: dict[str, object] = {
            "id": "base-1",
            "name": "核心知识库",
            "kind": "core",
            "active_version_id": None,
        }
        self.supplementary_base: dict[str, object] = {
            "id": "base-2",
            "name": "补充知识库",
            "kind": "supplementary",
            "active_version_id": None,
        }
        self.version: dict[str, object] | None = None

    def require_subject(self, workspace_id: str) -> dict[str, object]:
        assert workspace_id == self.workspace_id
        return {
            "id": workspace_id,
            "knowledge_bases": [
                dict(self.base),
                dict(self.supplementary_base),
            ],
        }

    def require_base(
        self,
        base_id: str,
        *,
        subject_id: str | None = None,
    ) -> dict[str, object]:
        assert base_id == self.base["id"]
        assert subject_id == self.workspace_id
        return dict(self.base)

    def create_version(self, base_id: str) -> dict[str, object]:
        assert base_id == self.base["id"]
        self.version = {
            "id": "version-1",
            "knowledge_base_id": "base-1",
            "alias_name": "kb-version-1",
            "status": "building",
            "vector_build_id": None,
            "collection_name": None,
        }
        return dict(self.version)

    def documents_for_version(self, version_id: str) -> list[str]:
        assert version_id == "version-1"
        return ["document-1"]

    def require_version(self, version_id: str) -> dict[str, object]:
        assert version_id == "version-1"
        assert self.version is not None
        return dict(self.version)

    def publish_version(
        self,
        version_id: str,
        *,
        build_id: str,
        collection_name: str,
    ) -> None:
        assert version_id == "version-1"
        assert self.version is not None
        assert self.version["status"] == "building"
        self.version["status"] = "published"
        self.version["vector_build_id"] = build_id
        self.version["collection_name"] = collection_name
        self.base["active_version_id"] = version_id

    def fail_version(self, version_id: str, error: str) -> None:
        assert self.version is not None
        self.version["status"] = "failed"
        self.failed_version = (version_id, error)


class CorpusRecords:
    def __init__(self) -> None:
        self.row: dict[str, Any] | None = None

    def find_by_checksum(
        self,
        *,
        subject_code: str,
        source_type: str,
        checksum: str,
    ) -> dict[str, Any] | None:
        if (
            self.row is not None
            and self.row["subject_code"] == subject_code
            and self.row["source_type"] == source_type
            and self.row["checksum"] == checksum
        ):
            return dict(self.row)
        return None

    def register_discovery(
        self,
        document: dict[str, Any],
        *,
        relative_path: str,
        size_bytes: int,
        current_paths: set[str],
    ) -> str:
        assert relative_path == document["object_key"]
        assert size_bytes > 0
        assert current_paths
        document_id = self.row["id"] if self.row is not None else "document-1"
        self.row = {"id": document_id, "error": None, "status": "discovered", **document}
        return str(document_id)

    def get(self, document_id: str) -> dict[str, Any] | None:
        if self.row is None or self.row["id"] != document_id:
            return None
        return dict(self.row)


class ConversionRunner:
    def __init__(self, result: JobResult) -> None:
        self.result = result
        self.document_ids: list[str] | None = None

    def convert_batch(
        self,
        *,
        document_ids: list[str] | None = None,
        workers: int = 1,
    ) -> JobResult:
        assert workers == 2
        self.document_ids = document_ids
        return self.result


class WorkspaceApiService:
    def __init__(
        self,
        *,
        upload_error: Exception | None = None,
        build_error: Exception | None = None,
    ) -> None:
        self.upload_error = upload_error
        self.build_error = build_error
        self.upload_call: dict[str, object] | None = None

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
    ) -> dict[str, object]:
        self.upload_call = {
            "workspace_id": workspace_id,
            "content": stream.read(),
            "filename": filename,
            "content_type": content_type,
            "source_type": source_type,
            "knowledge_base_id": knowledge_base_id,
            "license_confirmed": license_confirmed,
        }
        if self.upload_error is not None:
            raise self.upload_error
        return {
            "id": "document-1",
            "filename": filename,
            "source_type": source_type,
            "source_role": "core_knowledge",
            "authority_tier": "licensed_core",
            "knowledge_base_id": knowledge_base_id,
            "license_confirmed": license_confirmed,
            "status": "discovered",
            "checksum": hashlib.sha256(b"lesson notes").hexdigest(),
            "object_key": "corpus-sources/workspace-1/textbook/document-1.md",
            "page_count": None,
            "error": None,
        }

    def build_knowledge_base(self, knowledge_base_id: str) -> None:
        assert knowledge_base_id == "base-1"
        assert self.build_error is not None
        raise self.build_error


def _workspace_api(service: WorkspaceApiService) -> FastAPI:
    app = FastAPI()
    app.include_router(workspace_router)
    app.dependency_overrides[get_corpus_workspace_service] = lambda: service
    return app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        subject_pack="oxfordaqa-economics-9640",
        corpus_root=tmp_path / "read-only-corpus",
        object_store_local_root=tmp_path / "objects",
    )


def _upload_service(
    settings: Settings,
    workspaces: WorkspaceRecords,
    repository: CorpusRecords,
    object_store: ManagedObjectStore,
) -> CorpusWorkspaceService:
    subject = subject_context(settings)
    return CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, repository),
        object_store=object_store,
        ingestor=cast(Any, None),
        vector_indexes=cast(Any, None),
        knowledge=cast(Any, None),
    )


def test_workspace_upload_uses_managed_object_store_and_records_exam_identity(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    repository = CorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        object_store,
    )

    row = service.upload_document(
        subject.id,
        BytesIO(b"official mark scheme"),
        filename="A-Level-AQA经济学-国际卷MS-202406-Economics-U1-AQA.md",
        content_type="text/markdown",
        source_type="mark_scheme",
        knowledge_base_id=None,
        license_confirmed=False,
    )

    object_key = str(row["object_key"])
    assert object_key.startswith(f"corpus-sources/{subject.id}/mark_scheme/")
    assert object_store.materialize(object_key).read_bytes() == b"official mark scheme"
    assert repository.row is not None
    assert repository.row["pair_key"] == "9640:2024:JUN:U1"
    assert repository.row["identity_status"] == "complete"
    assert repository.row["path"] == f"object://{object_key}"
    assert not (subject.corpus_dir / "uploads").exists()


def test_workspace_upload_rejects_oversized_stream_before_persistence(
    tmp_path: Path,
) -> None:
    class CorpusRepositorySpy(CorpusRecords):
        def __init__(self) -> None:
            super().__init__()
            self.lookup_calls = 0
            self.registration_calls = 0

        def find_by_checksum(
            self,
            *,
            subject_code: str,
            source_type: str,
            checksum: str,
        ) -> dict[str, Any] | None:
            self.lookup_calls += 1
            return None

        def register_discovery(
            self,
            document: dict[str, Any],
            *,
            relative_path: str,
            size_bytes: int,
            current_paths: set[str],
        ) -> str:
            self.registration_calls += 1
            raise AssertionError("oversized upload reached document registration")

    class ObjectStoreSpy:
        def __init__(self) -> None:
            self.exists_calls: list[str] = []
            self.write_calls: list[tuple[str, int]] = []

        def exists(self, object_key: str) -> bool:
            self.exists_calls.append(object_key)
            return False

        def put_stream(
            self,
            object_key: str,
            stream: BinaryIO,
            *,
            max_bytes: int,
            metadata: ObjectMetadata,
        ) -> ObjectMetadata:
            self.write_calls.append((object_key, max_bytes))
            raise AssertionError("oversized upload reached object-store persistence")

    max_bytes = 1024 * 1024
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        corpus_root=tmp_path / "read-only-corpus",
        object_store_local_root=tmp_path / "objects",
        knowledge_upload_max_bytes=max_bytes,
    )
    subject = subject_context(settings)
    repository = CorpusRepositorySpy()
    object_store = ObjectStoreSpy()
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        cast(Any, object_store),
    )

    with pytest.raises(ValueError) as exc_info:
        service.upload_document(
            subject.id,
            BytesIO(b"x" * (max_bytes + 1)),
            filename="oversized-mark-scheme.md",
            content_type="text/markdown",
            source_type="mark_scheme",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert type(exc_info.value) is ValueError
    assert str(exc_info.value) == "资料文件超过允许的上传大小"
    assert repository.lookup_calls == 0
    assert repository.registration_calls == 0
    assert object_store.exists_calls == []
    assert object_store.write_calls == []


def test_authorized_textbook_upload_persists_core_assignment_metadata(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    repository = CorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(settings, workspaces, repository, object_store)

    service.upload_document(
        subject.id,
        BytesIO(b"licensed textbook chapter"),
        filename="licensed-economics-textbook.md",
        content_type="text/markdown",
        source_type="textbook",
        knowledge_base_id=str(workspaces.base["id"]),
        license_confirmed=True,
    )

    assert repository.row is not None
    assert repository.row["knowledge_base_id"] == workspaces.base["id"]
    assert repository.row["source_role"] == "core_knowledge"
    assert repository.row["authority_tier"] == "licensed_core"


def test_duplicate_upload_keeps_complete_identity_and_stable_object_key(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    repository = CorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        object_store,
    )
    payload = b"same official mark scheme"

    first = service.upload_document(
        subject.id,
        BytesIO(payload),
        filename="AQA-A-Level-JUN2024-Economics-Paper-1-MS.md",
        content_type="text/markdown",
        source_type="mark_scheme",
        knowledge_base_id=None,
        license_confirmed=False,
    )
    second = service.upload_document(
        subject.id,
        BytesIO(payload),
        filename="renamed-without-exam-identity.md",
        content_type="text/markdown",
        source_type="mark_scheme",
        knowledge_base_id=None,
        license_confirmed=False,
    )

    assert second["id"] == first["id"]
    assert second["object_key"] == first["object_key"]
    assert repository.row is not None
    assert repository.row["pair_key"] == "9640:2024:JUN:U1"
    assert repository.row["identity_status"] == "complete"


def test_conflicting_complete_duplicate_keeps_original_row_and_object(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    repository = CorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        object_store,
    )
    payload = b"same official mark scheme"
    first = service.upload_document(
        subject.id,
        BytesIO(payload),
        filename="AQA-A-Level-JUN2024-Economics-Paper-1-MS.md",
        content_type="text/markdown",
        source_type="mark_scheme",
        knowledge_base_id=None,
        license_confirmed=False,
    )
    assert repository.row is not None
    original_row = deepcopy(repository.row)
    assert original_row["identity_status"] == "complete"
    assert original_row["pair_key"] == "9640:2024:JUN:U1"
    original_object_key = str(first["object_key"])
    original_object = object_store.materialize(original_object_key).read_bytes()

    with pytest.raises(
        ValueError,
        match="重复资料的考试身份与已有记录冲突",
    ):
        service.upload_document(
            subject.id,
            BytesIO(payload),
            filename="AQA-A-Level-JUN2024-Economics-Paper-2-MS.md",
            content_type="text/markdown",
            source_type="mark_scheme",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert repository.row == original_row
    assert object_store.materialize(original_object_key).read_bytes() == original_object


def test_upload_removes_new_object_when_registration_fails(tmp_path: Path) -> None:
    class FailingCorpusRecords(CorpusRecords):
        def register_discovery(
            self,
            document: dict[str, Any],
            *,
            relative_path: str,
            size_bytes: int,
            current_paths: set[str],
        ) -> str:
            raise ValueError("registration failed")

    settings = _settings(tmp_path)
    subject = subject_context(settings)
    repository = FailingCorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        object_store,
    )
    payload = b"uncommitted source"
    object_key = f"corpus-sources/{subject.id}/other/{hashlib.sha256(payload).hexdigest()}.md"

    with pytest.raises(ValueError, match="registration failed"):
        service.upload_document(
            subject.id,
            BytesIO(payload),
            filename="source.md",
            content_type="text/markdown",
            source_type="other",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert not object_store.exists(object_key)


def test_failed_duplicate_registration_preserves_pre_existing_object(
    tmp_path: Path,
) -> None:
    class FailingCorpusRecords(CorpusRecords):
        def register_discovery(
            self,
            document: dict[str, Any],
            *,
            relative_path: str,
            size_bytes: int,
            current_paths: set[str],
        ) -> str:
            raise ValueError("registration failed")

    settings = _settings(tmp_path)
    subject = subject_context(settings)
    repository = FailingCorpusRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    service = _upload_service(
        settings,
        WorkspaceRecords(subject.id),
        repository,
        object_store,
    )
    payload = b"existing source"
    object_key = f"corpus-sources/{subject.id}/other/{hashlib.sha256(payload).hexdigest()}.md"
    object_store.put_bytes(
        object_key,
        payload,
        metadata=ObjectMetadata(
            purpose="corpus-source",
            owner_type="source_document",
            owner_id="pre-existing-document",
            content_type="text/markdown",
        ),
    )

    with pytest.raises(ValueError, match="registration failed"):
        service.upload_document(
            subject.id,
            BytesIO(payload),
            filename="source.md",
            content_type="text/markdown",
            source_type="other",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert object_store.materialize(object_key).read_bytes() == payload


def test_build_knowledge_base_runs_conversion_index_and_publication(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    conversion = ConversionRunner(JobResult(processed=1, succeeded=1, failed=0))
    vector_indexes = object()
    knowledge = object()
    index_call: dict[str, Any] = {}

    def index_builder(*args: object, **kwargs: object) -> JobResult:
        index_call["args"] = args
        index_call["kwargs"] = kwargs
        assert len(args) == 4
        runtime_settings = cast(Settings, args[0])
        build_context = cast(Any, args[1])
        assert runtime_settings.qdrant_collection == "kb-version-1_base"
        assert runtime_settings.qdrant_collection_alias == "kb-version-1"
        assert build_context.knowledge_base_version_ids == ("version-1",)
        assert build_context.vector_collection == "kb-version-1_base"
        assert build_context.vector_alias == "kb-version-1"
        assert args[2] is vector_indexes
        assert args[3] is knowledge
        workspaces.publish_version(
            "version-1",
            build_id="build-1",
            collection_name="collection-1",
        )
        return JobResult(processed=1, succeeded=1, failed=0)

    service = CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, None),
        object_store=cast(Any, None),
        ingestor=cast(Any, conversion),
        vector_indexes=cast(Any, vector_indexes),
        knowledge=cast(Any, knowledge),
        index_builder=index_builder,
    )

    result = service.build_knowledge_base("base-1")

    assert conversion.document_ids == ["document-1"]
    assert index_call["kwargs"] == {
        "knowledge_base_version_id": "version-1",
        "source_document_ids": ["document-1"],
    }
    assert result.version["status"] == "published"
    assert result.version["vector_build_id"] == "build-1"
    assert result.version["collection_name"] == "collection-1"
    assert workspaces.base["active_version_id"] == "version-1"
    assert result.index_result.succeeded == 1
    assert workspaces.failed_version is None


def test_build_knowledge_base_fails_when_builder_does_not_publish(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    conversion = ConversionRunner(JobResult(processed=1, succeeded=1, failed=0))

    service = CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, None),
        object_store=cast(Any, None),
        ingestor=cast(Any, conversion),
        vector_indexes=cast(Any, object()),
        knowledge=cast(Any, object()),
        index_builder=lambda *args, **kwargs: JobResult(
            processed=1,
            succeeded=1,
            failed=0,
        ),
    )

    with pytest.raises(KnowledgeBaseBuildError, match="知识库版本未发布"):
        service.build_knowledge_base("base-1")

    assert workspaces.failed_version == ("version-1", "知识库版本未发布")
    assert workspaces.version is not None
    assert workspaces.version["status"] == "failed"


def test_build_knowledge_base_marks_version_failed_when_conversion_fails(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    conversion = ConversionRunner(
        JobResult(processed=1, succeeded=0, failed=1, errors=["broken document"])
    )
    service = CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, None),
        object_store=cast(Any, None),
        ingestor=cast(Any, conversion),
        vector_indexes=cast(Any, object()),
        knowledge=cast(Any, object()),
    )

    with pytest.raises(KnowledgeBaseBuildError, match="核心知识库构建失败"):
        service.build_knowledge_base("base-1")

    assert workspaces.failed_version is not None
    assert workspaces.failed_version[0] == "version-1"
    assert "broken document" in workspaces.failed_version[1]


def test_resume_failed_knowledge_base_reuses_existing_vector_build(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    workspaces.create_version("base-1")
    assert workspaces.version is not None
    workspaces.version["status"] = "failed"
    vector_indexes = object()
    knowledge = object()
    index_call: dict[str, Any] = {}

    def index_builder(*args: object, **kwargs: object) -> JobResult:
        index_call["args"] = args
        index_call["kwargs"] = kwargs
        workspaces.version = {
            **workspaces.version,
            "status": "published",
            "vector_build_id": "build-1",
            "collection_name": "collection-1",
        }
        return JobResult(processed=2, succeeded=2, failed=0)

    service = CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, None),
        object_store=cast(Any, None),
        ingestor=cast(Any, ConversionRunner(JobResult(processed=0, succeeded=0, failed=0))),
        vector_indexes=cast(Any, vector_indexes),
        knowledge=cast(Any, knowledge),
        index_builder=index_builder,
    )

    result = service.resume_knowledge_base_version("version-1")

    assert len(index_call["args"]) == 4
    assert index_call["kwargs"] == {
        "resume": True,
        "knowledge_base_version_id": "version-1",
        "source_document_ids": ["document-1"],
    }
    assert result.version["status"] == "published"
    assert result.index_result.succeeded == 2


def test_resume_knowledge_base_rejects_non_failed_version(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    workspaces = WorkspaceRecords(subject.id)
    workspaces.create_version("base-1")
    service = CorpusWorkspaceService(
        settings,
        subject,
        workspaces=workspaces,
        documents=cast(Any, None),
        object_store=cast(Any, None),
        ingestor=cast(Any, None),
        vector_indexes=cast(Any, object()),
        knowledge=cast(Any, object()),
    )

    with pytest.raises(ValueError, match="只有构建失败"):
        service.resume_knowledge_base_version("version-1")


def test_workspace_router_upload_returns_created_response() -> None:
    service = WorkspaceApiService()

    with TestClient(_workspace_api(service)) as client:
        response = client.post(
            "/subject-workspaces/workspace-1/documents",
            files={"file": ("notes.md", b"lesson notes", "text/markdown")},
            data={
                "source_type": "textbook",
                "knowledge_base_id": "base-1",
                "license_confirmed": "true",
            },
        )

    assert response.status_code == 201
    assert response.json() == {
        "id": "document-1",
        "filename": "notes.md",
        "display_name": None,
        "source_type": "textbook",
        "source_role": "core_knowledge",
        "authority_tier": "licensed_core",
        "knowledge_base_id": "base-1",
        "license_confirmed": True,
        "status": "discovered",
        "checksum": hashlib.sha256(b"lesson notes").hexdigest(),
        "object_key": "corpus-sources/workspace-1/textbook/document-1.md",
        "page_count": None,
        "error": None,
        "pair_key": None,
        "unit_code": None,
        "exam_year": None,
        "exam_session": None,
        "identity_status": "not_applicable",
        "identity_error": None,
    }
    assert service.upload_call == {
        "workspace_id": "workspace-1",
        "content": b"lesson notes",
        "filename": "notes.md",
        "content_type": "text/markdown",
        "source_type": "textbook",
        "knowledge_base_id": "base-1",
        "license_confirmed": True,
    }


def test_workspace_document_content_supports_inline_preview_and_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    subject = subject_context(settings)
    original = tmp_path / "MS-202406-U1.pdf"
    original.write_bytes(b"%PDF-1.4 original mark scheme")
    row = {
        "id": "document-1",
        "subject_id": subject.id,
        "subject_code": subject.subject_code,
        "filename": "MS-202406-U1.pdf",
        "path": str(original),
        "object_key": None,
    }

    class Documents:
        def get_active(self, document_id: str) -> dict[str, object] | None:
            return row if document_id == "document-1" else None

    monkeypatch.setattr(workspace_api_module, "corpus_repository", lambda _: Documents())
    app = FastAPI()
    app.include_router(workspace_router)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_subject_context] = lambda: subject

    with TestClient(app) as client:
        preview = client.get(f"/subject-workspaces/{subject.id}/documents/document-1/content")
        download = client.get(
            f"/subject-workspaces/{subject.id}/documents/document-1/content?download=true"
        )
        row["subject_id"] = "another-workspace"
        forbidden = client.get(f"/subject-workspaces/{subject.id}/documents/document-1/content")

    assert preview.status_code == 200
    assert preview.content == b"%PDF-1.4 original mark scheme"
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"].startswith("inline;")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert forbidden.status_code == 404


def test_workspace_router_maps_missing_workspace_to_not_found() -> None:
    service = WorkspaceApiService(
        upload_error=WorkspaceNotFoundError("科目工作区不存在"),
    )

    with TestClient(_workspace_api(service)) as client:
        response = client.post(
            "/subject-workspaces/missing/documents",
            files={"file": ("notes.md", b"lesson notes", "text/markdown")},
            data={"source_type": "textbook"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "科目工作区不存在"}


@pytest.mark.parametrize(
    "upload_error",
    [
        pytest.param(ValueError("所选知识库不存在"), id="value-error"),
        pytest.param(LookupError("所选知识库不存在"), id="lookup-error"),
    ],
)
def test_workspace_router_maps_assignment_error_to_unprocessable(
    upload_error: Exception,
) -> None:
    service = WorkspaceApiService(upload_error=upload_error)

    with TestClient(_workspace_api(service)) as client:
        response = client.post(
            "/subject-workspaces/workspace-1/documents",
            files={"file": ("notes.md", b"lesson notes", "text/markdown")},
            data={"source_type": "textbook", "knowledge_base_id": "missing"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "所选知识库不存在"}


def test_workspace_router_maps_build_error_to_bad_gateway() -> None:
    service = WorkspaceApiService(
        build_error=KnowledgeBaseBuildError("核心知识库构建失败：索引服务不可用"),
    )

    with TestClient(_workspace_api(service)) as client:
        response = client.post("/knowledge-bases/base-1/build")

    assert response.status_code == 502
    assert response.json() == {"detail": "核心知识库构建失败：索引服务不可用"}
