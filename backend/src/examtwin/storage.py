from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol
from uuid import uuid4

from examtwin.local_storage import SafeLocalStorage


@dataclass(frozen=True)
class ObjectMetadata:
    purpose: str
    owner_type: str
    owner_id: str
    retain_until: datetime | None = None
    content_type: str | None = None


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str
    backend: str
    bucket: str | None = None


class ObjectCatalog(Protocol):
    def record_put(self, stored: StoredObject, metadata: ObjectMetadata) -> None: ...

    def claim_expired(self, *, limit: int) -> list[str]: ...

    def mark_deleted(self, key: str) -> None: ...

    def mark_delete_failed(self, key: str, error: str) -> None: ...

    def stats(self) -> dict[str, object]: ...

    def extend_retention(
        self,
        owner_type: str,
        owner_id: str,
        retain_until: datetime,
    ) -> None: ...


class ObjectStore(Protocol):
    backend_name: str
    bucket_name: str | None

    def put_bytes(
        self,
        key: str,
        content: bytes | str,
        *,
        metadata: ObjectMetadata,
    ) -> StoredObject: ...

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: ObjectMetadata,
    ) -> StoredObject: ...

    def materialize(self, key: str) -> Path: ...

    def working_path(self, key: str) -> Path: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def ping(self) -> None: ...


def normalize_object_key(key: str) -> str:
    normalized = str(PurePosixPath(key.strip().replace("\\", "/")))
    path = PurePosixPath(normalized)
    if (
        not key.strip()
        or path.is_absolute()
        or normalized in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("对象键不合法")
    return normalized


def _content_type(key: str, explicit: str | None) -> str:
    return explicit or mimetypes.guess_type(key)[0] or "application/octet-stream"


def _write_bounded(
    path: Path,
    stream: BinaryIO,
    *,
    max_bytes: int,
    chunk_bytes: int = 1024 * 1024,
) -> tuple[int, str]:
    if max_bytes < 1 or chunk_bytes < 1:
        raise ValueError("存储流容量参数必须为正数")
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("wb") as output:
            while block := stream.read(chunk_bytes):
                total += len(block)
                if total > max_bytes:
                    raise ValueError("上传文件超过容量限制")
                digest.update(block)
                output.write(block)
        if total == 0:
            raise ValueError("上传文件为空")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return total, digest.hexdigest()


class LocalObjectStore:
    """Filesystem-backed ObjectStore used for development and deterministic tests."""

    backend_name = "local"
    bucket_name = None

    def __init__(self, root: Path) -> None:
        self.storage = SafeLocalStorage(root)

    def put_bytes(
        self,
        key: str,
        content: bytes | str,
        *,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        normalized = normalize_object_key(key)
        encoded = content.encode("utf-8") if isinstance(content, str) else content
        self.storage.write_atomic(normalized, encoded)
        return StoredObject(
            key=normalized,
            size_bytes=len(encoded),
            checksum_sha256=hashlib.sha256(encoded).hexdigest(),
            content_type=_content_type(normalized, metadata.content_type),
            backend=self.backend_name,
        )

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        normalized = normalize_object_key(key)
        path = self.storage.resolve(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        size, checksum = _write_bounded(temporary, stream, max_bytes=max_bytes)
        temporary.replace(path)
        return StoredObject(
            key=normalized,
            size_bytes=size,
            checksum_sha256=checksum,
            content_type=_content_type(normalized, metadata.content_type),
            backend=self.backend_name,
        )

    def materialize(self, key: str) -> Path:
        return self.storage.resolve(normalize_object_key(key), require_file=True)

    def working_path(self, key: str) -> Path:
        return self.storage.resolve(normalize_object_key(key))

    def delete(self, key: str) -> None:
        self.storage.delete(normalize_object_key(key))

    def exists(self, key: str) -> bool:
        try:
            return self.storage.resolve(normalize_object_key(key)).is_file()
        except ValueError:
            return False

    def ping(self) -> None:
        self.storage.root.mkdir(parents=True, exist_ok=True)
        if not self.storage.root.is_dir():
            raise RuntimeError("本地对象存储目录不可用")


class S3ObjectStore:
    """S3-compatible object store with a bounded, disposable local read cache."""

    backend_name = "s3"

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
        cache_root: Path,
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError as error:  # pragma: no cover - packaging contract
            raise RuntimeError("S3 对象存储需要安装 boto3") from error

        self.bucket = bucket
        self.bucket_name = bucket
        self._client_error = ClientError
        self.cache = SafeLocalStorage(cache_root)
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url.rstrip("/"),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except self._client_error as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(
        self,
        key: str,
        content: bytes | str,
        *,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        normalized = normalize_object_key(key)
        encoded = content.encode("utf-8") if isinstance(content, str) else content
        content_type = _content_type(normalized, metadata.content_type)
        self.ensure_bucket()
        self.client.put_object(
            Bucket=self.bucket,
            Key=normalized,
            Body=encoded,
            ContentType=content_type,
            Metadata={
                "purpose": metadata.purpose,
                "owner-type": metadata.owner_type,
                "owner-id": metadata.owner_id,
            },
        )
        self.cache.write_atomic(normalized, encoded)
        return StoredObject(
            key=normalized,
            size_bytes=len(encoded),
            checksum_sha256=hashlib.sha256(encoded).hexdigest(),
            content_type=content_type,
            backend=self.backend_name,
            bucket=self.bucket,
        )

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        normalized = normalize_object_key(key)
        cache_path = self.cache.resolve(normalized)
        temporary = cache_path.with_name(f".{cache_path.name}.{uuid4().hex}.tmp")
        size, checksum = _write_bounded(temporary, stream, max_bytes=max_bytes)
        content_type = _content_type(normalized, metadata.content_type)
        try:
            self.ensure_bucket()
            self.client.upload_file(
                str(temporary),
                self.bucket,
                normalized,
                ExtraArgs={
                    "ContentType": content_type,
                    "Metadata": {
                        "purpose": metadata.purpose,
                        "owner-type": metadata.owner_type,
                        "owner-id": metadata.owner_id,
                    },
                },
            )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.replace(cache_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return StoredObject(
            key=normalized,
            size_bytes=size,
            checksum_sha256=checksum,
            content_type=content_type,
            backend=self.backend_name,
            bucket=self.bucket,
        )

    def materialize(self, key: str) -> Path:
        normalized = normalize_object_key(key)
        cached = self.cache.resolve(normalized)
        if cached.is_file():
            return cached
        cached.parent.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_name(f".{cached.name}.{uuid4().hex}.tmp")
        try:
            self.client.download_file(self.bucket, normalized, str(temporary))
            temporary.replace(cached)
        except self._client_error as error:
            temporary.unlink(missing_ok=True)
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise LookupError("存储对象不存在") from None
            raise
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return cached

    def working_path(self, key: str) -> Path:
        return self.cache.resolve(normalize_object_key(key))

    def delete(self, key: str) -> None:
        normalized = normalize_object_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=normalized)
        self.cache.delete(normalized)

    def exists(self, key: str) -> bool:
        normalized = normalize_object_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=normalized)
            return True
        except self._client_error as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def ping(self) -> None:
        self.ensure_bucket()
        self.client.head_bucket(Bucket=self.bucket)


class ManagedObjectStore:
    """Single storage lifecycle boundary for writes, metadata, reads and GC."""

    def __init__(self, backend: ObjectStore, catalog: ObjectCatalog | None = None) -> None:
        self.backend = backend
        self.catalog = catalog

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    def put_bytes(
        self,
        key: str,
        content: bytes | str,
        *,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        stored = self.backend.put_bytes(key, content, metadata=metadata)
        if self.catalog is not None:
            self.catalog.record_put(stored, metadata)
        return stored

    def register_existing(self, key: str, *, metadata: ObjectMetadata) -> StoredObject:
        normalized = normalize_object_key(key)
        path = self.backend.materialize(normalized)
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
        stored = StoredObject(
            key=normalized,
            size_bytes=size,
            checksum_sha256=digest.hexdigest(),
            content_type=_content_type(normalized, metadata.content_type),
            backend=self.backend.backend_name,
            bucket=self.backend.bucket_name,
        )
        if self.catalog is not None:
            self.catalog.record_put(stored, metadata)
        return stored

    def put_stream(
        self,
        key: str,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: ObjectMetadata,
    ) -> StoredObject:
        stored = self.backend.put_stream(
            key,
            stream,
            max_bytes=max_bytes,
            metadata=metadata,
        )
        if self.catalog is not None:
            self.catalog.record_put(stored, metadata)
        return stored

    def materialize(self, key: str) -> Path:
        return self.backend.materialize(key)

    def working_path(self, key: str) -> Path:
        return self.backend.working_path(key)

    def delete(self, key: str) -> None:
        self.backend.delete(key)
        if self.catalog is not None:
            self.catalog.mark_deleted(normalize_object_key(key))

    def exists(self, key: str) -> bool:
        return self.backend.exists(key)

    def ping(self) -> None:
        self.backend.ping()

    def collect_expired(self, *, limit: int) -> dict[str, int]:
        if self.catalog is None:
            raise RuntimeError("对象 GC 需要持久化 catalog")
        keys = self.catalog.claim_expired(limit=limit)
        deleted = 0
        failed = 0
        for key in keys:
            try:
                self.backend.delete(key)
                self.catalog.mark_deleted(key)
                deleted += 1
            except Exception as error:
                self.catalog.mark_delete_failed(key, f"{type(error).__name__}: {error}"[:1000])
                failed += 1
        return {"claimed": len(keys), "deleted": deleted, "failed": failed}

    def stats(self) -> dict[str, object]:
        if self.catalog is None:
            raise RuntimeError("对象统计需要持久化 catalog")
        return self.catalog.stats()

    def extend_retention(
        self,
        owner_type: str,
        owner_id: str,
        retain_until: datetime,
    ) -> None:
        if self.catalog is not None:
            self.catalog.extend_retention(owner_type, owner_id, retain_until)


def build_storage_backend(settings: object) -> ObjectStore:
    """Build the configured backend without introducing persistence dependencies."""

    if settings.object_store_backend == "s3":
        return S3ObjectStore(
            endpoint_url=settings.object_store_endpoint_url,
            bucket=settings.object_store_bucket,
            access_key=settings.object_store_access_key.get_secret_value(),
            secret_key=settings.object_store_secret_key.get_secret_value(),
            region=settings.object_store_region,
            cache_root=settings.object_cache_dir,
        )
    return LocalObjectStore(settings.object_store_root)
