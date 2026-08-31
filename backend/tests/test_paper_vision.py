from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from examtwin.assessment.paper_vision import (
    PaperVisionReviewer,
    parse_physical_page_markdown,
)
from examtwin.platform.config import Settings
from examtwin.platform.litellm_provider import provider_model_name
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


def _completion_via(client: httpx.Client):
    """Exercise the production LiteLLM request contract through a mock HTTP transport."""

    def completion(**kwargs: Any) -> dict[str, Any]:
        api_base = str(kwargs.pop("api_base"))
        api_key = str(kwargs.pop("api_key"))
        timeout = float(kwargs.pop("timeout"))
        kwargs.pop("max_retries")
        kwargs["model"] = provider_model_name(str(kwargs["model"]), "openai")
        response = client.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=kwargs,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    return completion


def test_vision_review_retries_and_restores_missing_subpart(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)

    calls = 0
    sent_image = False
    captured_request: dict[str, object] = {}

    class TransientProviderError(RuntimeError):
        status_code = 503

    def fake_completion(**request_body: Any) -> dict[str, object]:
        nonlocal calls, sent_image
        calls += 1
        captured_request.update(request_body)
        blocks = request_body["messages"][0]["content"]
        assert isinstance(blocks, list)
        sent_image = any(
            block.get("type") == "image_url"
            and block.get("image_url", {}).get("url", "").startswith("data:image/jpeg;base64,")
            for block in blocks
        )
        if calls < 3:
            raise TransientProviderError("temporary unavailable")
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
        return {"choices": [{"message": {"content": corrected}}]}

    monkeypatch.setattr("litellm.completion", fake_completion)

    settings = Settings(
        llm_base_url="https://active.invalid/v1/",
        llm_api_key="active-key",
        paper_vision_max_attempts=3,
        paper_vision_retry_delay_seconds=0,
        paper_vision_max_output_tokens=4_321,
    )
    result = PaperVisionReviewer(settings).review_chunk(
        source,
        "6 (b) Find the area of the square. [4 marks]",
        1,
        1,
    )

    assert calls == 3
    assert sent_image is True
    assert captured_request["model"] == f"openai/{settings.paper_vision_model}"
    assert captured_request["api_base"] == "https://active.invalid/v1"
    assert captured_request["api_key"] == "active-key"
    assert captured_request["reasoning_effort"] == "low"
    assert captured_request["max_tokens"] == 4_321
    assert "temperature" not in captured_request
    assert "enable_thinking" not in captured_request
    response_format = captured_request["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
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
    assert retry_records[0].error_type == "TransientProviderError"


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
        llm_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        f"1 Use the diagram.\n\n![Force diagram]({image_url})\n\nCalculate the force. [2 marks]"
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
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
        llm_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        f"1 Use the diagram.\n\n![Force diagram]({image_url})\n\nCalculate the force. [2 marks]"
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
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
        llm_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"9 Incorrect OCR copied from an earlier page. [6 marks]\n\n![]({image_url})"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
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
        llm_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"9 Incorrect OCR copied from an earlier page. [6 marks]\n\n![]({image_url})"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
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


def test_vision_review_accepts_empty_multi_page_discardable_chunk(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    responses = [
        _classified_page(1, "", role="answer_space"),
        _classified_page(2, "", role="administrative"),
    ]
    calls = 0
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        request_body = json.loads(request.content)
        prompts.append(request_body["messages"][0]["content"][0]["text"])
        page = responses[calls]
        calls += 1
        content = json.dumps({"pages": [page], "repairs": [], "confidence": 0.99})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        llm_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        "<!-- examtwin:physical-page=1 -->\nAdditional answer page.\n\n"
        "<!-- examtwin:physical-page=2 -->\nCopyright information."
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            markdown,
            1,
            2,
        )

    assert calls == 2
    assert parse_physical_page_markdown(result.markdown) == [(1, ""), (2, "")]
    assert [item.role for item in result.page_classifications] == [
        "answer_space",
        "administrative",
    ]
    assert "Additional answer page." in prompts[0]
    assert "Copyright information." not in prompts[0]
    assert "Copyright information." in prompts[1]
    assert "Additional answer page." not in prompts[1]


@pytest.mark.parametrize(
    ("role", "confidence"),
    [("question", 0.99), ("administrative", 0.85)],
)
def test_vision_review_rejects_empty_multi_page_chunk_without_safe_classifications(
    tmp_path: Path,
    role: str,
    confidence: float,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    responses = [
        _classified_page(1, "", role=role, confidence=confidence),
        _classified_page(2, "", role="administrative"),
    ]
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        page = responses[calls]
        calls += 1
        content = json.dumps({"pages": [page], "repairs": [], "confidence": 0.99})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    settings = Settings(
        llm_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = (
        "<!-- examtwin:physical-page=1 -->\nPotentially protected content.\n\n"
        "<!-- examtwin:physical-page=2 -->\nAdministrative content."
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="视觉模型没有返回可用的页段 Markdown"),
    ):
        PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            markdown,
            1,
            2,
        )


def test_vision_review_preserves_source_without_retry_when_model_discards_question_page_image(
    tmp_path: Path,
) -> None:
    source = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with source.open("wb") as output:
        writer.write(output)
    image_url = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'d' * 64}.png"
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
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
        llm_api_key="test-key",
        paper_vision_max_attempts=2,
        paper_vision_retry_delay_seconds=0,
    )
    markdown = f"1 Use the diagram.\n\n![]({image_url})\n\nFind x. [2 marks]"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            markdown,
            1,
            1,
        )

    assert calls == 1
    assert result.markdown.endswith(markdown)
    assert image_url in result.markdown
    assert result.confidence == settings.paper_vision_min_confidence
    assert "图片排除声明未通过门禁" in result.repairs[-2]
    assert result.repairs[-1] == "视觉模型持续遗漏来源图片；已保留该物理页的 MinerU 原文。"


@pytest.mark.parametrize(
    ("role", "confidence"),
    [
        ("source_material", 0.99),
        ("administrative", 0.85),
    ],
)
def test_vision_review_preserves_source_after_unsafe_non_question_discard(
    tmp_path: Path,
    role: str,
    confidence: float,
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
        llm_api_key="test-key",
        paper_vision_max_attempts=1,
        paper_vision_retry_delay_seconds=0,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            f"Reference material.\n\n![]({image_url})",
            1,
            1,
        )

    assert result.markdown.endswith(f"Reference material.\n\n![]({image_url})")
    assert image_url in result.markdown
    assert result.confidence == settings.paper_vision_min_confidence
    assert "图片排除声明未通过门禁" in result.repairs[-2]
    assert result.repairs[-1] == "视觉模型持续遗漏来源图片；已保留该物理页的 MinerU 原文。"


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
        llm_api_key="test-key",
        paper_vision_max_attempts=3,
        paper_vision_retry_delay_seconds=0,
    )
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            "1 Find x. [2 marks]",
            1,
            1,
        )

    assert calls == 1


def test_vision_review_scopes_multi_page_requests_and_recovers_only_current_page_image(
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

    settings = Settings(
        llm_api_key="test-key",
        paper_vision_max_attempts=1,
    )
    page_one_image = f"/api/v1/papers/jobs/job-1/question-images/p0001-{'a' * 64}.png"
    markdown = f"MinerU multi-page chunk.\n\n![]({page_one_image})"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = PaperVisionReviewer(settings, completion=_completion_via(client)).review_chunk(
            source,
            markdown,
            1,
            3,
        )

    assert requested_pages == [1, 2, 3]
    assert image_counts == [1, 1, 1]
    assert parse_physical_page_markdown(result.markdown) == [
        (1, f"1 (a) Find x. [2 marks]\n\n![]({page_one_image})"),
        (2, ""),
        (3, "1 (b) Hence find y. [3 marks]"),
    ]
    assert result.markdown.count("MinerU multi-page chunk") == 0
    assert result.repairs[-1] == "视觉模型持续遗漏来源图片；已将当前物理页图片附回复核结果。"
    assert result.markdown.count("<!-- examtwin:physical-page=") == 3
