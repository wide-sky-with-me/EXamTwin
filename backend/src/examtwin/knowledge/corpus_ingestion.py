from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from llama_index.core import Document
from llama_index.readers.mineru import MinerUReader
from tenacity import Retrying, stop_after_attempt, wait_exponential

from examtwin.contracts.common import JobResult
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.knowledge.source_preprocessing import prepare_for_mineru, restore_source_pages
from examtwin.platform.cache_paths import (
    MarkdownCacheMissing,
    MarkdownCacheStore,
    resolve_markdown_cache_path,
)
from examtwin.platform.config import Settings
from examtwin.platform.storage import ManagedObjectStore
from examtwin.subjects.public import SubjectContext


def _frontmatter(metadata: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        rendered = json.dumps(value, ensure_ascii=False)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def render_documents(documents: list[Document]) -> str:
    sections: list[str] = []
    for document in documents:
        page = document.metadata.get("page")
        if page is None:
            pages = document.metadata.get("pages")
            if pages:
                sections.append(
                    f"\n\n<!-- pages:{pages} -->\n\n## Pages {pages}\n\n{document.text.strip()}"
                )
            else:
                sections.append(document.text.strip())
        else:
            sections.append(
                f"\n\n<!-- page:{page} -->\n\n## Page {page}\n\n{document.text.strip()}"
            )
    return "".join(sections).strip() + "\n"


class CorpusIngestor:
    def __init__(
        self,
        documents: CorpusRepository,
        settings: Settings,
        subject: SubjectContext,
        object_store: ManagedObjectStore | None = None,
    ):
        self.documents = documents
        self.settings = settings
        self.subject = subject
        self.object_store = object_store
        self.cache = MarkdownCacheStore(object_store or settings.markdown_dir)

    def _reader(self, *, pages: str | None = None, split_pages: bool = False) -> MinerUReader:
        token = (
            self.settings.mineru_token.get_secret_value()
            if self.settings.mineru_token is not None
            else None
        )
        return MinerUReader(
            mode=self.settings.mineru_mode,
            token=token,
            language=self.settings.mineru_language,
            pages=pages,
            split_pages=split_pages,
            ocr=True,
            formula=True,
            table=True,
            timeout=self.settings.knowledge_mineru_timeout,
        )

    def _load_mineru(
        self,
        source: Path,
        metadata: dict[str, Any],
        *,
        pages: str | None = None,
    ) -> list[Document]:
        attempts = Retrying(
            reraise=True,
            stop=stop_after_attempt(self.settings.knowledge_mineru_max_attempts),
            wait=wait_exponential(
                multiplier=self.settings.knowledge_mineru_retry_delay_seconds,
                min=self.settings.knowledge_mineru_retry_delay_seconds,
                max=self.settings.knowledge_mineru_retry_max_seconds,
            ),
        )
        for attempt in attempts:
            with attempt:
                return self._reader(pages=pages).load_data(source, extra_info=metadata)
        raise RuntimeError("MinerU retry policy completed without a result")

    def convert(self, row: dict[str, Any], *, force: bool = False) -> tuple[str, bool]:
        self.subject.require(str(row.get("subject_code") or ""))
        object_key = row.get("object_key")
        if object_key:
            if self.object_store is None:
                raise RuntimeError("对象存储来源需要配置 ManagedObjectStore")
            source = self.object_store.materialize(str(object_key))
        else:
            source = Path(row["path"])
        document_id = str(row["id"])
        source_checksum = str(row.get("checksum") or "").strip()
        if not source_checksum:
            raise ValueError("Source document checksum is required for conversion")
        provenance_matches = str(row.get("converted_source_checksum") or "") == source_checksum
        if provenance_matches and not force:
            stored_path = str(row.get("markdown_path") or "")
            if stored_path:
                try:
                    target = resolve_markdown_cache_path(
                        self.settings,
                        document_id,
                        stored_path,
                    )
                except (OSError, MarkdownCacheMissing):
                    pass
                else:
                    self.documents.update_status(
                        document_id,
                        "converted",
                        markdown_path=stored_path,
                        converted_source_checksum=source_checksum,
                    )
                    return str(target), False
            if self.cache.exists(document_id):
                target = self.cache.resolve(document_id)
                legacy_key = self.cache.key(document_id)
                self.documents.update_status(
                    document_id,
                    "converted",
                    markdown_path=legacy_key,
                    converted_source_checksum=source_checksum,
                )
                return str(target), False

        if self.cache.exists(document_id, source_checksum=source_checksum):
            target = self.cache.resolve(document_id, source_checksum=source_checksum)
            versioned_key = self.cache.key(document_id, source_checksum=source_checksum)
            self.documents.update_status(
                document_id,
                "converted",
                markdown_path=versioned_key,
                converted_source_checksum=source_checksum,
            )
            return str(target), False

        self.documents.update_status(row["id"], "converting")
        try:
            metadata = {
                "document_id": row["id"],
                "subject_code": self.subject.subject_code,
                "source": str(source),
                "source_type": row["source_type"],
                "authority_tier": row.get("authority_tier", "supplementary"),
                "source_role": row.get("source_role", "excluded"),
                "knowledge_base_id": row.get("knowledge_base_id"),
                "pair_key": row.get("pair_key"),
                "unit_code": row.get("unit_code"),
                "source_checksum": source_checksum,
            }
            if source.suffix.lower() in {".md", ".markdown"}:
                body = source.read_text(encoding="utf-8")
            else:
                with prepare_for_mineru(
                    source,
                    page_count=row.get("page_count"),
                ) as prepared_sources:
                    parts: list[str] = []
                    for prepared in prepared_sources:
                        part_suffix = prepared.cache_suffix
                        is_derived_part = prepared.page_range is not None
                        if is_derived_part and self.cache.exists(
                            document_id,
                            part_suffix,
                            source_checksum=source_checksum,
                        ):
                            parts.append(
                                self.cache.read(
                                    document_id,
                                    part_suffix,
                                    source_checksum=source_checksum,
                                )
                            )
                            continue
                        documents = self._load_mineru(prepared.path, metadata)
                        restore_source_pages(documents, prepared)
                        rendered = render_documents(documents)
                        if is_derived_part and not self.cache.exists(
                            document_id,
                            part_suffix,
                            source_checksum=source_checksum,
                        ):
                            self.cache.write(
                                document_id,
                                rendered,
                                suffix=part_suffix,
                                source_checksum=source_checksum,
                            )
                        parts.append(rendered)
                    body = "\n\n".join(parts)
            versioned_key = self.cache.key(document_id, source_checksum=source_checksum)
            created = not self.cache.exists(document_id, source_checksum=source_checksum)
            if created:
                target = self.cache.write(
                    document_id,
                    _frontmatter(metadata) + body,
                    source_checksum=source_checksum,
                )
            else:
                target = self.cache.resolve(document_id, source_checksum=source_checksum)
            self.documents.update_status(
                document_id,
                "converted",
                markdown_path=versioned_key,
                error=None,
                converted_source_checksum=source_checksum,
            )
            return str(target), created
        except Exception as error:
            self.documents.update_status(row["id"], "failed", error=str(error)[:2000])
            raise

    def convert_batch(
        self,
        *,
        document_ids: list[str] | None = None,
        source_types: list[str] | None = None,
        authority_tiers: list[str] | None = None,
        limit: int | None = None,
        workers: int = 1,
        force: bool = False,
    ) -> JobResult:
        rows = self.documents.list(
            document_ids=document_ids,
            source_types=source_types,
            authority_tiers=authority_tiers,
            subject_code=self.subject.subject_code,
            limit=limit,
        )

        result = JobResult(processed=len(rows), succeeded=0, failed=0, skipped=0)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
            futures = {executor.submit(self.convert, row, force=force): row for row in rows}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    _, created = future.result()
                    if created:
                        result.succeeded += 1
                    else:
                        result.skipped += 1
                except Exception as error:
                    result.failed += 1
                    result.errors.append(f"{row['filename']}: {str(error)[:300]}")
        return result
