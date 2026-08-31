from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pypdf import PdfReader

from examtwin.knowledge.corpus_repository import CorpusRepository
from examtwin.subjects.public import DashboardRepository, SubjectPack

SUPPORTED_SUFFIXES = {".pdf", ".ppt", ".pptx", ".doc", ".docx", ".md"}

MONTH_MAP = {
    "jan": "JAN",
    "january": "JAN",
    "冬": "JAN",
    "may": "JUN",
    "jun": "JUN",
    "june": "JUN",
    "summer": "JUN",
    "夏": "JUN",
    "nov": "NOV",
    "november": "NOV",
    "autumn": "NOV",
}


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify_source(path: Path) -> str:
    text = str(path).lower().replace("_", " ")
    filename = re.sub(r"[-_]+", " ", path.name.lower())
    if path.suffix.lower() == ".md":
        return "markdown"
    if "specification" in filename or "考试大纲" in text:
        return "syllabus"
    if "章节分类练习" in text:
        return "topic_practice"
    if (
        re.search(r"(?:^|[^a-z])ms(?:[^a-z]|$)", filename)
        or "mark scheme" in filename
        or "markscheme" in filename
    ):
        return "mark_scheme"
    if "examiner" in filename or "report on exam" in filename or re.search(r"(^| )er ", filename):
        return "examiner_report"
    if "insert" in filename or re.search(r"(?:^|[-_ ])in(?:[-_ ]|$)", path.stem.lower()):
        return "insert"
    if re.search(r"(?:^|[^a-z])qp(?:[^a-z]|$)", filename) or "question paper" in filename:
        return "question_paper"
    if "历年真题" in text and "paper" in filename:
        return "question_paper"
    if "教材" in text or "student book" in filename:
        return "textbook"
    if "复习笔记" in text:
        return "revision_note"
    if path.suffix.lower() in {".ppt", ".pptx"}:
        return "slide"
    return "other"


def authority_tier(
    path: Path,
    source_type: str,
    subject_pack: SubjectPack,
) -> str:
    if source_type in subject_pack.board.official_source_types:
        return "official"
    if source_type == "textbook" and "赠送" not in str(path):
        return "licensed_core"
    return "supplementary"


def _parse_year(text: str) -> int | None:
    compact = re.search(r"20(1[7-9]|2[0-9])(?:0[156]|11)", text)
    if compact:
        return int(compact.group(0)[:4])
    four_digit = re.search(r"(?<!\d)(20(?:1[7-9]|2[0-9]))(?!\d)", text)
    if four_digit:
        return int(four_digit.group(1))
    two_digit = re.search(
        r"(?:jan|january|may|jun|june|nov|november)[- ]?([12][7-9]|2[0-9])(?!\d)",
        text,
    )
    if two_digit:
        return 2000 + int(two_digit.group(1))
    return None


def _parse_session(text: str) -> str | None:
    compact = re.search(r"20(?:1[7-9]|2[0-9])(0[156]|11)", text)
    if compact:
        return {"01": "JAN", "05": "JUN", "06": "JUN", "11": "NOV"}[compact.group(1)]
    for token, session in MONTH_MAP.items():
        if token in text:
            return session
    return None


def parse_exam_identity(
    path: Path,
    source_type: str,
    subject_pack: SubjectPack,
) -> dict[str, Any]:
    text = str(path).lower()
    year = _parse_year(text)
    session = _parse_session(text)
    unit = subject_pack.parse_unit(text)
    filename_subject_code = subject_pack.board.subject_code_from_filename(path.name)
    foreign_subject = bool(
        filename_subject_code and not filename_subject_code.startswith(subject_pack.subject_code)
    )
    specimen = "样卷" in text or "specimen" in text
    exam_source = (
        source_type in {"question_paper", "mark_scheme", "examiner_report", "insert"}
        and not foreign_subject
        and not specimen
    )
    pair_key = None
    missing: list[str] = []
    if exam_source:
        if year and session and unit:
            pair_key = subject_pack.pair_key(year, session, unit)
        else:
            if year is None:
                missing.append("year")
            if session is None:
                missing.append("session")
            if unit is None:
                missing.append("unit")
    return {
        "exam_year": year,
        "exam_session": session,
        "unit_code": unit,
        "pair_key": pair_key,
        "identity_status": (
            "complete"
            if exam_source and not missing
            else "incomplete"
            if exam_source
            else "not_applicable"
        ),
        "identity_error": f"missing:{','.join(missing)}" if missing else None,
    }


def page_count(path: Path) -> int | None:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            return len(PdfReader(path).pages)
        if suffix == ".pptx":
            with zipfile.ZipFile(path) as archive:
                presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
            slide_id_tag = "{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"
            return sum(1 for element in presentation.iter() if element.tag == slide_id_tag)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return None
    return None


def scan_corpus(
    documents: CorpusRepository,
    root: Path,
    subject_pack: SubjectPack,
) -> dict[str, Any]:
    if not root.exists():
        raise FileNotFoundError(f"Corpus directory does not exist: {root}")
    counts: Counter[str] = Counter()
    identity_failures: Counter[str] = Counter()
    scanned = 0
    paths = sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in SUPPORTED_SUFFIXES
    )
    current_paths = {str(path.resolve()) for path in paths}
    for path in paths:
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        source_type = classify_source(path)
        relative = path.relative_to(root)
        digest = checksum(path)
        identity = parse_exam_identity(path, source_type, subject_pack)
        documents.register_discovery(
            {
                "path": str(path.resolve()),
                "filename": path.name,
                "source_type": source_type,
                "subject_id": subject_pack.id,
                "subject_code": subject_pack.subject_code,
                "authority_tier": authority_tier(path, source_type, subject_pack),
                "source_role": (
                    "assessment_only"
                    if source_type in subject_pack.board.official_source_types
                    else "excluded"
                ),
                "checksum": digest,
                "page_count": page_count(path),
                "metadata_json": {
                    "relative_path": str(relative),
                    "subject_code": subject_pack.subject_code,
                    "subject_pack": subject_pack.id,
                },
                **identity,
            },
            relative_path=str(relative),
            size_bytes=path.stat().st_size,
            current_paths=current_paths,
        )
        scanned += 1
        counts[source_type] += 1
        if identity["identity_status"] == "incomplete":
            identity_failures[str(identity["identity_error"])] += 1
    documents.finish_scan(subject_pack.subject_code, current_paths)
    incomplete = sum(identity_failures.values())
    return {
        "scanned": scanned,
        "by_type": dict(sorted(counts.items())),
        "exam_identity_incomplete": incomplete,
        "identity_failures": dict(sorted(identity_failures.items())),
        "strict_pairing_ready": incomplete == 0,
    }


def corpus_stats(
    repository: DashboardRepository,
    *,
    subject_code: str | None = None,
) -> dict[str, Any]:
    return repository.stats(subject_code=subject_code)
