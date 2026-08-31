from __future__ import annotations

import asyncio
import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

import pymupdf
from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, ConfigDict, Field

from examtwin.assessment.answering_agent.contracts import AgentRunContext
from examtwin.contracts.evidence import AnswerImage
from examtwin.contracts.system import API_PREFIX
from examtwin.platform.database.session import utcnow
from examtwin.platform.litellm_provider import (
    configure_litellm,
    litellm_model_name,
    retryable_provider_error,
)
from examtwin.platform.storage import LocalObjectStore, ManagedObjectStore, ObjectMetadata

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ASSET_ID = re.compile(r"^[0-9a-f]{32}$")
ImageSize = Literal["1024x1024", "1536x1024", "1024x1536"]
ImageQuality = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class GeneratedImage:
    content: bytes
    width: int
    height: int


class ImageGenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=8, max_length=4_000)
    title: str = Field(min_length=1, max_length=160)
    caption: str = Field(default="", max_length=500)
    answer_anchor: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description=(
            "Exact printed subpart label this image answers, such as `(b)` or `.2`; use "
            "`whole` only when the question has no labelled subparts."
        ),
    )
    size: ImageSize = "1024x1024"
    quality: ImageQuality = "medium"


def _normalize_png(content: bytes) -> GeneratedImage:
    """Fully decode and re-encode a provider PNG before it reaches artifact storage."""

    if not content.startswith(PNG_SIGNATURE):
        raise ValueError("image generation provider did not return a PNG")
    try:
        pixmap = pymupdf.Pixmap(content)
        normalized = pixmap.tobytes("png")
    except Exception as error:
        raise ValueError("image generation provider returned a corrupt PNG") from error
    width, height = pixmap.width, pixmap.height
    if not (16 <= width <= 3840 and 16 <= height <= 3840):
        raise ValueError("generated PNG dimensions are outside the supported range")
    return GeneratedImage(content=normalized, width=width, height=height)


class ImageGenerationProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        size: ImageSize,
        quality: ImageQuality,
    ) -> GeneratedImage: ...


class LiteLLMImageProvider:
    """Bounded image generation adapter routed through LiteLLM."""

    def __init__(
        self,
        model: str,
        api_base: str,
        api_key: str,
        *,
        provider: str,
        timeout: float,
        max_attempts: int,
        max_output_bytes: int,
    ) -> None:
        if not model.strip():
            raise ValueError("Image generation model is required")
        if not api_base.strip():
            raise ValueError("Image generation API base is required")
        if not api_key:
            raise ValueError("Image generation API key is required")
        if timeout <= 0:
            raise ValueError("Image generation timeout must be positive")
        if not 1 <= max_attempts <= 3:
            raise ValueError("Image generation attempts must be between one and three")
        if max_output_bytes < 64 * 1024:
            raise ValueError("Image generation output limit is too small")
        self.model = model
        self.litellm_model = litellm_model_name(model, provider)
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_output_bytes = max_output_bytes

    async def generate(
        self,
        prompt: str,
        size: ImageSize,
        quality: ImageQuality,
    ) -> GeneratedImage:
        generated_prompt = (
            "Create a clear educational answer illustration. Keep the composition "
            "focused, use a clean light background, and do not add explanatory prose "
            "outside the requested visual. "
            f"\n\nRequested visual:\n{prompt}"
        )
        for attempt in range(1, self.max_attempts + 1):
            try:
                configure_litellm()
                from litellm import aimage_generation

                response = await aimage_generation(
                    model=self.litellm_model,
                    api_base=self.api_base,
                    api_key=self.api_key,
                    prompt=generated_prompt,
                    size=size,
                    quality=quality,
                    n=1,
                    output_format="png",
                    timeout=self.timeout,
                    max_retries=0,
                )
            except Exception as error:
                if attempt < self.max_attempts and retryable_provider_error(error):
                    await asyncio.sleep(attempt)
                    continue
                raise RuntimeError("Image generation provider request failed") from error
            try:
                data = response.get("data") if isinstance(response, Mapping) else response.data
                if not data:
                    raise ValueError("missing image data")
                item: Any = data[0]
                encoded = item.get("b64_json") if isinstance(item, Mapping) else item.b64_json
            except (AttributeError, KeyError, IndexError, TypeError, ValueError) as error:
                raise ValueError(
                    "Image generation provider returned an invalid response"
                ) from error
            if not isinstance(encoded, str):
                raise ValueError("Image generation provider did not return base64 image data")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError(
                    "Image generation provider returned invalid base64 data"
                ) from error
            if len(content) > self.max_output_bytes:
                raise ValueError("Generated image exceeds the configured output limit")
            generated = _normalize_png(content)
            if len(generated.content) > self.max_output_bytes:
                raise ValueError("Normalized image exceeds the configured output limit")
            return generated
        raise RuntimeError("Image generation retry loop exhausted")


class AnswerImageStore:
    def __init__(
        self,
        store: ManagedObjectStore | Path,
        *,
        retention_days: int = 30,
    ) -> None:
        if isinstance(store, Path):
            self.store = ManagedObjectStore(LocalObjectStore(store))
            self.prefix = ""
        else:
            self.store = store
            self.prefix = "answer-artifacts/"
        self.retention_days = retention_days

    def _key(self, asset_id: str) -> str:
        return f"{self.prefix}{asset_id}.png"

    def save(
        self,
        generated: GeneratedImage,
        *,
        title: str,
        caption: str,
    ) -> AnswerImage:
        asset_id = uuid4().hex
        self.store.put_bytes(
            self._key(asset_id),
            generated.content,
            metadata=ObjectMetadata(
                purpose="answer_image",
                owner_type="answer_asset",
                owner_id=asset_id,
                retain_until=utcnow() + timedelta(days=self.retention_days),
                content_type="image/png",
            ),
        )
        return AnswerImage(
            title=title,
            caption=caption,
            content_url=f"{API_PREFIX}/answer-assets/{asset_id}.png",
            width=generated.width,
            height=generated.height,
        )

    def resolve(self, asset_id: str) -> Path:
        if not ASSET_ID.fullmatch(asset_id):
            raise LookupError("Generated answer image does not exist")
        try:
            return self.store.materialize(self._key(asset_id))
        except (LookupError, ValueError) as error:
            raise LookupError("Generated answer image does not exist") from error

    def delete(self, image: AnswerImage) -> None:
        prefix = f"{API_PREFIX}/answer-assets/"
        if not image.content_url.startswith(prefix) or not image.content_url.endswith(".png"):
            raise ValueError("Generated answer image URL is invalid")
        asset_id = image.content_url[len(prefix) : -len(".png")]
        if not ASSET_ID.fullmatch(asset_id):
            raise ValueError("Generated answer image URL is invalid")
        try:
            self.store.delete(self._key(asset_id))
        except ValueError as error:
            raise ValueError("Generated answer image path escaped artifact storage") from error


class ImageGenerationTool:
    name = "image_generate"

    def __init__(
        self,
        provider: ImageGenerationProvider,
        store: AnswerImageStore,
        *,
        timeout_seconds: float,
    ) -> None:
        self._provider = provider
        self._store = store
        self._timeout_seconds = timeout_seconds

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def image_generate(
            prompt: str,
            title: str,
            caption: str = "",
            answer_anchor: str | None = None,
            size: ImageSize = "1024x1024",
            quality: ImageQuality = "medium",
        ) -> str:
            """Generate one raster answer illustration and return its saved artifact metadata."""

            request = ImageGenerationInput(
                prompt=prompt,
                title=title,
                caption=caption,
                answer_anchor=answer_anchor,
                size=size,
                quality=quality,
            )
            request = request.model_copy(
                update={
                    "answer_anchor": context.resolve_artifact_anchor(
                        self.name,
                        request.answer_anchor,
                    )
                }
            )
            context.ensure_image_capacity()
            async with asyncio.timeout(self._timeout_seconds):
                generated = await self._provider.generate(
                    request.prompt,
                    request.size,
                    request.quality,
                )
            image = self._store.save(
                generated,
                title=request.title,
                caption=request.caption,
            )
            image = image.model_copy(update={"answer_anchor": request.answer_anchor})
            try:
                image = context.add_image(image)
                context.register_artifact_rollback(lambda: self._store.delete(image))
            except BaseException:
                self._store.delete(image)
                raise
            return image.model_dump_json()

        return FunctionTool.from_defaults(
            async_fn=image_generate,
            name=self.name,
            fn_schema=ImageGenerationInput,
            description=(
                "Generate a raster educational illustration with the configured GPT Image "
                "model. Use only when a subject answer needs a pictorial image that the exact "
                "math_plot or math_diagram vector tools cannot represent. The server stores "
                "the PNG and returns metadata; never put base64 or raw image bytes in the answer."
            ),
        )
