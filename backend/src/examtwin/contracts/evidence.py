from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from examtwin.contracts.base import SerializedResponse

AnswerKind = Literal[
    "text",
    "numeric",
    "expression",
    "proof",
    "table",
    "math_plot",
    "math_diagram",
    "economics_diagram",
    "image",
]
AnswerArtifactTool = Literal[
    "math_plot",
    "math_diagram",
    "economics_diagram",
    "image_generate",
]


class SubpartRequirement(SerializedResponse):
    """A machine-checkable answer obligation extracted while splitting the paper."""

    label: str = Field(default="whole", max_length=32)
    marks: int | None = Field(default=None, ge=0, le=100)
    answer_kind: AnswerKind = "text"
    accuracy: str | None = Field(default=None, max_length=160)
    units: tuple[str, ...] = Field(default=(), max_length=8)
    required_tool: AnswerArtifactTool | None = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        return value.strip() or "whole"

    @field_validator("units")
    @classmethod
    def normalize_units(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(unit.strip() for unit in value if unit.strip()))


class Citation(SerializedResponse):
    source: str
    document_id: str | None = None
    page: int | None = None
    source_type: str | None = None
    authority_tier: str | None = None
    pair_key: str | None = None
    score: float | None = None
    excerpt: str
    section: str | None = None
    section_path: list[str] = Field(default_factory=list)
    knowledge_code: str | None = None
    index_build_id: str | None = None
    evidence_role: (
        Literal["definition", "explanation", "worked_example", "assessment", "marking"] | None
    ) = None
    content_url: str | None = None


DiagramTone = Literal["default", "primary", "secondary", "tertiary", "muted"]


class DiagramLegendItem(SerializedResponse):
    label: str = Field(min_length=1, max_length=120)
    tone: DiagramTone = "default"


class PaperDiagramSource(SerializedResponse):
    """Trusted original-paper pixels used as the calibrated diagram background."""

    kind: Literal["paper_page"] = "paper_page"
    page_number: int = Field(ge=1)
    width: int = Field(ge=16, le=10_000)
    height: int = Field(ge=16, le=10_000)
    calibration: Literal["blank_axes", "existing_curve_grid"]


class DiagramElement(SerializedResponse):
    kind: Literal["line", "polyline", "polygon", "circle", "ellipse", "path", "point", "text"]
    x1: float | None = None
    y1: float | None = None
    x2: float | None = None
    y2: float | None = None
    x: float | None = None
    y: float | None = None
    cx: float | None = None
    cy: float | None = None
    r: float | None = None
    rx: float | None = None
    ry: float | None = None
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=120)
    d: str | None = Field(default=None, max_length=4000)
    text: str | None = Field(default=None, max_length=240)
    dashed: bool = False
    emphasis: bool = False
    arrow_start: bool = False
    arrow_end: bool = False
    fill: Literal["none", "light", "accent"] = "none"
    tone: DiagramTone = "default"

    @field_validator("d")
    @classmethod
    def validate_svg_path(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[MmLlHhVvCcSsQqTtAaZz0-9eE+.,\s-]+", value):
            raise ValueError("diagram path contains unsupported characters")
        return value

    @model_validator(mode="after")
    def validate_geometry(self) -> DiagramElement:
        required: dict[str, tuple[str, ...]] = {
            "line": ("x1", "y1", "x2", "y2"),
            "circle": ("cx", "cy", "r"),
            "ellipse": ("cx", "cy", "rx", "ry"),
            "point": ("x", "y"),
            "text": ("x", "y", "text"),
            "path": ("d",),
        }
        missing = [name for name in required.get(self.kind, ()) if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} diagram element is missing {', '.join(missing)}")
        if self.kind in {"polyline", "polygon"} and len(self.points) < 2:
            raise ValueError(f"{self.kind} diagram element needs at least two points")
        return self


class AnswerDiagram(SerializedResponse):
    title: str = Field(min_length=1, max_length=160)
    caption: str = Field(default="", max_length=500)
    tool_name: Literal["math_plot", "math_diagram", "economics_diagram"] = "math_diagram"
    view_box: tuple[float, float, float, float] = (0, 0, 600, 360)
    elements: list[DiagramElement] = Field(default_factory=list, min_length=1, max_length=160)
    legend: list[DiagramLegendItem] = Field(default_factory=list, max_length=12)
    source: PaperDiagramSource | None = None

    @field_validator("view_box")
    @classmethod
    def validate_view_box(
        cls, value: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        if value[2] <= 0 or value[3] <= 0:
            raise ValueError("diagram view box width and height must be positive")
        return value

    @model_validator(mode="after")
    def validate_source_crop(self) -> AnswerDiagram:
        if self.source is None:
            return self
        x, y, width, height = self.view_box
        if x < 0 or y < 0:
            raise ValueError("paper-backed diagram crop cannot start outside the page")
        if x + width > self.source.width or y + height > self.source.height:
            raise ValueError("paper-backed diagram crop exceeds the source page")
        return self


class AnswerImage(SerializedResponse):
    """Opaque raster artifact generated by a trusted answering tool."""

    title: str = Field(min_length=1, max_length=160)
    caption: str = Field(default="", max_length=500)
    tool_name: Literal["image_generate"] = "image_generate"
    content_url: str = Field(
        pattern=r"^/api/v1/answer-assets/[0-9a-f]{32}\.png$",
        max_length=96,
    )
    media_type: Literal["image/png"] = "image/png"
    width: int = Field(default=1024, ge=16, le=3840)
    height: int = Field(default=1024, ge=16, le=3840)
    generated: Literal[True] = True
