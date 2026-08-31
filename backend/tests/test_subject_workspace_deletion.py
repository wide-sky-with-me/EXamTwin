from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from examtwin.app.main import app
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import PaperJobModel, SourceDocumentModel, SubjectModel
from examtwin.platform.database.session import create_session_factory, utcnow
from examtwin.subjects.workspace_repository import WorkspaceRepository
from fastapi.testclient import TestClient
from sqlalchemy import delete, update


@pytest.mark.integration
def test_batch_delete_subject_workspaces_is_atomic_and_rejects_active_jobs() -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    repository = WorkspaceRepository(sessions)
    token = uuid.uuid4().hex
    subject_ids = [f"delete-subject-{token}-a", f"delete-subject-{token}-b"]
    subject_codes = [f"D{token[:8]}A", f"D{token[:8]}B"]
    job_id = f"delete-job-{token}"
    now = utcnow()

    for subject_id, subject_code in zip(subject_ids, subject_codes, strict=True):
        repository.create_subject(
            subject_id=subject_id,
            subject_code=subject_code,
            title=f"Delete test {subject_code}",
            board_name="Test board",
        )
    with sessions.begin() as session:
        session.add(
            PaperJobModel(
                id=job_id,
                subject_pack_id=subject_ids[0],
                subject_code=subject_codes[0],
                filename="active.pdf",
                suffix=".pdf",
                unit_code="U1",
                source_path="delete-test-source",
                status="answering",
                stage="answering",
                lease_token=f"delete-test-lease-{token}",
                lease_expires_at=now + timedelta(minutes=5),
                error=None,
                created_at=now,
                updated_at=now,
            )
        )

    try:
        with TestClient(app) as client:
            blocked = client.post(
                "/api/v1/subject-workspaces/batch-delete",
                json={"subject_ids": subject_ids},
            )
            assert blocked.status_code == 409
            assert "正在处理的试卷任务" in blocked.json()["detail"]
            assert all(
                repository.resolve_subject(subject_id) is not None for subject_id in subject_ids
            )

            with sessions.begin() as session:
                session.execute(
                    update(PaperJobModel)
                    .where(PaperJobModel.id == job_id)
                    .values(status="failed", stage="failed")
                )

            deleted = client.post(
                "/api/v1/subject-workspaces/batch-delete",
                json={"subject_ids": subject_ids},
            )
            assert deleted.status_code == 200
            assert deleted.json() == {
                "deleted_ids": subject_ids,
                "deleted_count": 2,
            }

        with sessions() as session:
            assert session.get(PaperJobModel, job_id) is None
            assert all(session.get(SubjectModel, subject_id) is None for subject_id in subject_ids)
    finally:
        with sessions.begin() as session:
            session.execute(
                update(PaperJobModel)
                .where(PaperJobModel.id == job_id)
                .values(status="failed", stage="failed")
            )
        remaining = [
            subject_id
            for subject_id in subject_ids
            if repository.resolve_subject(subject_id) is not None
        ]
        if remaining:
            repository.delete_subjects(remaining)


@pytest.mark.integration
def test_batch_delete_rejects_installed_subjects_before_deleting_custom_ones() -> None:
    settings = get_settings()
    repository = WorkspaceRepository(create_session_factory(settings.database_url))
    token = uuid.uuid4().hex
    subject_id = f"delete-subject-{token}"
    repository.create_subject(
        subject_id=subject_id,
        subject_code=f"D{token[:8]}",
        title="Protected deletion test",
        board_name="Test board",
    )

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/subject-workspaces/batch-delete",
                json={
                    "subject_ids": [
                        subject_id,
                        "oxfordaqa-mathematics-9660",
                    ]
                },
            )
        assert response.status_code == 409
        assert response.json()["detail"] == "内置科目工作区不能删除"
        assert repository.resolve_subject(subject_id) is not None
    finally:
        if repository.resolve_subject(subject_id) is not None:
            repository.delete_subjects([subject_id])


@pytest.mark.integration
def test_create_subject_workspace_maps_public_id_to_repository_subject_id() -> None:
    settings = get_settings()
    repository = WorkspaceRepository(create_session_factory(settings.database_url))
    token = uuid.uuid4().hex
    subject_id = f"create-subject-{token}"

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/subject-workspaces",
                json={
                    "id": subject_id,
                    "subject_code": f"C{token[:8]}",
                    "title": "Created through API",
                    "board_name": "Test board",
                    "icon": "book-open",
                    "color": "#2F6FED",
                },
            )

        assert response.status_code == 201
        assert response.json()["id"] == subject_id
        assert repository.resolve_subject(subject_id) is not None
    finally:
        if repository.resolve_subject(subject_id) is not None:
            repository.delete_subjects([subject_id])


@pytest.mark.integration
def test_installed_subject_synchronization_preserves_user_presentation() -> None:
    settings = get_settings()
    repository = WorkspaceRepository(create_session_factory(settings.database_url))
    token = uuid.uuid4().hex
    subject_id = f"sync-subject-{token}"
    package = SimpleNamespace(
        pack=SimpleNamespace(
            id=subject_id,
            subject_code=f"S{token[:8]}",
            title="Package title",
            board=SimpleNamespace(name="Package board"),
        )
    )

    try:
        repository.synchronize_installed_subjects([package])
        repository.update_subject_presentation(
            subject_id,
            title="Teacher title",
            icon="atom",
            color="#123456",
        )

        repository.synchronize_installed_subjects([package])

        subject = repository.require_subject(subject_id)
        assert subject["title"] == "Teacher title"
        assert subject["icon"] == "atom"
        assert subject["color"] == "#123456"
    finally:
        if repository.resolve_subject(subject_id) is not None:
            repository.delete_subjects([subject_id])


@pytest.mark.integration
def test_archived_documents_remain_available_to_immutable_consumers() -> None:
    settings = get_settings()
    sessions = create_session_factory(settings.database_url)
    repository = CorpusRepository(sessions)
    document_id = f"archived-source-{uuid.uuid4().hex}"

    try:
        repository.register_generated_mark_scheme(
            document_id=document_id,
            subject_id="oxfordaqa-mathematics-9660",
            subject_code="9660",
            filename="archived.md",
            checksum=uuid.uuid4().hex,
            pair_key="2026-jan-unit-p1",
            markdown_path=f"generated/mark-schemes/{document_id}.md",
        )
        repository.archive(document_id, subject_code="9660")

        assert repository.get_active(document_id) is None
        assert repository.get(document_id) is not None
        assert repository.get_converted(document_id) is not None
    finally:
        with sessions.begin() as session:
            session.execute(
                delete(SourceDocumentModel).where(SourceDocumentModel.id == document_id)
            )
