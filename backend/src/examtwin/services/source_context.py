from __future__ import annotations

import re
from typing import Any, Protocol

from examtwin.config import Settings
from examtwin.schemas.knowledge import SourceContextResponse
from examtwin.services.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path

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
