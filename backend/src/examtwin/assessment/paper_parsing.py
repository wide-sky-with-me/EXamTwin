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
    r"\b(?:figures?|diagrams?|graphs?|charts?|histograms?|scatter\s+plots?|"
    r"box\s+plots?|tree\s+diagrams?)\b"
    r"(?:[ \t]+\d+|[ \t]+(?:above|below)|.{0,30}\b(?:shows?|shown|provided)\b)|"
    r"\b(?:shown|illustrated|displayed)[ \t]+(?:in|on|by)[ \t]+(?:the[ \t]+)?"
    r"(?:figure|diagram|graph|chart)\b|"
    r"\b(?:coordinate\s+axes|shaded\s+region)\b)",
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
    r"(?:(?:\d[ \t]+\d{1,2}|0*\d{1,3})[ \t]*)?"
    r"(?P<label>(?:\.[ \t]*\d+|\([a-zivx]+\)(?:[ \t]*\([a-zivx]+\))*))"
    r"(?:\*{1,2})?(?=[^\S\r\n]|[.:]|$)"
)
_FULL_DECIMAL_SUBPART = re.compile(
    r"(?im)^(?P<prefix>[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?)"
    r"(?P<number>0*\d+)(?P<label>(?:\.\d+){1,2})(?P<suffix>(?:\*{1,2})?)"
    r"(?=[^\S\r\n]|[.:]|$)"
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
    page_markdown: tuple[str, ...] = ()


_MINERU_AUXILIARY_BLOCK_TYPES = {
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
}
_MINERU_SUPPORTED_BLOCK_TYPES = {
    "text",
    "title",
    "equation",
    "image",
    "chart",
    "table",
    "code",
    "list",
    *_MINERU_AUXILIARY_BLOCK_TYPES,
}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _mineru_content_block_markdown(item: dict[str, Any]) -> str:
    block_type = str(item.get("type") or "").strip().lower()
    if block_type in _MINERU_AUXILIARY_BLOCK_TYPES:
        return ""
    if block_type not in _MINERU_SUPPORTED_BLOCK_TYPES:
        raise ValueError(f"不支持的 MinerU 内容块类型：{block_type or 'unknown'}")

    if block_type in {"text", "title"}:
        text = str(item.get("text") or "").strip()
        if not text:
            return ""
        raw_level = item.get("text_level")
        level = raw_level if isinstance(raw_level, int) and not isinstance(raw_level, bool) else 0
        if block_type == "title" and level < 1:
            level = 1
        return f"{'#' * min(6, level)} {text}" if level > 0 else text

    if block_type == "equation":
        return str(item.get("text") or "").strip()

    if block_type in {"image", "chart"}:
        caption = _string_list(item.get(f"{block_type}_caption"))
        footnote = _string_list(item.get(f"{block_type}_footnote"))
        image_path = str(item.get("img_path") or "").strip()
        parts = [*caption]
        if image_path:
            alt = " ".join(caption) or ("Chart" if block_type == "chart" else "Image")
            parts.append(f"![{alt}]({image_path})")
        content = str(item.get("content") or "").strip()
        if content:
            parts.append(content)
        parts.extend(footnote)
        return "\n\n".join(parts)

    if block_type == "table":
        parts = [
            *_string_list(item.get("table_caption")),
            str(item.get("table_body") or "").strip(),
            *_string_list(item.get("table_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)

    if block_type == "list":
        return "\n".join(_string_list(item.get("list_items")))

    caption = _string_list(item.get("code_caption"))
    footnote = _string_list(item.get("code_footnote"))
    body = str(item.get("code_body") or "").strip()
    parts = [*caption]
    if body:
        parts.append(f"```\n{body}\n```")
    parts.extend(footnote)
    return "\n\n".join(parts)


def _mineru_page_markdown(content_list: object) -> tuple[str, ...]:
    """Render MinerU's page-indexed content blocks without losing page provenance."""

    if not isinstance(content_list, list) or not content_list:
        return ()
    pages: dict[int, list[str]] = {}
    for raw_item in content_list:
        if not isinstance(raw_item, dict):
            return ()
        page_index = raw_item.get("page_idx")
        if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0:
            return ()
        try:
            rendered = _mineru_content_block_markdown(raw_item)
        except ValueError:
            # A provider schema change must fail back to the original whole-chunk
            # Markdown instead of silently dropping an unknown content block.
            return ()
        pages.setdefault(page_index, [])
        if rendered:
            pages[page_index].append(rendered)
    if not pages:
        return ()
    return tuple(
        "\n\n".join(pages.get(page_index, ())).strip() for page_index in range(max(pages) + 1)
    )


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
    normalized = re.sub(r"\s+", "", str(value)).lower().strip("#*_")
    wrapped_decimal = re.fullmatch(r"\(0*\d+\.(\d+)\)", normalized)
    if wrapped_decimal:
        return f".{int(wrapped_decimal.group(1))}"
    return re.sub(r"^\d+(?=[.(])", "", normalized)


def _collapse_redundant_decimal_labels(labels: tuple[str, ...]) -> tuple[str, ...]:
    nested_count = 0
    nested_parent = ""
    collapsed: list[str] = []
    for label in labels:
        nested = re.fullmatch(r"\.(\d+)\.(\d+)", label)
        if nested:
            if len(collapsed) != nested_count:
                return labels
            parent, child = nested.groups()
            if nested_parent and parent != nested_parent:
                return labels
            nested_parent = parent
            nested_count += 1
            if int(child) != nested_count:
                return labels
            collapsed.append(f".{int(child)}")
            continue
        simple = re.fullmatch(r"\.(\d+)", label)
        if not simple or not nested_count or int(simple.group(1)) != len(collapsed) + 1:
            return labels
        collapsed.append(f".{int(simple.group(1))}")
    return tuple(collapsed) if 1 < nested_count < len(labels) else labels


def _repair_redundant_decimal_headings(markdown: str, question_number: str) -> str:
    matches = [
        match
        for match in _FULL_DECIMAL_SUBPART.finditer(markdown)
        if _canonical_question_number(match.group("number")) == question_number
    ]
    labels = tuple(match.group("label") for match in matches)
    collapsed = _collapse_redundant_decimal_labels(labels)
    if collapsed == labels:
        return markdown
    replacements = {match.start(): label for match, label in zip(matches, collapsed, strict=True)}

    def replace(match: re.Match[str]) -> str:
        label = replacements.get(match.start())
        if label is None:
            return match.group(0)
        return f"{match.group('prefix')}{question_number}{label}{match.group('suffix')}"

    return _FULL_DECIMAL_SUBPART.sub(replace, markdown)


def _normalize_decimal_subpart_headings(markdown: str, question_number: str) -> str:
    """Normalize OCR-spaced decimal labels without changing question wording."""

    def replace(match: re.Match[str]) -> str:
        label = _normalized_structure_label(match.group("label"))
        if not re.fullmatch(r"\.\d+", label):
            return match.group(0)
        raw = match.group(0)
        label_start = match.start("label") - match.start()
        label_end = match.end("label") - match.start()
        prefix = re.sub(
            r"(?:\d[ \t]+\d{1,2}|0*\d{1,3})[ \t]*$",
            "",
            raw[:label_start],
        )
        return f"{prefix}{question_number}{label}{raw[label_end:]}"

    return _STRUCTURE_SUBPART.sub(replace, markdown)


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

    def is_subpart_prefix(match: re.Match[str]) -> bool:
        return bool(
            re.match(
                r"[ \t]*(?:\.[ \t]*\d|\([a-zivx]+\))",
                combined[match.end() :],
                re.IGNORECASE,
            )
        )

    # ``_TOP_LEVEL_QUESTION`` intentionally accepts the numeric prefix of a
    # subpart so a page containing only ``16.1`` / ``16.2`` or ``3 (a)`` can
    # still establish its top-level question.  When an explicit heading exists,
    # however, those prefixes are subparts rather than duplicate top-level
    # anchors.
    explicit_numbers = {
        number
        for match in matches
        if (number := _canonical_question_number(match.group("number")))
        and not is_subpart_prefix(match)
    }
    matches = [
        match
        for match in matches
        if (number := _canonical_question_number(match.group("number"))) not in explicit_numbers
        or not is_subpart_prefix(match)
    ]

    number_counts: dict[str, int] = {}
    for match in matches:
        number = _canonical_question_number(match.group("number"))
        if number:
            number_counts[number] = number_counts.get(number, 0) + 1
    marked_duplicate_numbers = {
        number
        for index, match in enumerate(matches)
        if (number := _canonical_question_number(match.group("number")))
        and number_counts.get(number, 0) > 1
        and _PRINTED_MARK.search(
            combined[
                match.end() : matches[index + 1].start()
                if index + 1 < len(matches)
                else len(combined)
            ]
        )
    }
    matches = [
        match
        for index, match in enumerate(matches)
        if (number := _canonical_question_number(match.group("number")))
        not in marked_duplicate_numbers
        or _PRINTED_MARK.search(
            combined[
                match.end() : matches[index + 1].start()
                if index + 1 < len(matches)
                else len(combined)
            ]
        )
    ]

    numbered_matches = [
        (_canonical_question_number(match.group("number")), match)
        for match in matches
        if _canonical_question_number(match.group("number"))
    ]
    repaired_matches: list[tuple[str, re.Match[str]]] = []
    repaired_numbers: set[str] = set()
    for index, (number, match) in enumerate(numbered_matches):
        if number in repaired_numbers and repaired_matches and index + 1 < len(numbered_matches):
            previous_number = repaired_matches[-1][0]
            next_number, next_match = numbered_matches[index + 1]
            candidate = str(int(previous_number) + 1)
            current_span = combined[match.start() : next_match.start()]
            if (
                candidate not in repaired_numbers
                and candidate.endswith(number)
                and next_number == candidate
                and is_subpart_prefix(next_match)
                and _STRUCTURE_SUBPART.search(current_span)
                and _PRINTED_MARK.search(current_span)
            ):
                number = candidate
        repaired_matches.append((number, match))
        repaired_numbers.add(number)

    anchors: list[tuple[str, re.Match[str]]] = []
    seen: set[str] = set()
    for number, match in repaired_matches:
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
        subpart_anchor = is_subpart_prefix(match)
        content_start = match.start() if subpart_anchor else match.end()
        raw_question = combined[content_start:span_end]
        end_marker = _END_OF_QUESTIONS_RE.search(raw_question)
        if end_marker:
            span_end = content_start + end_marker.start()
            raw_question = raw_question[: end_marker.start()]
        next_section = _NEXT_SECTION_PREAMBLE_RE.search(raw_question)
        if next_section:
            span_end = content_start + next_section.start()
            raw_question = raw_question[: next_section.start()]
        for _page_number, page_start, page_end in page_spans:
            if page_start <= content_start or page_start >= span_end:
                continue
            page_body = combined[page_start:page_end]
            preceding_question = combined[content_start:page_start]
            has_current_question_subpart = bool(_PRINTED_MARK.search(page_body)) and any(
                _canonical_question_number(page_match.group("number")) == number
                and bool(
                    re.match(
                        r"[ \t]*(?:\.[ \t]*\d|\([a-zivx]+\))",
                        page_body[page_match.end() :],
                        re.IGNORECASE,
                    )
                )
                for page_match in _TOP_LEVEL_QUESTION.finditer(page_body)
            )
            if (
                _ADMINISTRATIVE_PAGE_RE.search(page_body)
                and not has_current_question_subpart
                and _question_page_overlap(
                    preceding_question,
                    page_body,
                )
                < 0.2
            ):
                span_end = page_start
                raw_question = combined[content_start:span_end]
                break
        question = raw_question.strip() if subpart_anchor else raw_question.lstrip(" \t.:)").strip()
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
        question = _repair_redundant_decimal_headings(question, number)
        source_question = _repair_redundant_decimal_headings(
            combined[span_start:span_end],
            number,
        )
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
                question_markdown=_normalize_decimal_subpart_headings(question, number),
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
        comparable_actual_labels = _collapse_redundant_decimal_labels(actual_labels)
        expected_labels = (
            structure.subpart_labels
            if structure.subpart_labels
            else ("whole",)
            if structure.marks
            else actual_labels
        )
        actual_ordinals = _simple_subpart_ordinals(comparable_actual_labels)
        expected_ordinals = _simple_subpart_ordinals(expected_labels)
        labels_match = comparable_actual_labels == expected_labels or (
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
_NEXT_SECTION_PREAMBLE_RE = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?Section[ \t]+[A-Z0-9]+\b"
)
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
    return ParsedPaperChunk(
        markdown=markdown,
        images=images,
        page_markdown=_mineru_page_markdown(content_list),
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
