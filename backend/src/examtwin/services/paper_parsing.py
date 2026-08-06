from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from examtwin.answering_agent.contracts import (
    QuestionSpec,
)
from examtwin.config import Settings
from examtwin.services.corpus_ingestion import render_documents
from examtwin.services.paper_vision import parse_physical_page_markdown
from llama_index.readers.mineru import MinerUReader

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_SUFFIXES = {".md", ".markdown", ".pdf"}
_VISUAL_CONTEXT = re.compile(
    r"(?:!\[|<img\b|<svg\b|"
    r"\b(?:figure|diagram|graph|chart|histogram|scatter\s+plot|box\s+plot|"
    r"tree\s+diagram|coordinate\s+axes|shaded\s+region)\b|"
    r"\b(?:draw|sketch|shade)\b)",
    re.IGNORECASE,
)


def question_requires_visual_context(markdown: str) -> bool:
    """Conservative fallback when an older split result lacks the visual flag."""

    return bool(_VISUAL_CONTEXT.search(markdown))


def question_spec_from_item(item: dict[str, Any]) -> QuestionSpec:
    raw_subparts = item.get("answer_requirements", [])
    if raw_subparts is None:
        raw_subparts = []
    if not isinstance(raw_subparts, list):
        raise ValueError("answer_requirements must be an array")
    raw_total = item.get("total_marks")
    spec = QuestionSpec.model_validate({"subparts": raw_subparts, "total_marks": raw_total})
    if spec.total_marks is None:
        marks = [part.marks for part in spec.subparts]
        if marks and all(mark is not None for mark in marks):
            spec = spec.model_copy(update={"total_marks": sum(mark for mark in marks if mark)})
    return spec


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower())
        if token
        not in {
            "and",
            "answer",
            "find",
            "from",
            "given",
            "marks",
            "question",
            "show",
            "that",
            "the",
            "this",
            "using",
            "where",
            "with",
        }
    }


def _question_number_value(value: Any) -> str:
    match = re.match(r"\s*0*(\d+)", str(value))
    return str(int(match.group(1))) if match else ""


def _question_anchor_matches(number: str, body: str) -> list[re.Match[str]]:
    escaped = re.escape(number)
    pattern = re.compile(
        rf"(?im)^[ \t]*(?:[#>*-]+\s*)?(?:question\s+)?0*{escaped}"
        r"(?=[ \t]*(?:$|[.:\)]|\([a-zivx]+\)|[A-Za-z]))"
    )
    return list(pattern.finditer(body))


def _meaningful_page_text(text: str) -> bool:
    without_comments = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    return bool(re.search(r"[A-Za-z0-9]|[=+\-×÷∫√]", without_comments))


_END_OF_QUESTIONS_RE = re.compile(r"\bEND\s+OF\s+QUESTIONS\b", re.IGNORECASE)
_ADMINISTRATIVE_PAGE_RE = re.compile(
    r"(?:"
    r"TURN\s+OVER\s+FOR\s+THE\s+NEXT\s+QUESTION"
    r"|DO\s+NOT\s+WRITE\s+ON\s+THIS\s+PAGE"
    r"|THERE\s+ARE\s+NO\s+QUESTIONS?\s+PRINTED\s+ON\s+THIS\s+PAGE"
    r"|ADDITIONAL\s+PAGE(?:,\s*IF\s+REQUIRED)?"
    r"|WRITE\s+THE\s+QUESTION\s+NUMBERS?\s+IN\s+THE\s+LEFT[- ]HAND\s+MARGIN"
    r")",
    re.IGNORECASE,
)
_EXTRACT_REFERENCE_RE = re.compile(r"\bextract\s+([A-Z])\b", re.IGNORECASE)


def _referenced_extract_start_page(
    question: str,
    pages: list[tuple[int, str]],
    question_page_index: int,
) -> int | None:
    labels = {label.upper() for label in _EXTRACT_REFERENCE_RE.findall(question)}
    if not labels:
        return None
    headings = tuple(
        re.compile(rf"(?im)^[ \t]*(?:[#>*-]+\s*)?extract\s+{re.escape(label)}\b")
        for label in labels
    )
    return next(
        (
            page_index
            for page_index, (_page_number, body) in enumerate(pages[: question_page_index + 1])
            if any(heading.search(body) for heading in headings)
        ),
        None,
    )


def _question_page_overlap(question: str, body: str) -> float:
    question_tokens = _tokens(question)
    if not question_tokens:
        return 0.0
    return len(question_tokens & _tokens(body)) / len(question_tokens)


def _question_source_page_is_relevant(question: str, body: str) -> bool:
    if not _meaningful_page_text(body):
        return False
    if not _ADMINISTRATIVE_PAGE_RE.search(body):
        return True
    # Genuine question pages may also contain examiner boilerplate. Reject an
    # administrative-looking page only when it has no material question overlap.
    return _question_page_overlap(question, body) >= 0.2


class QuestionSourcePageResolutionError(ValueError):
    """Raised when extracted question order cannot be reconciled with trusted page markers."""

    def __init__(self, unresolved_numbers: list[str]) -> None:
        self.unresolved_numbers = tuple(unresolved_numbers)
        super().__init__("无法从物理页标记确定题目来源页：" + ", ".join(self.unresolved_numbers))


def reconcile_question_source_pages(
    markdown: str,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace model page guesses with spans derived from immutable page markers."""

    pages = parse_physical_page_markdown(markdown)
    if not pages:
        return questions

    anchors: list[tuple[int, int] | None] = []
    previous: tuple[int, int] = (-1, -1)
    for item in questions:
        number = _question_number_value(item.get("number", ""))
        question = str(item.get("question_markdown", ""))
        candidates: list[tuple[float, int, int]] = []
        if number:
            for page_index, (_page_number, body) in enumerate(pages):
                for match in _question_anchor_matches(number, body):
                    coordinate = (page_index, match.start())
                    if coordinate > previous:
                        candidates.append(
                            (
                                _question_page_overlap(question, body[match.start() :]),
                                page_index,
                                match.start(),
                            )
                        )
        if candidates:
            _score, page_index, offset = min(
                candidates,
                key=lambda candidate: (
                    candidate[1],
                    candidate[2],
                    -candidate[0],
                ),
            )
            anchor = (page_index, offset)
        else:
            fallback: list[tuple[float, int]] = []
            for page_index, (_page_number, body) in enumerate(pages):
                if (page_index, 0) < previous:
                    continue
                score = _question_page_overlap(question, body)
                if score >= 0.2:
                    fallback.append((score, page_index))
            if fallback:
                _score, page_index = max(
                    fallback,
                    key=lambda candidate: (candidate[0], -candidate[1]),
                )
                anchor = (page_index, 0)
            else:
                anchor = None
        anchors.append(anchor)
        if anchor is not None:
            previous = anchor

    unresolved = [
        str(item.get("number", "?"))
        for item, anchor in zip(questions, anchors, strict=True)
        if anchor is None
    ]
    if unresolved:
        raise QuestionSourcePageResolutionError(unresolved)

    end_of_questions_page = next(
        (
            page_index
            for page_index, (_page_number, body) in enumerate(pages)
            if _END_OF_QUESTIONS_RE.search(body)
        ),
        len(pages) - 1,
    )
    reconciled: list[dict[str, Any]] = []
    for index, (item, anchor) in enumerate(zip(questions, anchors, strict=True)):
        assert anchor is not None
        start_page_index, _start_offset = anchor
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else None
        page_indexes: list[int]
        if next_anchor is None:
            page_indexes = list(
                range(
                    start_page_index,
                    max(start_page_index, end_of_questions_page) + 1,
                )
            )
        else:
            next_page_index, next_offset = next_anchor
            if next_page_index == start_page_index:
                page_indexes = [start_page_index]
            else:
                page_indexes = list(range(start_page_index, next_page_index))
                prefix = pages[next_page_index][1][:next_offset]
                if _meaningful_page_text(prefix):
                    page_indexes.append(next_page_index)
        extract_start_page = _referenced_extract_start_page(
            str(item.get("question_markdown", "")),
            pages,
            start_page_index,
        )
        if extract_start_page is not None:
            page_indexes = sorted(
                set(page_indexes) | set(range(extract_start_page, start_page_index + 1))
            )
        source_pages = [
            pages[page_index][0]
            for page_index in page_indexes
            if _question_source_page_is_relevant(
                str(item.get("question_markdown", "")),
                pages[page_index][1],
            )
        ]
        if not source_pages:
            source_pages = [pages[start_page_index][0]]
        repaired = dict(item)
        repaired["source_pages"] = source_pages
        reconciled.append(repaired)
    return reconciled


def mineru_reader(settings: Settings, *, timeout: int | None = None) -> MinerUReader:
    token = settings.mineru_token.get_secret_value() if settings.mineru_token else None
    return MinerUReader(
        mode=settings.mineru_mode,
        token=token,
        language=settings.mineru_language,
        ocr=True,
        formula=True,
        table=True,
        timeout=timeout or settings.paper_mineru_timeout,
    )


def upload_to_markdown(settings: Settings, filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("仅支持 Markdown（.md/.markdown）或 PDF 试卷")
    if not content:
        raise ValueError("上传的试卷为空")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("试卷文件超过 25 MB 限制")
    if suffix in {".md", ".markdown"}:
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("Markdown 必须使用 UTF-8 编码") from error

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        documents = mineru_reader(settings).load_data(
            temporary_path,
            extra_info={"source": filename, "source_type": "uploaded_question_paper"},
        )
        return render_documents(documents)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
