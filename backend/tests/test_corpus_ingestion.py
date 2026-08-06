import subprocess
from pathlib import Path
from typing import Any

from examtwin.knowledge.corpus_ingestion import CorpusIngestor
from examtwin.knowledge.source_preprocessing import prepare_for_mineru, restore_source_pages
from examtwin.platform.config import Settings
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
        }
    )

    assert converted is True
    assert "# Source" in Path(converted_path).read_text(encoding="utf-8")
    assert records.statuses[-1][1] == "converted"
