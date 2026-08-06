from __future__ import annotations

import re
from typing import Any, Protocol

from examtwin.contracts.knowledge import SourceContextResponse
from examtwin.platform.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path
from examtwin.platform.config import Settings

MAX_CONTEXT_CHARS = 100_000
PAGE_MARKER = re.compile(r"<!--\s*page(?::|\s)\s*(\d+)\s*-->", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6})\s+")


class SourceDocumentReader(Protocol):
    def get_converted(self, document_id: str) -> dict[str, Any] | None: ...


def _page_section(markdown: str, page: int) -> str | None:
    matches = list(PAGE_MARKER.finditer(markdown))
    for index, match in enumerate(matches):
        if int(match.group(1)) != page:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        return markdown[match.start() : end].strip()
    return None


def _question_section(markdown: str, question_number: str) -> str | None:
    match = re.match(r"\s*0*(\d+)", question_number)
    if match is None:
        return None
    normalized = str(int(match.group(1)))
    question_table = re.compile(
        r"<td>question</td>.*?</tr>\s*<tr><td(?:\s+[^>]*)?>0*(\d+)</td>",
        re.IGNORECASE,
    )
    heading = re.compile(
        rf"^#{{1,6}}\s+(?:question\s+)?0*{re.escape(normalized)}(?:\D|$)",
        re.IGNORECASE,
    )
    lines = markdown.splitlines()
    starts = []
    for index, line in enumerate(lines):
        table_match = question_table.search(line)
        if (table_match and str(int(table_match.group(1))) == normalized) or heading.search(
            line
        ) is not None:
            starts.append(index)
    if not starts:
        return None
    start = starts[0]
    maximum = re.compile(
        rf"\bmaximum\s+for\s+question\s+0*{re.escape(normalized)}\b",
        re.IGNORECASE,
    )
    any_question_row = question_table
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if maximum.search(line):
            end = index + 1
            break
        if "<td>question</td>" in line.lower():
            question_match = any_question_row.search(line)
            if question_match and str(int(question_match.group(1))) != normalized:
                end = index
                break
    return "\n".join(lines[start:end]).strip()


def _referenced_extract_sections(markdown: str, query: str) -> str | None:
    labels = tuple(dict.fromkeys(re.findall(r"\bEXTRACT\s+([A-Z])\b", query.upper())))
    if not labels:
        return None
    lines = markdown.splitlines()
    extract = re.compile(
        r"^\s*(?:#{1,6}\s*)?extract\s+([A-Z])\s*:",
        re.IGNORECASE,
    )
    sections: list[str] = []
    for label in labels:
        starts = [
            index
            for index, line in enumerate(lines)
            if (match := extract.match(line)) is not None and match.group(1).upper() == label
        ]
        if not starts:
            continue
        start = starts[-1]
        end = len(lines)
        for index in range(start + 1, len(lines)):
            match = extract.match(lines[index])
            if match is not None and match.group(1).upper() != label:
                end = index
                break
            if re.match(
                r"^\s*(?:#{1,6}\s*)?end\s+of\s+extracts\b",
                lines[index],
                re.IGNORECASE,
            ):
                end = index
                break
        sections.append("\n".join(lines[start:end]).strip())
    return "\n\n".join(sections) if sections else None


def _heading_section(markdown: str, query: str) -> str:
    lines = markdown.splitlines()
    terms = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", query.lower())
        if token not in {"and", "from", "that", "the", "this", "with"}
    }
    if not terms:
        return markdown.strip()
    best_index = 0
    best_score = -1
    for index, line in enumerate(lines):
        lowered = line.lower()
        score = sum(term in lowered for term in terms)
        if score > best_score:
            best_index = index
            best_score = score

    start = best_index
    level = 7
    while start >= 0:
        heading = HEADING.match(lines[start])
        if heading:
            level = len(heading.group(1))
            break
        start -= 1
    if start < 0:
        start = max(0, best_index - 20)

    end = len(lines)
    for index in range(start + 1, len(lines)):
        heading = HEADING.match(lines[index])
        if heading and len(heading.group(1)) <= level:
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def source_context(
    documents: SourceDocumentReader,
    settings: Settings,
    document_id: str,
    *,
    page: int | None = None,
    query: str = "",
    question_number: str | None = None,
) -> SourceContextResponse:
    row = documents.get_converted(document_id)
    if not row:
        raise LookupError("参考资料不存在或尚未转换")

    try:
        markdown_path = resolve_markdown_cache_path(
            settings,
            str(row["id"]),
            str(row["markdown_path"]),
        )
    except MarkdownCacheMissing as error:
        raise LookupError("参考资料原文缓存不存在") from error
    markdown = markdown_path.read_text(encoding="utf-8")
    content = _page_section(markdown, page) if page is not None else None
    if content is None and question_number:
        content = _question_section(markdown, question_number)
    if content is None:
        content = _referenced_extract_sections(markdown, query)
    if content is None:
        content = _heading_section(markdown, query)
    truncated = len(content) > MAX_CONTEXT_CHARS
    if truncated:
        content = content[:MAX_CONTEXT_CHARS].rstrip() + "\n\n> 原文过长，已显示此前 100000 字符。"
    return SourceContextResponse(
        document_id=row["id"],
        source=row["path"],
        page=page,
        content_markdown=content,
        truncated=truncated,
    )
