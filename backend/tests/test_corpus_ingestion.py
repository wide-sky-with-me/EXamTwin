import subprocess
from pathlib import Path

from examtwin.services.source_preprocessing import prepare_for_mineru, restore_source_pages
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
