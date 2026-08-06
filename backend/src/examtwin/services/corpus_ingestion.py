from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from examtwin.config import Settings
from examtwin.persistence.corpus_repository import CorpusRepository
from examtwin.schemas.common import JobResult
from examtwin.services.cache_paths import MarkdownCacheStore
from examtwin.services.source_preprocessing import prepare_for_mineru, restore_source_pages
from examtwin.services.subject_context import SubjectContext
from examtwin.storage import ManagedObjectStore
from llama_index.core import Document
from llama_index.readers.mineru import MinerUReader
from tenacity import retry, stop_after_attempt, wait_exponential


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
            timeout=1200,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    def _load_mineru(
        self,
        source: Path,
        metadata: dict[str, Any],
        *,
        pages: str | None = None,
    ) -> list[Document]:
        return self._reader(pages=pages).load_data(source, extra_info=metadata)

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
        if self.cache.exists(document_id) and not force:
            target = self.cache.resolve(document_id)
            self.documents.update_status(
                document_id,
                "converted",
                markdown_path=self.cache.key(document_id),
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
                        if (
                            is_derived_part
                            and self.cache.exists(document_id, part_suffix)
                            and not force
                        ):
                            parts.append(self.cache.read(document_id, part_suffix))
                            continue
                        documents = self._load_mineru(prepared.path, metadata)
                        restore_source_pages(documents, prepared)
                        rendered = render_documents(documents)
                        if is_derived_part:
                            self.cache.write(document_id, rendered, suffix=part_suffix)
                        parts.append(rendered)
                    body = "\n\n".join(parts)
            target = self.cache.write(document_id, _frontmatter(metadata) + body)
            self.documents.update_status(
                document_id,
                "converted",
                markdown_path=self.cache.key(document_id),
                error=None,
            )
            return str(target), True
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
