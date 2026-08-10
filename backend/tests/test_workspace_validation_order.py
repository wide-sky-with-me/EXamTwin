from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from examtwin.knowledge.workspace_service import (
    CorpusWorkspaceService,
    WorkspaceNotFoundError,
)
from examtwin.platform.config import Settings
from examtwin.subjects.public import SubjectContext


class FailingWorkspaceLookup:
    def __init__(self) -> None:
        self.called = False

    def require_subject(self, workspace_id: str) -> dict[str, object]:
        self.called = True
        raise LookupError(f"未知科目：{workspace_id}")


class WorkspaceLookup:
    def __init__(self) -> None:
        self.called = False

    def require_subject(self, workspace_id: str) -> dict[str, object]:
        self.called = True
        return {
            "id": workspace_id,
            "knowledge_bases": [
                {"id": "core-1", "kind": "core"},
                {"id": "supplementary-1", "kind": "supplementary"},
            ],
        }


class UnexpectedDocuments:
    def find_by_checksum(self, **kwargs: object) -> None:
        raise AssertionError(f"assignment error reached document persistence: {kwargs}")


def _service(tmp_path: Path, workspaces: object) -> CorpusWorkspaceService:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        corpus_root=tmp_path / "read-only-corpus",
        object_store_local_root=tmp_path / "objects",
    )
    subject = cast(
        SubjectContext,
        SimpleNamespace(id="workspace-1", subject_code="9640"),
    )
    return CorpusWorkspaceService(
        settings,
        subject,
        workspaces=cast(Any, workspaces),
        documents=cast(Any, UnexpectedDocuments()),
        object_store=cast(Any, None),
        ingestor=cast(Any, None),
        vector_indexes=cast(Any, None),
        knowledge=cast(Any, None),
    )


def test_workspace_id_mismatch_precedes_unknown_source_type(tmp_path: Path) -> None:
    workspaces = FailingWorkspaceLookup()
    service = _service(tmp_path, workspaces)

    with pytest.raises(WorkspaceNotFoundError) as error:
        service.upload_document(
            "missing-workspace",
            BytesIO(b"content"),
            filename="source.md",
            content_type="text/markdown",
            source_type="unknown",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert str(error.value) == "科目工作区不存在"
    assert not workspaces.called


def test_unknown_source_type_precedes_failing_workspace_lookup(tmp_path: Path) -> None:
    workspaces = FailingWorkspaceLookup()
    service = _service(tmp_path, workspaces)

    with pytest.raises(ValueError) as error:
        service.upload_document(
            "workspace-1",
            BytesIO(b"content"),
            filename="source.md",
            content_type="text/markdown",
            source_type="unknown",
            knowledge_base_id=None,
            license_confirmed=False,
        )

    assert str(error.value) == "未知资料类型"
    assert not workspaces.called


@pytest.mark.parametrize(
    ("source_type", "knowledge_base_id", "expected_error"),
    [
        ("textbook", "missing", "知识库不存在于当前科目"),
        ("textbook", "core-1", "教材必须确认已获授权后才能进入知识库"),
        ("revision_note", "core-1", "核心知识库只接受考纲和已授权教材"),
        ("syllabus", "supplementary-1", "考纲必须归属核心知识库"),
    ],
)
def test_knowledge_assignment_errors_precede_file_validation(
    tmp_path: Path,
    source_type: str,
    knowledge_base_id: str,
    expected_error: str,
) -> None:
    service = _service(tmp_path, WorkspaceLookup())

    with pytest.raises(ValueError) as error:
        service.upload_document(
            "workspace-1",
            BytesIO(b"content"),
            filename="source.txt",
            content_type=None,
            source_type=source_type,
            knowledge_base_id=knowledge_base_id,
            license_confirmed=False,
        )

    assert str(error.value) == expected_error


@pytest.mark.parametrize(
    ("filename", "content", "expected_error"),
    [
        ("source.txt", b"content", "仅支持 PDF、Markdown、PPT 或 PPTX 资料"),
        ("source.md", b"", "上传文件为空"),
    ],
)
def test_file_validation_precedes_other_base_rejection(
    tmp_path: Path,
    filename: str,
    content: bytes,
    expected_error: str,
) -> None:
    workspaces = WorkspaceLookup()
    service = _service(tmp_path, workspaces)

    with pytest.raises(ValueError) as error:
        service.upload_document(
            "workspace-1",
            BytesIO(content),
            filename=filename,
            content_type=None,
            source_type="other",
            knowledge_base_id="core-1",
            license_confirmed=False,
        )

    assert str(error.value) == expected_error
    assert workspaces.called


def test_other_base_rejection_precedes_document_persistence(tmp_path: Path) -> None:
    service = _service(tmp_path, WorkspaceLookup())

    with pytest.raises(ValueError) as error:
        service.upload_document(
            "workspace-1",
            BytesIO(b"content"),
            filename="source.md",
            content_type="text/markdown",
            source_type="other",
            knowledge_base_id="core-1",
            license_confirmed=False,
        )

    assert str(error.value) == "未分类资料不能进入知识库"
