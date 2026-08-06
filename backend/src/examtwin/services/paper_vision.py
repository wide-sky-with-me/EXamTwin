from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pymupdf
from examtwin.config import Settings
from examtwin.services.model_json import parse_json_response

logger = logging.getLogger(__name__)

PHYSICAL_PAGE_MARKER_TEMPLATE = "<!-- examtwin:physical-page={page_number} -->"
_PHYSICAL_PAGE_MARKER_RE = re.compile(
    r"(?m)^[ \t]*<!--\s*examtwin:physical-page=(\d+)\s*-->[ \t]*$"
)
_LEGACY_PAGE_MARKER_RE = re.compile(
    r"(?m)^[ \t]*<!--\s*page\s+(\d+)\s*-->[ \t]*$",
    re.IGNORECASE,
)
_RETRYABLE_HTTP_STATUS_CODES = {408, 429}


def _is_retryable_failure(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        return status_code in _RETRYABLE_HTTP_STATUS_CODES or 500 <= status_code <= 599
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, (KeyError, TypeError, ValueError))


def _without_answer_scaffolding(markdown: str) -> str:
    kept: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "Answer":
            continue
        if stripped.lower().startswith("answer"):
            remainder = stripped[len("answer") :].strip()
            if remainder and all(char in "_ .:-" for char in remainder):
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def physical_page_marker(page_number: int) -> str:
    if page_number < 1:
        raise ValueError("物理页码必须从 1 开始")
    return PHYSICAL_PAGE_MARKER_TEMPLATE.format(page_number=page_number)


def format_physical_page_markdown(pages: list[tuple[int, str]]) -> str:
    """Serialize physical pages with markers that are never delegated to an LLM."""

    seen: set[int] = set()
    sections: list[str] = []
    for page_number, body in pages:
        if page_number < 1 or page_number in seen:
            raise ValueError("物理页码必须为不重复的正整数")
        seen.add(page_number)
        cleaned = _PHYSICAL_PAGE_MARKER_RE.sub("", str(body))
        cleaned = _LEGACY_PAGE_MARKER_RE.sub("", cleaned).strip()
        marker = physical_page_marker(page_number)
        sections.append(f"{marker}\n{cleaned}" if cleaned else marker)
    return "\n\n".join(sections)


def parse_physical_page_markdown(markdown: str) -> list[tuple[int, str]]:
    """Read canonical page sections, rejecting duplicates and out-of-order pages."""

    matches = list(_PHYSICAL_PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        return []
    pages: list[tuple[int, str]] = []
    previous = 0
    for index, match in enumerate(matches):
        page_number = int(match.group(1))
        if page_number <= previous:
            raise ValueError("物理页标记必须严格递增且不能重复")
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        pages.append((page_number, markdown[body_start:body_end].strip()))
        previous = page_number
    return pages


def validate_physical_page_markdown(
    markdown: str,
    page_start: int,
    page_end: int,
) -> list[tuple[int, str]]:
    pages = parse_physical_page_markdown(markdown)
    expected = list(range(page_start, page_end + 1))
    actual = [page_number for page_number, _body in pages]
    if actual != expected:
        raise ValueError(f"视觉复核物理页标记不完整：expected={expected}, actual={actual}")
    return pages


def _legacy_markdown_pages(
    markdown: str,
    page_start: int,
    page_end: int,
) -> list[tuple[int, str]]:
    """Compatibility path for an old provider response; output is still canonical."""

    matches = list(_LEGACY_PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        if page_start == page_end:
            return [(page_start, markdown)]
        raise ValueError("视觉模型没有按物理页返回结构化 Markdown")
    pages: list[tuple[int, str]] = []
    for index, match in enumerate(matches):
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        pages.append((int(match.group(1)), markdown[body_start:body_end]))
    expected = list(range(page_start, page_end + 1))
    if [page_number for page_number, _body in pages] != expected:
        raise ValueError("视觉模型返回的旧版物理页标记不完整")
    return pages


def _reviewed_pages(
    payload: dict[str, Any],
    page_start: int,
    page_end: int,
) -> list[tuple[int, str]]:
    raw_pages = payload.get("pages")
    pages: list[tuple[int, str]]
    if isinstance(raw_pages, list):
        pages = []
        for item in raw_pages:
            if not isinstance(item, dict):
                raise ValueError("视觉模型 pages 必须是对象数组")
            page_number = item.get("page_number")
            if not isinstance(page_number, int) or isinstance(page_number, bool):
                raise ValueError("视觉模型 page_number 必须是整数")
            body = item.get("markdown", "")
            if not isinstance(body, str):
                raise ValueError("视觉模型逐页 Markdown 必须是字符串")
            pages.append((page_number, body))
    else:
        raw_markdown = payload.get("markdown", "")
        if not isinstance(raw_markdown, str):
            raise ValueError("视觉模型没有返回可用的 Markdown")
        pages = _legacy_markdown_pages(raw_markdown, page_start, page_end)

    expected = list(range(page_start, page_end + 1))
    if [page_number for page_number, _body in pages] != expected:
        raise ValueError(
            "视觉模型返回的物理页集合不完整："
            f"expected={expected}, "
            f"actual={[page_number for page_number, _body in pages]}"
        )
    return [(page_number, _without_answer_scaffolding(body)) for page_number, body in pages]


@dataclass(frozen=True)
class VisionReviewResult:
    markdown: str
    repairs: tuple[str, ...]
    confidence: float
    model: str


class PaperVisionReviewer:
    """Reconcile a MinerU page chunk against the rendered source pages."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
    ):
        self.settings = settings
        self.client = client

    def review_chunk(
        self,
        source_path: Path,
        markdown: str,
        page_start: int,
        page_end: int,
        _allow_empty: bool = False,
    ) -> VisionReviewResult:
        if page_start != page_end:
            parsed_pages = parse_physical_page_markdown(markdown)
            page_inputs = (
                validate_physical_page_markdown(markdown, page_start, page_end)
                if parsed_pages
                else [(page_number, markdown) for page_number in range(page_start, page_end + 1)]
            )
            results = [
                self.review_chunk(
                    source_path,
                    body,
                    page_number,
                    page_number,
                    _allow_empty=True,
                )
                for page_number, body in page_inputs
            ]
            combined_markdown = "\n\n".join(result.markdown for result in results)
            combined_length = sum(
                len(body.strip()) for _page, body in parse_physical_page_markdown(combined_markdown)
            )
            if combined_length < 10 <= len(markdown.strip()):
                raise ValueError("视觉模型没有返回可用的页段 Markdown")
            return VisionReviewResult(
                markdown=combined_markdown,
                repairs=tuple(repair for result in results for repair in result.repairs),
                confidence=min(result.confidence for result in results),
                model=self.settings.paper_vision_model,
            )

        images = self._render_pages(source_path, page_start, page_end)
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": self._prompt(markdown, page_start, page_end),
            }
        ]
        for page_number, image in images:
            encoded = base64.b64encode(image).decode("ascii")
            content.extend(
                [
                    {"type": "text", "text": f"PDF page {page_number}:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    },
                ]
            )

        payload, reviewed = self._complete(
            content,
            page_start=page_start,
            page_end=page_end,
        )
        reviewed_length = sum(
            len(body.strip()) for _page, body in parse_physical_page_markdown(reviewed)
        )
        source_pages = parse_physical_page_markdown(markdown)
        source_length = (
            sum(len(body.strip()) for _page, body in source_pages)
            if source_pages
            else len(markdown.strip())
        )
        if not _allow_empty and reviewed_length < 10 <= source_length:
            raise ValueError("视觉模型没有返回可用的页段 Markdown")
        raw_repairs = payload.get("repairs", [])
        repairs = (
            tuple(str(item).strip() for item in raw_repairs if str(item).strip())
            if isinstance(raw_repairs, list)
            else ()
        )
        try:
            confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        return VisionReviewResult(
            markdown=reviewed,
            repairs=repairs,
            confidence=confidence,
            model=self.settings.paper_vision_model,
        )

    def _complete(
        self,
        content: list[dict[str, Any]],
        *,
        page_start: int,
        page_end: int,
    ) -> tuple[dict[str, Any], str]:
        provider_api_key = self.settings.llm_provider_api_key
        api_key = provider_api_key.get_secret_value() if provider_api_key else None
        if not api_key:
            raise RuntimeError("视觉复核需要配置模型供应商 API Key")
        request = {
            "model": self.settings.paper_vision_model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": 12000,
            "enable_thinking": False,
        }
        own_client = self.client is None
        client = self.client or httpx.Client(timeout=self.settings.paper_vision_timeout)
        last_error: Exception | None = None
        try:
            for attempt in range(1, self.settings.paper_vision_max_attempts + 1):
                attempt_started = time.monotonic()
                try:
                    response = client.post(
                        f"{self.settings.llm_provider_base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=request,
                        timeout=self.settings.paper_vision_timeout,
                    )
                    response.raise_for_status()
                    body = response.json()
                    message = body["choices"][0]["message"]
                    text = message.get("content", "")
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError("视觉模型没有返回文本内容")
                    payload = parse_json_response(text)
                    confidence = float(payload.get("confidence", 0))
                    if confidence < self.settings.paper_vision_min_confidence:
                        raise ValueError(
                            "视觉复核置信度过低："
                            f"{confidence:.2f} < "
                            f"{self.settings.paper_vision_min_confidence:.2f}"
                        )
                    reviewed = format_physical_page_markdown(
                        _reviewed_pages(payload, page_start, page_end)
                    )
                    validate_physical_page_markdown(
                        reviewed,
                        page_start,
                        page_end,
                    )
                    return payload, reviewed
                except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                    last_error = error
                    if (
                        attempt >= self.settings.paper_vision_max_attempts
                        or not _is_retryable_failure(error)
                    ):
                        break
                    delay = self.settings.paper_vision_retry_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "paper vision request failed; retry scheduled",
                        extra={
                            "event": "paper_vision_retry",
                            "stage": "vision_review",
                            "page_start": page_start,
                            "page_end": page_end,
                            "attempt": attempt,
                            "max_attempts": self.settings.paper_vision_max_attempts,
                            "retry_in_seconds": delay,
                            "duration_ms": round(
                                (time.monotonic() - attempt_started) * 1000,
                                2,
                            ),
                            "error_type": type(error).__name__,
                        },
                    )
                    if delay:
                        time.sleep(delay)
        finally:
            if own_client:
                client.close()
        assert last_error is not None
        raise last_error

    @staticmethod
    def _render_pages(
        source_path: Path,
        page_start: int,
        page_end: int,
    ) -> list[tuple[int, bytes]]:
        if page_start < 1 or page_end < page_start:
            raise ValueError("视觉复核页码范围无效")
        rendered: list[tuple[int, bytes]] = []
        with pymupdf.open(source_path) as document:
            if page_end > document.page_count:
                raise ValueError("视觉复核页码超出 PDF 范围")
            matrix = pymupdf.Matrix(1.6, 1.6)
            for page_number in range(page_start, page_end + 1):
                page = document.load_page(page_number - 1)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                rendered.append((page_number, pixmap.tobytes("jpeg", jpg_quality=82)))
        return rendered

    @staticmethod
    def _prompt(markdown: str, page_start: int, page_end: int) -> str:
        return f"""
You are the visual quality gate for an examination question paper.
Compare the MinerU Markdown with the rendered PDF pages {page_start}-{page_end}.
The page images are the source of truth. Repair the Markdown, do not solve anything.

Requirements:
- Preserve every printed question number, subpart label, instruction, equation, table,
  multiple-choice option, and mark value in reading order.
- Restore text or mathematical notation that MinerU omitted, split, or placed out of order.
- Do not invent wording that is not visible. Write [unreadable] for genuinely unreadable text.
- Remove answer lines, examiner-use boxes, barcodes, headers, footers, and blank space.
- For a diagram needed to answer a question, add a concise bracketed visual description
  containing every visible label, coordinate, dimension, curve, and shaded boundary.
- Return exactly one object for every physical PDF page from {page_start} through
  {page_end}, including an object with empty Markdown for a genuinely blank page.
- Never merge two physical pages. Do not add page-marker comments yourself; the
  application attaches immutable page markers after validating this structure.

Return only JSON:
{{
  "pages": [
    {{"page_number": {page_start}, "markdown": "<corrected content from only this page>"}}
  ],
  "repairs": ["short factual description of each material repair"],
  "confidence": 0.0
}}

MinerU Markdown:
{markdown[:30000]}
""".strip()
