from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from llama_index.core import Document
from pypdf import PdfReader, PdfWriter

MAX_MINERU_PAGES = 200
MAX_MINERU_UPLOAD_BYTES = 180 * 1024 * 1024
OFFICE_CONVERSION_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class PreparedSource:
    path: Path
    page_start: int | None = None
    page_end: int | None = None

    @property
    def page_range(self) -> str | None:
        if self.page_start is None or self.page_end is None:
            return None
        return f"{self.page_start}-{self.page_end}"

    @property
    def cache_suffix(self) -> str:
        page_range = self.page_range
        return f".pages-{page_range}.md" if page_range else ".md"


def _convert_presentation(source: Path, output_dir: Path) -> Path:
    profile = output_dir / "libreoffice-profile"
    command = [
        "soffice",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=OFFICE_CONVERSION_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Legacy PowerPoint conversion requires LibreOffice (soffice)") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Legacy PowerPoint conversion timed out") from error

    candidates = sorted(output_dir.glob("*.pdf"))
    if completed.returncode != 0 or len(candidates) != 1:
        detail = (completed.stderr or completed.stdout or "unknown LibreOffice error").strip()
        raise RuntimeError(f"Legacy PowerPoint conversion failed: {detail[:500]}")
    return candidates[0]


def _write_pdf_range(
    reader: PdfReader,
    output_dir: Path,
    start_index: int,
    end_index: int,
    *,
    max_bytes: int,
) -> list[PreparedSource]:
    target = output_dir / f"pages-{start_index + 1}-{end_index}.pdf"
    writer = PdfWriter()
    for index in range(start_index, end_index):
        writer.add_page(reader.pages[index])
    with target.open("wb") as handle:
        writer.write(handle)

    if target.stat().st_size <= max_bytes:
        return [PreparedSource(target, start_index + 1, end_index)]
    if end_index - start_index <= 1:
        raise ValueError(
            f"PDF page {start_index + 1} exceeds the MinerU upload limit after splitting"
        )

    target.unlink()
    midpoint = start_index + (end_index - start_index) // 2
    return [
        *_write_pdf_range(
            reader,
            output_dir,
            start_index,
            midpoint,
            max_bytes=max_bytes,
        ),
        *_write_pdf_range(
            reader,
            output_dir,
            midpoint,
            end_index,
            max_bytes=max_bytes,
        ),
    ]


def _split_pdf(
    source: Path,
    output_dir: Path,
    *,
    max_pages: int,
    max_bytes: int,
) -> tuple[PreparedSource, ...]:
    reader = PdfReader(str(source))
    page_count = len(reader.pages)
    if page_count == 0:
        raise ValueError("PDF contains no pages")
    parts: list[PreparedSource] = []
    for start in range(0, page_count, max_pages):
        parts.extend(
            _write_pdf_range(
                reader,
                output_dir,
                start,
                min(start + max_pages, page_count),
                max_bytes=max_bytes,
            )
        )
    return tuple(parts)


@contextmanager
def prepare_for_mineru(
    source: Path,
    *,
    page_count: int | None,
    max_pages: int = MAX_MINERU_PAGES,
    max_bytes: int = MAX_MINERU_UPLOAD_BYTES,
) -> Iterator[tuple[PreparedSource, ...]]:
    """Yield upload-safe sources while keeping all derived files temporary."""

    suffix = source.suffix.lower()
    needs_office_conversion = suffix == ".ppt"
    needs_pdf_split = suffix == ".pdf" and (
        (page_count or 0) > max_pages or source.stat().st_size > max_bytes
    )
    if not needs_office_conversion and not needs_pdf_split:
        yield (PreparedSource(source),)
        return

    with TemporaryDirectory(prefix="examtwin-corpus-") as temporary:
        output_dir = Path(temporary)
        prepared_source = (
            _convert_presentation(source, output_dir) if needs_office_conversion else source
        )
        prepared_page_count = len(PdfReader(str(prepared_source)).pages)
        if prepared_page_count <= max_pages and prepared_source.stat().st_size <= max_bytes:
            yield (
                PreparedSource(
                    prepared_source,
                    page_start=1,
                    page_end=prepared_page_count,
                ),
            )
            return
        yield _split_pdf(
            prepared_source,
            output_dir,
            max_pages=max_pages,
            max_bytes=max_bytes,
        )


def restore_source_pages(documents: Sequence[Document], part: PreparedSource) -> None:
    """Translate page metadata from a physical PDF part back to the source document."""

    if part.page_start is None or part.page_end is None:
        return
    for document in documents:
        page = document.metadata.get("page")
        try:
            relative_page = int(page) if page is not None else None
        except (TypeError, ValueError):
            relative_page = None
        if relative_page is not None:
            document.metadata["page"] = part.page_start + relative_page - 1
            continue

        pages = str(document.metadata.get("pages") or "")
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", pages)
        if match:
            document.metadata["pages"] = (
                f"{part.page_start + int(match.group(1)) - 1}-"
                f"{part.page_start + int(match.group(2)) - 1}"
            )
        else:
            document.metadata["pages"] = part.page_range
