from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pymupdf
import pytest
from examtwin.answering_agent.contracts import AgentRunContext, AnswerTask
from examtwin.answering_agent.tools.image_generate import (
    PNG_SIGNATURE,
    AnswerImageStore,
    GeneratedImage,
    ImageGenerationTool,
    OpenAICompatibleImageProvider,
    _normalize_png,
)
from examtwin.api.papers import answer_image_asset
from fastapi import HTTPException


def _png(width: int = 1024, height: int = 1024) -> bytes:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, height), False)
    pixmap.clear_with(255)
    return pixmap.tobytes("png")


@pytest.mark.asyncio
async def test_image_provider_retries_transient_status_and_validates_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://images.invalid/v1/images/generations")
    responses = [
        httpx.Response(503, request=request, json={"error": {"message": "temporary"}}),
        httpx.Response(
            200,
            request=request,
            json={"data": [{"b64_json": base64.b64encode(_png()).decode("ascii")}]},
        ),
    ]
    calls: list[dict[str, Any]] = []

    async def fake_post(*_args: Any, **kwargs: Any) -> httpx.Response:
        calls.append(kwargs)
        return responses.pop(0)

    monkeypatch.setattr(
        "examtwin.answering_agent.tools.image_generate.httpx.AsyncClient.post",
        fake_post,
    )

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "examtwin.answering_agent.tools.image_generate.asyncio.sleep",
        no_sleep,
    )
    provider = OpenAICompatibleImageProvider(
        "gpt-image-2",
        "https://images.invalid/v1",
        "test-key",
        timeout=90,
        max_attempts=2,
        max_output_bytes=64 * 1024,
    )

    generated = await provider.generate(
        "A clean educational illustration of a right triangle.",
        "1024x1024",
        "low",
    )

    assert generated.width == 1024
    assert generated.height == 1024
    assert len(calls) == 2
    assert calls[1]["json"]["model"] == "gpt-image-2"
    assert calls[1]["headers"]["Authorization"] == "Bearer test-key"


def test_full_png_decode_rejects_a_truncated_payload() -> None:
    with pytest.raises(ValueError, match="corrupt PNG"):
        _normalize_png(PNG_SIGNATURE + b"truncated")


@pytest.mark.asyncio
async def test_image_tool_saves_opaque_artifact_without_returning_base64(
    tmp_path: Path,
) -> None:
    class FakeProvider:
        async def generate(
            self,
            _prompt: str,
            _size: str,
            _quality: str,
        ) -> GeneratedImage:
            return GeneratedImage(_png(1024, 1024), 1024, 1024)

    context = AgentRunContext(
        task=AnswerTask(subject_code="9660", question="Draw a clear educational illustration.")
    )
    store = AnswerImageStore(tmp_path)
    tool = ImageGenerationTool(
        FakeProvider(),  # type: ignore[arg-type]
        store,
        timeout_seconds=10,
    ).bind(context)

    result = await tool.acall(
        prompt="A textbook illustration of a membrane with no prose.",
        title="Cell membrane",
        caption="Generated answer illustration.",
        quality="low",
    )

    assert result.is_error is False
    assert "base64" not in result.content
    assert len(context.images) == 1
    image = context.images[0]
    assert image.content_url.startswith("/api/v1/answer-assets/")
    assert store.resolve(image.content_url.rsplit("/", 1)[1].removesuffix(".png")).read_bytes() == (
        _png()
    )

    context.rollback_artifacts()
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_image_capacity_is_checked_before_calling_provider(tmp_path: Path) -> None:
    class CountingProvider:
        calls = 0

        async def generate(
            self,
            _prompt: str,
            _size: str,
            _quality: str,
        ) -> GeneratedImage:
            self.calls += 1
            return GeneratedImage(_png(), 1024, 1024)

    context = AgentRunContext(
        task=AnswerTask(subject_code="9660", question="Create several illustrations.")
    )
    store = AnswerImageStore(tmp_path)
    for index in range(3):
        context.add_image(
            store.save(
                GeneratedImage(_png(16, 16), 16, 16),
                title=f"Existing {index}",
                caption="",
            )
        )
    provider = CountingProvider()
    tool = ImageGenerationTool(provider, store, timeout_seconds=10).bind(context)

    with pytest.raises(ValueError, match="maximum of three"):
        await tool.acall(
            prompt="A fourth educational illustration that must not be requested.",
            title="Fourth image",
        )

    assert provider.calls == 0


def test_answer_image_route_serves_only_valid_opaque_assets(tmp_path: Path) -> None:
    store = AnswerImageStore(tmp_path)
    image = store.save(
        GeneratedImage(_png(), 1024, 1024),
        title="Generated visual",
        caption="",
    )
    asset_id = image.content_url.rsplit("/", 1)[1].removesuffix(".png")
    response = answer_image_asset(asset_id, store)

    assert response.media_type == "image/png"
    assert Path(response.path).read_bytes() == _png()
    with pytest.raises(HTTPException) as missing:
        answer_image_asset("0" * 32, store)
    assert missing.value.status_code == 404
    assert store.resolve(asset_id).is_file()
