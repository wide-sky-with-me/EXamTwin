import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from examtwin.knowledge.corpus_ingestion import CorpusIngestor
from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.knowledge.source_preprocessing import prepare_for_mineru, restore_source_pages
from examtwin.platform.config import Settings
from examtwin.platform.database.models import (
    SourceDocumentLocationModel,
    SourceDocumentModel,
)
from examtwin.platform.storage import LocalObjectStore, ManagedObjectStore, ObjectMetadata
from examtwin.subjects.public import subject_context
from llama_index.core import Document
from pypdf import PdfReader, PdfWriter


def _write_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)


def test_long_pdf_is_physically_split_and_restores_source_pages(tmp_path: Path) -> None:
    source = tmp_path / "long.pdf"
    _write_pdf(source, 3)

    with prepare_for_mineru(source, page_count=3, max_pages=2) as parts:
        assert [(part.page_start, part.page_end) for part in parts] == [(1, 2), (3, 3)]
        assert [len(PdfReader(str(part.path)).pages) for part in parts] == [2, 1]
        documents = [Document(text="page", metadata={"page": 1})]
        restore_source_pages(documents, parts[1])
        assert documents[0].metadata["page"] == 3

    assert all(not part.path.exists() for part in parts)


def test_legacy_ppt_is_converted_before_mineru(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "lesson.ppt"
    source.write_bytes(b"legacy presentation")

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        output_dir = Path(command[command.index("--outdir") + 1])
        _write_pdf(output_dir / "lesson.pdf", 2)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with prepare_for_mineru(source, page_count=None) as parts:
        assert len(parts) == 1
        assert parts[0].page_range == "1-2"
        assert parts[0].path.suffix == ".pdf"


class CorpusStatusRecords:
    def __init__(self) -> None:
        self.statuses: list[tuple[str, str, dict[str, Any]]] = []

    def update_status(self, document_id: str, status: str, **values: Any) -> None:
        self.statuses.append((document_id, status, values))


def test_object_backed_markdown_is_materialized_for_conversion(tmp_path: Path) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    store = ManagedObjectStore(LocalObjectStore(settings.object_store_local_root))
    stored = store.put_bytes(
        "corpus-sources/subject/other/source.md",
        "# Source\n\nEvidence.",
        metadata=ObjectMetadata(
            purpose="corpus-source",
            owner_type="source_document",
            owner_id="document-1",
        ),
    )
    records = CorpusStatusRecords()
    ingestor = CorpusIngestor(records, settings, subject, store)  # type: ignore[arg-type]

    converted_path, converted = ingestor.convert(
        {
            "id": "document-1",
            "subject_code": subject.subject_code,
            "path": "/unavailable/read-only-corpus/source.md",
            "object_key": stored.key,
            "source_type": "other",
            "checksum": stored.checksum_sha256,
        }
    )

    assert converted is True
    assert "# Source" in Path(converted_path).read_text(encoding="utf-8")
    assert records.statuses[-1][1] == "converted"
    assert records.statuses[-1][2]["converted_source_checksum"] == stored.checksum_sha256
    assert records.statuses[-1][2]["markdown_path"] == (
        f"corpus/md/document-1/{stored.checksum_sha256}.md"
    )


def test_same_document_cache_is_reused_only_for_its_source_checksum(tmp_path: Path) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    source = tmp_path / "source.md"
    source.write_text("# Version 1", encoding="utf-8")
    records = CorpusStatusRecords()
    ingestor = CorpusIngestor(records, settings, subject)
    base_row = {
        "id": "stable-document-id",
        "subject_code": subject.subject_code,
        "path": str(source),
        "source_type": "mark_scheme",
    }

    v1_path, created = ingestor.convert({**base_row, "checksum": "source-checksum-v1"})
    assert created is True
    assert Path(v1_path).relative_to(settings.markdown_dir) == Path(
        "stable-document-id/source-checksum-v1.md"
    )
    assert 'source_checksum: "source-checksum-v1"' in Path(v1_path).read_text(encoding="utf-8")

    source.write_text("# Version 2", encoding="utf-8")
    v2_path, created = ingestor.convert(
        {
            **base_row,
            "checksum": "source-checksum-v2",
            "converted_source_checksum": "source-checksum-v1",
            "markdown_path": records.statuses[-1][2]["markdown_path"],
        }
    )
    assert created is True
    assert v2_path != v1_path
    assert Path(v2_path).relative_to(settings.markdown_dir) == Path(
        "stable-document-id/source-checksum-v2.md"
    )
    converted = Path(v2_path).read_text(encoding="utf-8")
    assert "# Version 2" in converted
    assert 'source_checksum: "source-checksum-v2"' in converted
    assert "# Version 1" in Path(v1_path).read_text(encoding="utf-8")
    assert "# Version 2" not in Path(v1_path).read_text(encoding="utf-8")
    assert records.statuses[-1][2]["converted_source_checksum"] == "source-checksum-v2"
    assert records.statuses[-1][2]["markdown_path"] == ("stable-document-id/source-checksum-v2.md")

    reused_path, created = ingestor.convert(
        {
            **base_row,
            "checksum": "source-checksum-v2",
            "converted_source_checksum": "source-checksum-v2",
            "markdown_path": records.statuses[-1][2]["markdown_path"],
        }
    )
    assert created is False
    assert reused_path == v2_path

    source.write_text("# Untrusted rewrite under the same checksum", encoding="utf-8")
    forced_path, created = ingestor.convert(
        {
            **base_row,
            "checksum": "source-checksum-v2",
            "converted_source_checksum": "source-checksum-v2",
            "markdown_path": records.statuses[-1][2]["markdown_path"],
        },
        force=True,
    )
    assert created is False
    assert forced_path == v2_path
    assert "Untrusted rewrite" not in Path(v2_path).read_text(encoding="utf-8")


def test_unchanged_legacy_cache_path_is_preserved(tmp_path: Path) -> None:
    settings = Settings(
        subject_pack="oxfordaqa-economics-9640",
        object_store_local_root=tmp_path / "objects",
    )
    subject = subject_context(settings)
    settings.markdown_dir.mkdir(parents=True)
    legacy = settings.markdown_dir / "legacy-document.md"
    legacy.write_text("# Legacy conversion", encoding="utf-8")
    records = CorpusStatusRecords()
    ingestor = CorpusIngestor(records, settings, subject)

    resolved, created = ingestor.convert(
        {
            "id": "legacy-document",
            "subject_code": subject.subject_code,
            "path": str(tmp_path / "source.pdf"),
            "source_type": "mark_scheme",
            "checksum": "legacy-source-checksum",
            "converted_source_checksum": "legacy-source-checksum",
            "markdown_path": "legacy-document.md",
        }
    )

    assert created is False
    assert Path(resolved) == legacy
    assert records.statuses[-1][2]["markdown_path"] == "legacy-document.md"


class DiscoverySession:
    def __init__(self) -> None:
        self.document = SimpleNamespace(
            id="stable-document-id",
            path="/corpus/mark-scheme.pdf",
            filename="mark-scheme.pdf",
            checksum="source-checksum-v1",
            status="converted",
            markdown_path="stable-document-id.md",
            converted_source_checksum="source-checksum-v1",
            error=None,
        )
        self.location = SimpleNamespace(
            document_id="stable-document-id",
            relative_path="mark-scheme.pdf",
            present=True,
            last_seen_at=None,
        )

    def __enter__(self) -> "DiscoverySession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> "DiscoverySession":
        return self

    def scalar(self, _statement: object) -> str:
        return "stable-document-id"

    def get(self, model: object, _key: str) -> object:
        if model is SourceDocumentModel:
            return self.document
        if model is SourceDocumentLocationModel:
            return self.location
        raise AssertionError(f"Unexpected model: {model}")

    def add(self, _row: object) -> None:
        raise AssertionError("Replacement must update the stable source document")

    def execute(self, _statement: object) -> None:
        return None


def test_source_discovery_requires_explicit_subject_metadata() -> None:
    repository = CorpusRepository(DiscoverySession())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="explicit subject_code"):
        repository.register_discovery(
            {
                "path": "/corpus/source.pdf",
                "filename": "source.pdf",
                "source_type": "other",
                "checksum": "checksum",
            },
            relative_path="source.pdf",
            size_bytes=1,
            current_paths={"/corpus/source.pdf"},
        )


def test_same_path_source_replacement_preserves_id_and_invalidates_conversion() -> None:
    sessions = DiscoverySession()
    repository = CorpusRepository(sessions)  # type: ignore[arg-type]

    document_id = repository.register_discovery(
        {
            "subject_code": "9999",
            "path": "/corpus/mark-scheme.pdf",
            "filename": "mark-scheme.pdf",
            "source_type": "mark_scheme",
            "checksum": "source-checksum-v2",
        },
        relative_path="mark-scheme.pdf",
        size_bytes=42,
        current_paths={"/corpus/mark-scheme.pdf"},
    )

    assert document_id == "stable-document-id"
    assert sessions.document.checksum == "source-checksum-v2"
    assert sessions.document.status == "discovered"
    assert sessions.document.markdown_path is None
    assert sessions.document.converted_source_checksum == "source-checksum-v1"


def test_rediscovered_archived_source_becomes_active_without_losing_conversion_provenance() -> None:
    sessions = DiscoverySession()
    sessions.document.status = "deleted"
    sessions.document.error = "archived"
    sessions.location.present = False
    repository = CorpusRepository(sessions)  # type: ignore[arg-type]

    document_id = repository.register_discovery(
        {
            "subject_code": "9999",
            "path": "/corpus/mark-scheme.pdf",
            "filename": "mark-scheme.pdf",
            "source_type": "mark_scheme",
            "checksum": "source-checksum-v1",
        },
        relative_path="mark-scheme.pdf",
        size_bytes=42,
        current_paths={"/corpus/mark-scheme.pdf"},
    )

    assert document_id == "stable-document-id"
    assert sessions.document.status == "discovered"
    assert sessions.document.error is None
    assert sessions.document.markdown_path == "stable-document-id.md"
    assert sessions.document.converted_source_checksum == "source-checksum-v1"
    assert sessions.location.present is True
