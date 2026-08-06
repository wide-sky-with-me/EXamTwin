from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from examtwin.platform.config import Settings
from examtwin.platform.database.session import utcnow
from examtwin.platform.object_catalog_repository import ObjectCatalogRepository
from examtwin.platform.storage import (
    LocalObjectStore,
    ManagedObjectStore,
    ObjectMetadata,
    S3ObjectStore,
    StoredObject,
)
from examtwin.platform.storage_lifecycle import run_storage_gc_forever

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


class StopGcLoop(RuntimeError):
    pass


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


def test_gc_worker_recovers_after_a_failed_collection_cycle(tmp_path: Path) -> None:
    class FlakyStore:
        calls = 0

        def collect_expired(self, *, limit: int) -> dict[str, int]:
            assert limit == 7
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("catalog unavailable")
            return {"claimed": 1, "deleted": 1, "failed": 0}

    store = FlakyStore()
    delays: list[float] = []
    reports: list[dict[str, int]] = []

    def stop_after_recovery(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 2:
            raise StopGcLoop

    with pytest.raises(StopGcLoop):
        run_storage_gc_forever(
            store,  # type: ignore[arg-type]
            batch_size=7,
            interval_seconds=60,
            report=reports.append,
            sleep=stop_after_recovery,
        )

    assert store.calls == 2
    assert delays == [2, 60]
    assert reports == [{"claimed": 1, "deleted": 1, "failed": 0}]


@pytest.mark.integration
def test_s3_object_store_round_trip_uses_disposable_cache(tmp_path: Path) -> None:
    endpoint = os.environ.get("EXAMTWIN_TEST_S3_ENDPOINT")
    if not endpoint:
        pytest.skip("EXAMTWIN_TEST_S3_ENDPOINT is not configured")
    store = S3ObjectStore(
        endpoint_url=endpoint,
        bucket=os.environ.get("EXAMTWIN_TEST_S3_BUCKET", "examtwin"),
        access_key=os.environ.get("EXAMTWIN_TEST_S3_ACCESS_KEY", "examtwin"),
        secret_key=os.environ.get(
            "EXAMTWIN_TEST_S3_SECRET_KEY",
            "examtwin_dev_secret",
        ),
        region="us-east-1",
        cache_root=tmp_path / "cache",
    )
    key = f"integration/{uuid4().hex}/source.md"
    metadata = ObjectMetadata(
        purpose="integration_test",
        owner_type="test_run",
        owner_id=key,
    )
    stored = None
    try:
        stored = store.put_stream(
            key,
            BytesIO(b"# durable object\n"),
            max_bytes=1024,
            metadata=metadata,
        )
        assert stored.backend == "s3"
        assert store.exists(key) is True
        store.cache.delete(key)
        assert store.materialize(key).read_bytes() == b"# durable object\n"
    finally:
        if stored is not None:
            store.delete(key)
    assert store.exists(key) is False
