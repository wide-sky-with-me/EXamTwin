from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from examtwin.config import Settings
from examtwin.persistence.object_catalog_repository import ObjectCatalogRepository
from examtwin.persistence.session import utcnow
from examtwin.storage import (
    LocalObjectStore,
    ManagedObjectStore,
    ObjectMetadata,
    StoredObject,
)

from backend.tests.paper_job_support import _job_service, _test_database


class RecordingCatalog:
    def __init__(self) -> None:
        self.puts: list[tuple[StoredObject, ObjectMetadata]] = []
        self.expired = ["paper-jobs/job-1/source.pdf"]
        self.deleted: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def record_put(self, stored: StoredObject, metadata: ObjectMetadata) -> None:
        self.puts.append((stored, metadata))

    def claim_expired(self, *, limit: int) -> list[str]:
        return self.expired[:limit]

    def mark_deleted(self, key: str) -> None:
        self.deleted.append(key)

    def mark_delete_failed(self, key: str, error: str) -> None:
        self.failed.append((key, error))


def test_managed_local_object_store_enforces_ceiling_and_records_lifecycle(
    tmp_path: Path,
) -> None:
    catalog = RecordingCatalog()
    store = ManagedObjectStore(LocalObjectStore(tmp_path), catalog)
    metadata = ObjectMetadata(
        purpose="paper_source",
        owner_type="paper_job",
        owner_id="job-1",
        retain_until=datetime(2026, 9, 1, tzinfo=UTC),
    )

    stored = store.put_stream(
        "paper-jobs/job-1/source.pdf",
        BytesIO(b"pdf-body"),
        max_bytes=20,
        metadata=metadata,
    )

    assert store.materialize(stored.key).read_bytes() == b"pdf-body"
    assert stored.size_bytes == 8
    assert len(stored.checksum_sha256) == 64
    assert catalog.puts == [(stored, metadata)]
    assert store.collect_expired(limit=10) == {"claimed": 1, "deleted": 1, "failed": 0}
    assert catalog.deleted == [stored.key]
    assert not store.exists(stored.key)

    with pytest.raises(ValueError, match="容量限制"):
        store.put_stream(
            "paper-jobs/job-2/source.pdf",
            BytesIO(b"too-large"),
            max_bytes=3,
            metadata=metadata,
        )
    assert not store.exists("paper-jobs/job-2/source.pdf")


@pytest.mark.integration
def test_gc_does_not_claim_expired_objects_owned_by_an_active_paper_job(
    tmp_path: Path,
) -> None:
    database = _test_database()
    jobs = _job_service(database, Settings(object_store_local_root=tmp_path))
    created = jobs.create_job("paper.md", b"# Question 1\nFind x.", unit_code="P1")
    catalog = ObjectCatalogRepository(database.sessions)
    key = f"paper-jobs/{created.job_id}/source.md"
    catalog.record_put(
        StoredObject(
            key=key,
            size_bytes=10,
            checksum_sha256="a" * 64,
            content_type="text/markdown",
            backend="local",
        ),
        ObjectMetadata(
            purpose="paper_source",
            owner_type="paper_job",
            owner_id=created.job_id,
            retain_until=utcnow() - timedelta(days=1),
        ),
    )

    assert catalog.claim_expired(limit=10) == []

    database.execute(
        "UPDATE paper_jobs SET status='completed', stage='completed' WHERE id=?",
        (created.job_id,),
    )
    assert catalog.claim_expired(limit=10) == [key]
