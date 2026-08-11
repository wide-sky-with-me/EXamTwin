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


def _classified_page(
    page_number: int,
    markdown: str,
    *,
    role: str = "question",
    confidence: float = 0.99,
) -> dict[str, object]:
    return {
        "page_number": page_number,
        "page_role": role,
        "contains_question": role == "question",
        "classification_evidence": f"Visible {role.replace('_', ' ')} content.",
        "classification_confidence": confidence,
        "markdown": markdown,
    }


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
                "pages": [
                    _classified_page(
                        1,
                        "6 (a) Find the equation of the line through B and D. [5 marks]\n"
                        "Answer _________________________\n"
                        "6 (b) Find the area of the square. [4 marks]",
                    )
                ],
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


def test_vision_review_retries_when_mineru_image_position_is_lost(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'a' * 64}.png"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        image = f"\n\n![Force diagram]({image_url})" if calls > 1 else ""
        content = json.dumps(
            {
                "pages": [
                    _classified_page(
                        1,
                        f"1 Use the diagram.{image}\n\nCalculate the force. [2 marks]",
                    )
                ],
                "repairs": [],
                "confidence": 0.99,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        f"1 Use the diagram.\n\n![Force diagram]({image_url})\n\nCalculate the force. [2 marks]"
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            1,
        )

    assert calls == 2
    assert image_url in result.markdown
    assert result.markdown.index(image_url) < result.markdown.index("Calculate the force")


def test_vision_review_preserves_source_page_when_image_is_always_lost(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'b' * 64}.png"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = json.dumps(
            {
                "pages": [
                    _classified_page(
                        1,
                        "1 Use the diagram.\n\nCalculate the force. [2 marks]",
                    )
                ],
                "repairs": [],
                "confidence": 0.99,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        f"1 Use the diagram.\n\n![Force diagram]({image_url})\n\nCalculate the force. [2 marks]"
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            1,
        )

    assert calls == 2
    assert result.markdown.endswith(markdown)
    assert image_url in result.markdown
    assert result.confidence == settings.paper_vision_min_confidence
    assert result.repairs[-1] == "视觉模型持续遗漏来源图片；已保留该物理页的 MinerU 原文。"
    assert any(
        getattr(record, "event", None) == "paper_vision_source_fallback"
        for record in caplog.records
    )


def test_vision_review_allows_model_to_discard_verified_non_question_page_image(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'c' * 64}.jpg"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = json.dumps(
            {
                "pages": [
                    _classified_page(
                        1,
                        (
                            "There are no questions printed on this page.\n\n"
                            "ANSWER IN THE SPACES PROVIDED."
                        ),
                        role="answer_space",
                    )
                ],
                "discarded_images": [{"url": image_url, "reason": "answer_space"}],
                "repairs": ["Removed OCR content from earlier physical pages."],
                "confidence": 0.99,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"9 Incorrect OCR copied from an earlier page. [6 marks]\n\n![]({image_url})"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            1,
        )

    assert calls == 1
    assert "Incorrect OCR" not in result.markdown
    assert image_url not in result.markdown
    assert "no questions printed" in result.markdown
    assert result.confidence == 0.99


def test_vision_review_accepts_semantic_administrative_page_without_text_marker(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'e' * 64}.jpg"

    def handler(_request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "pages": [_classified_page(1, "", role="administrative")],
                "discarded_images": [{"url": image_url, "reason": "administrative_page"}],
                "repairs": ["Removed an administrative full-page image."],
                "confidence": 0.99,
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"9 Incorrect OCR copied from an earlier page. [6 marks]\n\n![]({image_url})"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            1,
            _allow_empty=True,
        )

    assert parse_physical_page_markdown(result.markdown) == [(1, "")]
    assert image_url not in result.markdown
    assert result.confidence == 0.99
    assert result.page_classifications[0].role == "administrative"


def test_vision_review_rejects_image_discard_from_question_page(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'d' * 64}.png"

    def handler(_request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "pages": [_classified_page(1, "1 Use the diagram. [2 marks]")],
                "discarded_images": [{"url": image_url, "reason": "answer_space"}],
                "repairs": [],
                "confidence": 0.99,
            }
        )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"1 Use the diagram.\n\n![]({image_url})\n\nFind x. [2 marks]"
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="不能从题目、资料或说明页面排除来源图片"),
    ):
        PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            markdown,
            1,
            1,
        )


@pytest.mark.parametrize(
    ("role", "confidence", "expected_error"),
    [
        ("source_material", 0.99, "不能从题目、资料或说明页面排除来源图片"),
        ("administrative", 0.85, "排除非题目页的置信度过低"),
    ],
)
def test_vision_review_fail_closes_unsafe_non_question_discard(
    tmp_path: Path,
    role: str,
    confidence: float,
    expected_error: str,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'f' * 64}.png"

    def handler(_request: httpx.Request) -> httpx.Response:
        content = json.dumps(
            {
                "pages": [
                    _classified_page(
                        1,
                        "Reference data needed by the next question.",
                        role=role,
                        confidence=confidence,
                    )
                ],
                "discarded_images": [{"url": image_url, "reason": "administrative_page"}],
                "repairs": [],
                "confidence": 0.99,
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        openai_compat_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match=expected_error),
    ):
        PaperVisionReviewer(settings, client=client).review_chunk(
            source,
            f"Reference material.\n\n![]({image_url})",
            1,
            1,
        )


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
                "pages": [
                    _classified_page(
                        page_number,
                        bodies[page_number],
                        role="blank" if page_number == 2 else "question",
                    )
                ],
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
