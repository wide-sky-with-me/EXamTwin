from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from examtwin.config import Settings
from examtwin.persistence.session import utcnow
from examtwin.storage import ManagedObjectStore, ObjectMetadata

MANAGED_PREFIXES = ("corpus/md", "paper-jobs", "answer-artifacts")


def _migration_metadata(settings: Settings, key: str, source: Path) -> ObjectMetadata:
    owner_id = source.stem
    retain_until = None
    purpose = "markdown_cache"
    owner_type = "source_document"
    if key.startswith("paper-jobs/"):
        parts = key.split("/")
        owner_id = parts[1] if len(parts) > 1 else source.stem
        owner_type = "paper_job"
        purpose = "paper_source" if source.name.startswith("source.") else "paper_derived"
        retain_until = utcnow() + timedelta(days=settings.paper_object_retention_days)
    elif key.startswith("answer-artifacts/"):
        owner_id = source.stem
        owner_type = "answer_asset"
        purpose = "answer_image"
        retain_until = utcnow() + timedelta(days=settings.answer_artifact_retention_days)
    return ObjectMetadata(
        purpose=purpose,
        owner_type=owner_type,
        owner_id=owner_id,
        retain_until=retain_until,
    )


def migrate_local_objects(
    settings: Settings,
    store: ManagedObjectStore,
    *,
    execute: bool,
) -> dict[str, object]:
    root = settings.object_store_root.resolve()
    candidates = [
        path
        for prefix in MANAGED_PREFIXES
        for path in (root / prefix).rglob("*")
        if path.is_file() and not path.name.startswith(".")
    ]
    result: dict[str, object] = {
        "execute": execute,
        "discovered": len(candidates),
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
    }
    if not execute:
        return result

    errors: list[str] = []
    for source in candidates:
        key = source.relative_to(root).as_posix()
        try:
            metadata = _migration_metadata(settings, key, source)
            if store.exists(key):
                store.register_existing(key, metadata=metadata)
                result["skipped"] = int(result["skipped"]) + 1
            else:
                with source.open("rb") as stream:
                    store.put_stream(
                        key,
                        stream,
                        max_bytes=max(1, source.stat().st_size),
                        metadata=metadata,
                    )
                result["migrated"] = int(result["migrated"]) + 1
        except Exception as error:
            result["failed"] = int(result["failed"]) + 1
            errors.append(f"{key}: {type(error).__name__}: {error}"[:500])
    result["errors"] = errors
    return result


def run_storage_gc_forever(
    store: ManagedObjectStore,
    *,
    batch_size: int,
    interval_seconds: int,
    report: Callable[[dict[str, int]], None] | None = None,
) -> None:
    while True:
        result = store.collect_expired(limit=batch_size)
        if report is not None:
            report(result)
        time.sleep(interval_seconds)
