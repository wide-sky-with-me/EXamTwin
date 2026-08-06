from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from examtwin.assessment.paper_vision import (
    PaperVisionReviewer,
    parse_physical_page_markdown,
)
from examtwin.platform.config import Settings
from pypdf import PdfWriter


def test_vision_review_retries_and_restores_missing_subpart(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)

    calls = 0
    sent_image = False
    requested_url = ""
    authorization = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal authorization, calls, requested_url, sent_image
        calls += 1
        requested_url = str(request.url)
        authorization = request.headers.get("Authorization", "")
        request_body = json.loads(request.content)
        blocks = request_body["messages"][0]["content"]
        sent_image = any(
            block.get("type") == "image_url"
            and block.get("image_url", {}).get("url", "").startswith("data:image/jpeg;base64,")
            for block in blocks
        )
        if calls < 3:
            return httpx.Response(503, json={"error": "temporary unavailable"})
        corrected = json.dumps(
            {
                "markdown": (
                    "<!-- page 1 -->\n"
                    "6 (a) Find the equation of the line through B and D. [5 marks]\n"
                    "Answer _________________________\n"
                    "6 (b) Find the area of the square. [4 marks]"
                ),
                "repairs": ["Restored question 6(a) from the page image."],
                "confidence": 0.98,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": corrected}}]},
        )

    settings = Settings(
        openai_compat_base_url="https://active.invalid/v1/",
        openai_compat_api_key="active-key",
        paper_vision_max_attempts=3,
        paper_vision_retry_delay_seconds=0,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            "6 (b) Find the area of the square. [4 marks]",
            1,
            1,
        )

    assert calls == 3
    assert sent_image is True
    assert requested_url == "https://active.invalid/v1/chat/completions"
    assert authorization == "Bearer active-key"
    assert "6 (a)" in result.markdown
    assert "Answer ___" not in result.markdown
    assert result.repairs == ("Restored question 6(a) from the page image.",)
    assert result.confidence == 0.98
    retry_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "paper_vision_retry"
    ]
    assert len(retry_records) == 2
    assert retry_records[0].stage == "vision_review"
    assert retry_records[0].page_start == 1
    assert retry_records[0].page_end == 1
    assert retry_records[0].attempt == 1
    assert retry_records[0].max_attempts == 3
    assert retry_records[0].error_type == "HTTPStatusError"


def test_vision_review_does_not_retry_permanent_http_error(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, json={"error": "route not found"})

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=3,
        paper_vision_retry_delay_seconds=0,
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            "1 Find x. [2 marks]",
            1,
            1,
        )

    assert calls == 1


def test_vision_review_sends_multi_page_chunks_as_single_page_requests(
    tmp_path: Path,
) -> None:
    source = tmp_path / "three-pages.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)

    requested_pages: list[int] = []
    image_counts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_body = json.loads(request.content)
        blocks = request_body["messages"][0]["content"]
        prompt = blocks[0]["text"]
        page_number = next(page for page in range(1, 4) if f"pages {page}-{page}" in prompt)
        requested_pages.append(page_number)
        image_counts.append(sum(block.get("type") == "image_url" for block in blocks))
        bodies = {
            1: "1 (a) Find x. [2 marks]",
            2: "",
            3: "1 (b) Hence find y. [3 marks]",
        }
        content = json.dumps(
            {
                "pages": [{"page_number": page_number, "markdown": bodies[page_number]}],
                "repairs": [],
                "confidence": 0.99,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    settings = Settings(openai_compat_api_key="test-key")
    markdown = "MinerU chunk with enough content to review."
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            3,
        )

    assert requested_pages == [1, 2, 3]
    assert image_counts == [1, 1, 1]
    assert parse_physical_page_markdown(result.markdown) == [
        (1, "1 (a) Find x. [2 marks]"),
        (2, ""),
        (3, "1 (b) Hence find y. [3 marks]"),
    ]
    assert result.markdown.count("<!-- examtwin:physical-page=") == 3
