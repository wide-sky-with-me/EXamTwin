from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llama_index.readers.mineru import MinerUReader
from mineru import MinerU

from examtwin.assessment.answering_agent.contracts import (
    QuestionSpec,
)
from examtwin.assessment.paper_vision import parse_physical_page_markdown
from examtwin.knowledge.public import render_documents
from examtwin.platform.config import Settings

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_SUFFIXES = {".md", ".markdown", ".pdf"}
_VISUAL_CONTEXT = re.compile(
    r"(?:!\[|<img\b|<svg\b|"
    r"\b(?:figure|diagram|graph|chart|histogram|scatter\s+plot|box\s+plot|"
    r"tree\s+diagram|coordinate\s+axes|shaded\s+region)\b|"
    r"\b(?:draw|sketch|shade)\b)",
    re.IGNORECASE,
)
_UNRESOLVED_SOURCE_PLACEHOLDER = re.compile(
    r"(?:\\text\{\s*)?"
    r"\[[^\]\n]{0,120}\b(?:as\s+printed|omitted|missing|not\s+captured)\b"
    r"[^\]\n]{0,120}\]"
    r"(?:\s*\})?",
    re.IGNORECASE,
)
_TOP_LEVEL_QUESTION = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?"
    r"(?:question[ \t]+)?(?P<number>(?:\d[ \t]+\d{1,2}|0*\d{1,3}))(?:\*{1,2})?"
    r"(?![ \t]*:[ \t]*\d)"
    r"(?=(?:[ \t]*(?:$|[.:\)]|\([a-zivx]+\))|[ \t]+(?:\*{1,2})?[A-Za-z]))"
)
_STRUCTURE_SUBPART = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?"
    r"(?:0*\d{1,3}[ \t]*)?"
    r"(?P<label>(?:\.\d+|\([a-zivx]+\)(?:[ \t]*\([a-zivx]+\))*))"
    r"(?:\*{1,2})?(?=[ \t.:]|$)"
)
_PRINTED_MARK = re.compile(
    r"\\?[\[(][ \t]*(\d+)(?:[ \t]+|\\text\{[ \t]*)"
    r"marks?[ \t]*\}?\\?[\])]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QuestionSourceStructure:
    number: str
    question_markdown: str
    source_pages: tuple[int, ...]
    subpart_labels: tuple[str, ...]
    marks: tuple[int, ...]
    requires_visual_context: bool
    source_digest: str


@dataclass(frozen=True)
class ExtractedPaperImage:
    name: str
    path: str
    content: bytes
    page_index: int | None = None


@dataclass(frozen=True)
class ParsedPaperChunk:
    markdown: str
    images: tuple[ExtractedPaperImage, ...] = ()


class QuestionSourceStructureError(ValueError):
    """Raised when a split question cannot be proven complete against its trusted source."""


def question_has_unresolved_source_placeholder(markdown: str) -> bool:
    """Return whether extraction left an instruction in place of printed source content."""

    return bool(_UNRESOLVED_SOURCE_PLACEHOLDER.search(markdown))


def question_requires_visual_context(markdown: str) -> bool:
    """Require source-page review for spatial content or unresolved printed content."""

    return bool(
        _VISUAL_CONTEXT.search(markdown) or question_has_unresolved_source_placeholder(markdown)
    )


def _canonical_question_number(value: object) -> str:
    match = re.fullmatch(r"0*(\d+)", re.sub(r"\s+", "", str(value)))
    return str(int(match.group(1))) if match else ""


def _normalized_structure_label(value: object) -> str:
    normalized = re.sub(r"\s+", "", str(value)).lower()
    return re.sub(r"^\d+(?=[.(])", "", normalized)


def _simple_subpart_ordinals(labels: tuple[str, ...]) -> tuple[int, ...] | None:
    ordinals: list[int] = []
    for label in labels:
        decimal = re.fullmatch(r"\.(\d+)", label)
        if decimal:
            ordinals.append(int(decimal.group(1)))
            continue
        alpha = re.fullmatch(r"\(([a-z])\)", label)
        if alpha:
            ordinals.append(ord(alpha.group(1)) - ord("a") + 1)
            continue
        return None
    return tuple(ordinals)


def question_source_structures(markdown: str) -> list[QuestionSourceStructure]:
    """Derive the question structure once from visually reviewed source Markdown."""

    physical_pages = parse_physical_page_markdown(markdown)
    pages = physical_pages or [(1, markdown)]
    combined_parts: list[str] = []
    page_spans: list[tuple[int, int, int]] = []
    cursor = 0
    for page_number, body in pages:
        body = body.replace("\\n\\n", "\n\n")
        if combined_parts:
            combined_parts.append("\n\n")
            cursor += 2
        start = cursor
        combined_parts.append(body)
        cursor += len(body)
        page_spans.append((page_number, start, cursor))
    combined = "".join(combined_parts)
    matches = list(_TOP_LEVEL_QUESTION.finditer(combined))
    if not matches:
        return []

    anchors: list[tuple[str, re.Match[str]]] = []
    seen: set[str] = set()
    for match in matches:
        number = _canonical_question_number(match.group("number"))
        if not number:
            continue
        if anchors and anchors[-1][0] == number:
            continue
        if number in seen:
            raise QuestionSourceStructureError(f"主源题号不连续重复：{number}")
        seen.add(number)
        anchors.append((number, match))

    source_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    structures: list[QuestionSourceStructure] = []
    for index, (number, match) in enumerate(anchors):
        span_start = match.start()
        span_end = anchors[index + 1][1].start() if index + 1 < len(anchors) else len(combined)
        raw_question = combined[match.end() : span_end]
        end_marker = _END_OF_QUESTIONS_RE.search(raw_question)
        if end_marker:
            span_end = match.end() + end_marker.start()
            raw_question = raw_question[: end_marker.start()]
        question = raw_question.lstrip(" \t.:)").strip()
        if not question:
            raise QuestionSourceStructureError(f"主源第 {number} 题内容为空")
        source_pages = tuple(
            page_number
            for page_number, page_start, page_end in page_spans
            if span_start < page_end
            and span_end > page_start
            and _meaningful_page_text(
                combined[max(span_start, page_start) : min(span_end, page_end)]
            )
        )
        source_question = combined[span_start:span_end]
        all_labels = tuple(
            dict.fromkeys(
                _normalized_structure_label(label)
                for label in _STRUCTURE_SUBPART.findall(source_question)
            )
        )
        labels = tuple(
            label
            for label in all_labels
            if not any(
                candidate != label and candidate.startswith(label) for candidate in all_labels
            )
        )
        marks = tuple(int(value) for value in _PRINTED_MARK.findall(question))
        structures.append(
            QuestionSourceStructure(
                number=number,
                question_markdown=question,
                source_pages=source_pages,
                subpart_labels=labels,
                marks=marks,
                requires_visual_context=question_requires_visual_context(question),
                source_digest=source_digest,
            )
        )
    return structures


def validate_question_source_structure(
    markdown: str,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fail closed unless split output preserves the trusted page structure exactly."""

    physical_pages = parse_physical_page_markdown(markdown)
    if not physical_pages:
        source_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        normalized: list[dict[str, Any]] = []
        for item in questions:
            question = dict(item)
            question["requires_visual_context"] = question_requires_visual_context(
                str(question.get("question_markdown", ""))
            )
            question["source_kind"] = "primary"
            question["source_digest"] = source_digest
            normalized.append(question)
        return normalized

    structures = question_source_structures(markdown)
    if not structures:
        raise QuestionSourceStructureError("视觉复核主源没有可核对的顶层题号")
    actual_numbers = [_canonical_question_number(item.get("number", "")) for item in questions]
    expected_numbers = [structure.number for structure in structures]
    if actual_numbers != expected_numbers:
        raise QuestionSourceStructureError(
            f"分题题号与主源不一致：expected={expected_numbers}, actual={actual_numbers}"
        )

    validated: list[dict[str, Any]] = []
    for item, structure in zip(questions, structures, strict=True):
        spec = question_spec_from_item(item)
        if not spec.subparts and not structure.subpart_labels and len(structure.marks) == 1:
            spec = QuestionSpec.model_validate(
                {
                    "subparts": [{"label": "whole", "marks": structure.marks[0]}],
                    "total_marks": structure.marks[0],
                }
            )
        actual_labels = tuple(_normalized_structure_label(part.label) for part in spec.subparts)
        expected_labels = (
            structure.subpart_labels
            if structure.subpart_labels
            else ("whole",)
            if structure.marks
            else actual_labels
        )
        actual_ordinals = _simple_subpart_ordinals(actual_labels)
        expected_ordinals = _simple_subpart_ordinals(expected_labels)
        labels_match = actual_labels == expected_labels or (
            actual_ordinals is not None
            and expected_ordinals is not None
            and actual_ordinals == expected_ordinals
        )
        if not labels_match:
            raise QuestionSourceStructureError(
                f"第 {structure.number} 题子问结构与主源不一致："
                f"expected={expected_labels}, actual={actual_labels}"
            )
        actual_marks = tuple(part.marks for part in spec.subparts)
        if structure.marks and (
            any(mark is None for mark in actual_marks)
            or tuple(int(mark) for mark in actual_marks if mark is not None) != structure.marks
        ):
            raise QuestionSourceStructureError(
                f"第 {structure.number} 题分值结构与主源不一致："
                f"expected={structure.marks}, actual={actual_marks}"
            )
        if structure.marks and spec.total_marks != sum(structure.marks):
            raise QuestionSourceStructureError(
                f"第 {structure.number} 题总分与主源不一致："
                f"expected={sum(structure.marks)}, actual={spec.total_marks}"
            )
        validated_item = dict(item)
        validated_item["question_markdown"] = structure.question_markdown
        validated_item["source_pages"] = list(structure.source_pages)
        validated_item["requires_visual_context"] = structure.requires_visual_context
        validated_item["source_kind"] = "primary"
        validated_item["answer_requirements"] = [
            {**part.model_dump(mode="json"), "label": label}
            for part, label in zip(spec.subparts, expected_labels, strict=True)
        ]
        validated_item["total_marks"] = spec.total_marks
        validated_item["source_digest"] = structure.source_digest
        validated.append(validated_item)
    return validated


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


def extract_paper_chunk(
    settings: Settings,
    source: Path,
    *,
    timeout: int | None = None,
) -> ParsedPaperChunk:
    """Extract a PDF chunk while retaining MinerU's position-linked image assets."""

    token = settings.mineru_token.get_secret_value() if settings.mineru_token else None
    with MinerU(token=token) as client:
        client.set_source("examtwin-paper")
        if settings.mineru_mode == "flash":
            result = client.flash_extract(
                str(source),
                language=settings.mineru_language,
                is_ocr=True,
                enable_formula=True,
                enable_table=True,
                timeout=timeout or settings.paper_mineru_timeout,
            )
        else:
            result = client.extract(
                str(source),
                language=settings.mineru_language,
                ocr=True,
                formula=True,
                table=True,
                timeout=timeout or settings.paper_mineru_timeout,
            )
    if result.state != "done":
        raise ValueError(
            f"MinerU extraction failed: source={source}, state={result.state}, error={result.error}"
        )
    markdown = str(result.markdown or "")
    if not markdown.strip():
        raise ValueError("MinerU extraction returned empty Markdown")
    image_pages: dict[str, int] = {}
    content_list = getattr(result, "content_list", None)
    if isinstance(content_list, list):
        for item in content_list:
            if not isinstance(item, dict):
                continue
            image_path = str(item.get("img_path") or "").replace("\\", "/").lstrip("./")
            page_index = item.get("page_idx")
            if (
                image_path
                and isinstance(page_index, int)
                and not isinstance(page_index, bool)
                and page_index >= 0
            ):
                image_pages[image_path] = page_index
    images = tuple(
        ExtractedPaperImage(
            name=str(image.name),
            path=str(image.path),
            content=bytes(image.data),
            page_index=image_pages.get(str(image.path).replace("\\", "/").lstrip("./")),
        )
        for image in result.images
        if image.data
    )
    return ParsedPaperChunk(markdown=markdown, images=images)


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
