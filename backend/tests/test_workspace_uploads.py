from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from examtwin.api import workspaces as workspace_api
from examtwin.config import Settings
from examtwin.services.subject_context import subject_context
from examtwin.storage import LocalObjectStore, ManagedObjectStore
from fastapi import UploadFile
from starlette.datastructures import Headers


class WorkspaceRecords:
    def require_subject(self, workspace_id: str) -> dict[str, object]:
        return {"id": workspace_id, "knowledge_bases": []}

    def assign_document(self, *_args: object, **_kwargs: object) -> None:
        return None


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


def _upload(filename: str, payload: bytes) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(payload),
        headers=Headers({"content-type": "text/markdown"}),
    )


def test_workspace_upload_uses_managed_object_store_and_records_exam_identity(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        corpus_root=tmp_path / "read-only-corpus",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    repository = CorpusRecords()
    workspaces = WorkspaceRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    monkeypatch.setattr(workspace_api, "corpus_repository", lambda _settings: repository)
    monkeypatch.setattr(workspace_api, "_workspaces", lambda _settings: workspaces)
    monkeypatch.setattr(workspace_api, "build_object_store", lambda _settings: object_store)

    response = workspace_api.upload_workspace_document(
        subject.id,
        _upload(
            "A-Level-AQA经济学-国际卷MS-202406-Economics-U1-AQA.md",
            b"official mark scheme",
        ),
        "mark_scheme",
        None,
        False,
        settings,
        subject,
    )

    assert response.object_key is not None
    assert response.object_key.startswith(f"corpus-sources/{subject.id}/mark_scheme/")
    assert object_store.materialize(response.object_key).read_bytes() == b"official mark scheme"
    assert repository.row is not None
    assert repository.row["pair_key"] == "9640:2024:JUN:U1"
    assert repository.row["identity_status"] == "complete"
    assert repository.row["path"] == f"object://{response.object_key}"
    assert not (subject.corpus_dir / "uploads").exists()


def test_duplicate_upload_keeps_complete_identity_and_stable_object_key(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        corpus_root=tmp_path / "read-only-corpus",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    repository = CorpusRecords()
    workspaces = WorkspaceRecords()
    object_store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    monkeypatch.setattr(workspace_api, "corpus_repository", lambda _settings: repository)
    monkeypatch.setattr(workspace_api, "_workspaces", lambda _settings: workspaces)
    monkeypatch.setattr(workspace_api, "build_object_store", lambda _settings: object_store)
    payload = b"same official mark scheme"

    first = workspace_api.upload_workspace_document(
        subject.id,
        _upload("AQA-A-Level-JUN2024-Economics-Paper-1-MS.md", payload),
        "mark_scheme",
        None,
        False,
        settings,
        subject,
    )
    second = workspace_api.upload_workspace_document(
        subject.id,
        _upload("renamed-without-exam-identity.md", payload),
        "mark_scheme",
        None,
        False,
        settings,
        subject,
    )

    assert second.id == first.id
    assert second.object_key == first.object_key
    assert repository.row is not None
    assert repository.row["pair_key"] == "9640:2024:JUN:U1"
    assert repository.row["identity_status"] == "complete"
