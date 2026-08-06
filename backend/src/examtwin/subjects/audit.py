from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, cast

import fitz

from examtwin.subjects import SubjectPack


def audit_subject_pack_pdf(subject_pack: SubjectPack, pdf_path: Path) -> dict[str, Any]:
    """Check a SubjectPack's topic codes against its real official specification PDF."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"SubjectPack specification does not exist: {pdf_path}")
    discovered_pages: dict[str, int] = {}
    topic_code_pattern = re.compile(rf"^({subject_pack.topic_code_pattern})(?:\s|:|$)")
    subject_code_visible = False
    with fitz.open(pdf_path) as document:
        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            text = cast(str, page.get_text("text"))
            if subject_pack.subject_code in text:
                subject_code_visible = True
            for raw_line in text.splitlines():
                line = re.sub(r"\s+", " ", raw_line).strip()
                match = topic_code_pattern.match(line)
                if match:
                    code = match.group(1)
                    discovered_pages.setdefault(code, page_index + 1)
        page_count = document.page_count
    unmapped = sorted(
        code for code in discovered_pages if subject_pack.resolve_topic_unit(code) is None
    )
    mapped = len(discovered_pages) - len(unmapped)
    passed = (
        subject_code_visible
        and len(discovered_pages) >= subject_pack.minimum_topics
        and not unmapped
    )
    return {
        "subject_pack": subject_pack.id,
        "subject_code": subject_pack.subject_code,
        "specification": str(pdf_path),
        "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "pages": page_count,
        "minimum_topics": subject_pack.minimum_topics,
        "discovered_topics": len(discovered_pages),
        "mapped_topics": mapped,
        "unmapped_topic_codes": unmapped,
        "subject_code_visible": subject_code_visible,
        "passed": passed,
    }
