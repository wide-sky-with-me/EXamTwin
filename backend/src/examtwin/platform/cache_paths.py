from __future__ import annotations

from pathlib import Path

from examtwin.platform.config import Settings
from examtwin.platform.storage import (
    LocalObjectStore,
    ManagedObjectStore,
    ObjectMetadata,
    build_storage_backend,
)


class MarkdownCacheMissing(LookupError):
    """Raised when a stored Markdown path cannot be resolved inside the configured cache."""


class MarkdownCacheStore:
    """Canonical conversion-cache owner with legacy filesystem compatibility."""

    def __init__(self, store: ManagedObjectStore | Path) -> None:
        if isinstance(store, Path):
            self.store = ManagedObjectStore(LocalObjectStore(store))
            self.prefix = ""
        else:
            self.store = store
            self.prefix = "corpus/md/"

    def key(self, document_id: str, suffix: str = ".md") -> str:
        return f"{self.prefix}{document_id}{suffix}"

    def exists(self, document_id: str, suffix: str = ".md") -> bool:
        return self.store.exists(self.key(document_id, suffix))

    def read(self, document_id: str, suffix: str = ".md") -> str:
        return self.store.materialize(self.key(document_id, suffix)).read_text(encoding="utf-8")

    def write(
        self,
        document_id: str,
        content: str,
        *,
        suffix: str = ".md",
    ) -> Path:
        stored = self.store.put_bytes(
            self.key(document_id, suffix),
            content,
            metadata=ObjectMetadata(
                purpose="markdown_cache",
                owner_type="source_document",
                owner_id=document_id,
                retain_until=None,
                content_type="text/markdown; charset=utf-8",
            ),
        )
        return self.store.materialize(stored.key)

    def resolve(self, document_id: str, suffix: str = ".md") -> Path:
        return self.store.materialize(self.key(document_id, suffix))


def resolve_markdown_cache_path(
    settings: Settings,
    document_id: str,
    stored_path: str,
) -> Path:
    """Resolve current and legacy DB paths without escaping the cache root.

    Older rows contain absolute host paths. Containers mount the same cache at a
    different root, so the stable document-id filename is the portable identity.
    """
    root = settings.markdown_dir.resolve()
    raw_path = Path(stored_path)
    expected_name = f"{document_id}.md"

    # After an S3 migration, legacy local files are rollback copies rather than
    # the canonical read source. Prefer the configured backend while accepting
    # old absolute DB paths that cannot be interpreted as object keys.
    if settings.object_store_backend == "s3":
        backend = build_storage_backend(settings)
        for key in (f"corpus/md/{expected_name}", stored_path):
            try:
                candidate = backend.materialize(key)
            except (LookupError, ValueError):
                continue
            if candidate.suffix.lower() == ".md" and candidate.is_file():
                return candidate

    candidates = [raw_path.resolve()]
    if not raw_path.is_absolute():
        candidates.append((root / raw_path).resolve())

    if raw_path.name == expected_name:
        candidates.append((root / expected_name).resolve())
    object_root = settings.object_store_root.resolve()
    if not raw_path.is_absolute():
        candidates.append((object_root / raw_path).resolve())

    for candidate in dict.fromkeys(candidates):
        if (
            candidate.suffix.lower() == ".md"
            and candidate.is_relative_to(root)
            and candidate.is_file()
        ):
            return candidate
    raise MarkdownCacheMissing(f"Markdown cache is unavailable for document {document_id}")
