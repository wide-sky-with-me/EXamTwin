from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, BinaryIO

import pymupdf

from examtwin.platform.database.session import utcnow
from examtwin.platform.storage import LocalObjectStore, ManagedObjectStore, ObjectMetadata


@dataclass
class _PageLockEntry:
    lock: threading.Lock
    users: int = 0


class PaperSourceStore:
    """Own uploaded papers and all job-scoped derived objects."""

    def __init__(
        self,
        store: ManagedObjectStore | Path,
        *,
        retention_days: int = 30,
    ) -> None:
        if isinstance(store, Path):
            self.store = ManagedObjectStore(LocalObjectStore(store))
            self.prefix = ""
        else:
            self.store = store
            self.prefix = "paper-jobs/"
        self.retention_days = retention_days
        self._page_locks: dict[str, _PageLockEntry] = {}
        self._page_locks_guard = threading.Lock()

    def _key(self, relative_path: str) -> str:
        return f"{self.prefix}{relative_path}"

    def _metadata(self, relative_path: str, *, purpose: str) -> ObjectMetadata:
        owner_id = relative_path.split("/", 1)[0]
        return ObjectMetadata(
            purpose=purpose,
            owner_type="paper_job",
            owner_id=owner_id,
            retain_until=utcnow() + timedelta(days=self.retention_days),
        )

    def write(self, relative_path: str, content: bytes | str) -> Path:
        stored = self.store.put_bytes(
            self._key(relative_path),
            content,
            metadata=self._metadata(relative_path, purpose="paper_derived"),
        )
        return self.store.materialize(stored.key)

    def write_upload(
        self,
        relative_path: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
    ) -> tuple[Path, int]:
        try:
            stored = self.store.put_stream(
                self._key(relative_path),
                stream,
                max_bytes=max_bytes,
                metadata=self._metadata(relative_path, purpose="paper_source"),
            )
        except ValueError as error:
            message = str(error)
            if "超过容量限制" in message:
                raise ValueError("试卷文件超过 25 MB 限制") from error
            if "为空" in message:
                raise ValueError("上传的试卷为空") from error
            raise
        return self.store.materialize(stored.key), stored.size_bytes

    def remove(self, relative_path: str) -> None:
        self.store.delete(self._key(relative_path))

    def extend_retention(self, job_id: str) -> None:
        self.store.extend_retention(
            "paper_job",
            job_id,
            utcnow() + timedelta(days=self.retention_days),
        )

    def resolve(self, relative_path: str) -> Path:
        try:
            return self.store.materialize(self._key(relative_path))
        except LookupError:
            # Callers also use this for not-yet-created job work paths and directories.
            return self.store.working_path(self._key(relative_path))

    def source_file(self, record: Mapping[str, Any]) -> tuple[Path, str, str]:
        try:
            path = self.store.materialize(self._key(str(record["source_path"])))
        except LookupError as error:
            raise LookupError("原始试卷文件不存在") from error
        return path, str(record["filename"]), str(record["suffix"])

    def source_page(self, record: Mapping[str, Any], job_id: str, page_number: int) -> Path:
        _source_path, _filename, suffix = self.source_file(record)
        if suffix != ".pdf":
            raise ValueError("只有 PDF 试卷可以渲染原卷页图")
        if page_number < 1:
            raise ValueError("原卷页码必须从 1 开始")

        relative_path = f"{job_id}/source-pages/{page_number:04d}.jpg"
        key = self._key(relative_path)
        if self.store.exists(key):
            return self.store.materialize(key)
        with self._page_lock(key):
            if self.store.exists(key):
                return self.store.materialize(key)
            source_path, _filename, _suffix = self.source_file(record)
            with pymupdf.open(source_path) as document:
                if page_number > document.page_count:
                    raise ValueError("原卷页码超出试卷范围")
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.8, 1.8), alpha=False)
                content = pixmap.tobytes("jpeg", jpg_quality=88)
            return self.write(relative_path, content)

    @contextmanager
    def _page_lock(self, key: str) -> Iterator[None]:
        with self._page_locks_guard:
            entry = self._page_locks.setdefault(key, _PageLockEntry(threading.Lock()))
            entry.users += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._page_locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._page_locks.get(key) is entry:
                    self._page_locks.pop(key, None)
