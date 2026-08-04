from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TypedDict

from examtwin.config import Settings
from examtwin.observability import safe_exception_extra
from examtwin.persistence.session import utcnow
from examtwin.storage import ManagedObjectStore, ObjectMetadata

MANAGED_PREFIXES = ("corpus/md", "paper-jobs", "answer-artifacts")
logger = logging.getLogger(__name__)


class ObjectMigrationResult(TypedDict):
    execute: bool
    discovered: int
    migrated: int
    skipped: int
    failed: int
    errors: list[str]


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
) -> ObjectMigrationResult:
    root = settings.object_store_root.resolve()
    candidates = [
        path
        for prefix in MANAGED_PREFIXES
        for path in (root / prefix).rglob("*")
        if path.is_file() and not path.name.startswith(".")
    ]
    result: ObjectMigrationResult = {
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
                result["skipped"] += 1
            else:
                with source.open("rb") as stream:
                    store.put_stream(
                        key,
                        stream,
                        max_bytes=max(1, source.stat().st_size),
                        metadata=metadata,
                    )
                result["migrated"] += 1
        except Exception as error:
            result["failed"] += 1
            errors.append(f"{key}: {type(error).__name__}: {error}"[:500])
    result["errors"] = errors
    return result


def run_storage_gc_forever(
    store: ManagedObjectStore,
    *,
    batch_size: int,
    interval_seconds: int,
    report: Callable[[dict[str, int]], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_backoff_seconds: int = 300,
) -> None:
    consecutive_failures = 0
    while True:
        try:
            result = store.collect_expired(limit=batch_size)
        except Exception as error:
            consecutive_failures += 1
            retry_in = min(
                max_backoff_seconds,
                max(1, min(interval_seconds, 2 ** min(consecutive_failures, 8))),
            )
            logger.error(
                "storage_gc_cycle_failed",
                extra={
                    "event": "storage_gc_cycle_failed",
                    "retry_in_seconds": retry_in,
                    **safe_exception_extra(error),
                },
            )
            sleep(retry_in)
            continue
        consecutive_failures = 0
        if report is not None:
            try:
                report(result)
            except Exception as error:
                logger.error(
                    "storage_gc_report_failed",
                    extra={
                        "event": "storage_gc_report_failed",
                        **safe_exception_extra(error),
                    },
                )
        sleep(interval_seconds)
