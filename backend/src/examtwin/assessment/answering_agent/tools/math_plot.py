from __future__ import annotations

import math
from typing import Literal

import numpy as np
from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sympy import Symbol, lambdify

from examtwin.assessment.answering_agent.contracts import AgentRunContext
from examtwin.assessment.answering_agent.tools.source_plot_overlay import (
    PlotCalibrationError,
    compile_paper_plot_overlay,
)
from examtwin.assessment.symbolic import parse_safe_expression
from examtwin.contracts.evidence import (
    AnswerDiagram,
    DiagramElement,
    DiagramLegendItem,
    DiagramTone,
)
from examtwin.subjects.public import mathematics_source_plot_overlay_mode

CANVAS_WIDTH = 600.0
CANVAS_HEIGHT = 360.0
PLOT_LEFT = 62.0
PLOT_RIGHT = 24.0
PLOT_TOP = 22.0
PLOT_BOTTOM = 48.0
CURVE_TONES: tuple[Literal["primary", "secondary", "tertiary", "muted"], ...] = (
    "primary",
    "secondary",
    "tertiary",
    "muted",
)


class MathPlotCurve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Safe SymPy expression in the declared variable. Use *, ^, sin, cos, tan, "
            "exp, log, sqrt, Abs/abs and pi; example: Abs(10*cos(pi*(x-37)/180))."
        ),
    )
    variable: str = Field(default="x", pattern=r"^[A-Za-z][A-Za-z0-9_]{0,15}$")
    domain: tuple[float, float] | None = Field(
        default=None,
        description="Optional curve domain; defaults to the plot x_range.",
    )
    samples: int = Field(default=121, ge=24, le=241)
    label: str = Field(default="", max_length=80)
    tone: Literal["auto", "primary", "secondary", "tertiary", "muted"] = Field(
        default="auto",
        description=(
            "Semantic curve colour. Leave as auto to assign a distinct accessible tone. "
            "Use inline Markdown math delimiters in labels, for example `$y=x^2$`."
        ),
    )
    dashed: bool = False
    emphasis: bool = False

    @model_validator(mode="after")
    def validate_domain(self) -> MathPlotCurve:
        if self.domain is not None and self.domain[0] >= self.domain[1]:
            raise ValueError("curve domain must increase")
        return self


class MathPlotSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[tuple[float, float]] = Field(min_length=2, max_length=120)
    dashed: bool = False
    emphasis: bool = False
    arrow_start: bool = False
    arrow_end: bool = False
    tone: DiagramTone = "default"


class MathPlotPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    label: str = Field(
        default="",
        max_length=32,
        description=(
            "Short point label placed automatically near the point with collision avoidance; "
            "put longer explanation in the diagram caption."
        ),
    )
    emphasis: bool = True
    tone: DiagramTone = "primary"


class MathPlotLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(
        description=(
            "Exact data x-coordinate of the text origin. Offset it yourself when annotating "
            "a nearby point; use points[].label for automatic placement."
        )
    )
    y: float = Field(description="Exact data y-coordinate of the text baseline.")
    text: str = Field(
        min_length=1,
        max_length=32,
        description="Short in-plot annotation; put longer explanation in the diagram caption.",
    )
    tone: DiagramTone = "default"


class MathPlotInput(BaseModel):
    """High-level mathematical coordinate plot compiled into a safe vector scene."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    caption: str = Field(default="", max_length=500)
    answer_anchor: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
        description=(
            "Exact printed subpart label this plot answers, such as `(b)` or `.2`; use `whole` "
            "only when the question has no labelled subparts."
        ),
    )
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    x_label: str = Field(default="x", max_length=40)
    y_label: str = Field(default="y", max_length=40)
    curves: list[MathPlotCurve] = Field(default_factory=list, max_length=6)
    segments: list[MathPlotSegment] = Field(default_factory=list, max_length=80)
    points: list[MathPlotPoint] = Field(default_factory=list, max_length=40)
    labels: list[MathPlotLabel] = Field(default_factory=list, max_length=40)
    show_grid: bool = True

    @model_validator(mode="after")
    def validate_ranges_and_content(self) -> MathPlotInput:
        if self.x_range[0] >= self.x_range[1] or self.y_range[0] >= self.y_range[1]:
            raise ValueError("plot ranges must increase")
        if not (self.curves or self.segments or self.points):
            raise ValueError("plot requires at least one curve, segment, or point")
        return self


def _map_point(
    x: float,
    y: float,
    *,
    x_range: tuple[float, float],
    y_range: tuple[float, float],
) -> tuple[float, float]:
    plot_width = CANVAS_WIDTH - PLOT_LEFT - PLOT_RIGHT
    plot_height = CANVAS_HEIGHT - PLOT_TOP - PLOT_BOTTOM
    mapped_x = PLOT_LEFT + (x - x_range[0]) / (x_range[1] - x_range[0]) * plot_width
    mapped_y = PLOT_TOP + (y_range[1] - y) / (y_range[1] - y_range[0]) * plot_height
    return round(mapped_x, 3), round(mapped_y, 3)


def _tick_values(bounds: tuple[float, float], count: int = 5) -> list[float]:
    start, end = bounds
    return [start + (end - start) * index / (count - 1) for index in range(count)]


def _tick_text(value: float) -> str:
    if math.isclose(value, round(value), abs_tol=1e-9):
        return str(int(round(value)))
    return f"{value:.3g}"


def _text_box(x: float, y: float, text: str) -> tuple[float, float, float, float]:
    """Approximate the exact boxes used by AnswerDiagramView for collision checks."""

    has_math = (
        (text.count("$") >= 2)
        or ("\\(" in text and "\\)" in text)
        or ("\\[" in text and "\\]" in text)
    )
    if has_math:
        # Keep this aligned with the foreignObject contract in AnswerDiagramView.
        return (x, y - 29.0, x + 190.0, y + 23.0)
    # The SVG uses a 16px sans-serif font. One em per non-space character is
    # deliberately conservative for Latin, mathematical Unicode, and CJK; it
    # avoids declaring a collision clear when the browser's glyphs are wider.
    width = max(10.0, sum(5.0 if character.isspace() else 16.0 for character in text))
    return (x, y - 15.0, x + width, y + 5.0)


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return (
        first[0] < second[2]
        and first[2] > second[0]
        and first[1] < second[3]
        and first[3] > second[1]
    )


def _box_inside_canvas(box: tuple[float, float, float, float]) -> bool:
    return (
        2 <= box[0] and box[2] <= CANVAS_WIDTH - 2 and 2 <= box[1] and box[3] <= CANVAS_HEIGHT - 2
    )


def _overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def _base_elements(spec: MathPlotInput) -> list[DiagramElement]:
    elements: list[DiagramElement] = []
    x_ticks = _tick_values(spec.x_range)
    y_ticks = _tick_values(spec.y_range)
    x_axis_y = 0.0 if spec.y_range[0] <= 0 <= spec.y_range[1] else spec.y_range[0]
    y_axis_x = 0.0 if spec.x_range[0] <= 0 <= spec.x_range[1] else spec.x_range[0]

    if spec.show_grid:
        for value in x_ticks:
            start = _map_point(
                value,
                spec.y_range[0],
                x_range=spec.x_range,
                y_range=spec.y_range,
            )
            end = _map_point(
                value,
                spec.y_range[1],
                x_range=spec.x_range,
                y_range=spec.y_range,
            )
            elements.append(
                DiagramElement(
                    kind="line",
                    x1=start[0],
                    y1=start[1],
                    x2=end[0],
                    y2=end[1],
                    dashed=True,
                    tone="muted",
                )
            )
        for value in y_ticks:
            start = _map_point(
                spec.x_range[0],
                value,
                x_range=spec.x_range,
                y_range=spec.y_range,
            )
            end = _map_point(
                spec.x_range[1],
                value,
                x_range=spec.x_range,
                y_range=spec.y_range,
            )
            elements.append(
                DiagramElement(
                    kind="line",
                    x1=start[0],
                    y1=start[1],
                    x2=end[0],
                    y2=end[1],
                    dashed=True,
                    tone="muted",
                )
            )

    x_start = _map_point(
        spec.x_range[0],
        x_axis_y,
        x_range=spec.x_range,
        y_range=spec.y_range,
    )
    x_end = _map_point(
        spec.x_range[1],
        x_axis_y,
        x_range=spec.x_range,
        y_range=spec.y_range,
    )
    y_start = _map_point(
        y_axis_x,
        spec.y_range[0],
        x_range=spec.x_range,
        y_range=spec.y_range,
    )
    y_end = _map_point(
        y_axis_x,
        spec.y_range[1],
        x_range=spec.x_range,
        y_range=spec.y_range,
    )
    elements.extend(
        (
            DiagramElement(
                kind="line",
                x1=x_start[0],
                y1=x_start[1],
                x2=x_end[0],
                y2=x_end[1],
                arrow_end=True,
                emphasis=True,
            ),
            DiagramElement(
                kind="line",
                x1=y_start[0],
                y1=y_start[1],
                x2=y_end[0],
                y2=y_end[1],
                arrow_end=True,
                emphasis=True,
            ),
            DiagramElement(kind="text", x=CANVAS_WIDTH - 20, y=x_end[1] - 8, text=spec.x_label),
            DiagramElement(kind="text", x=y_end[0] + 8, y=18, text=spec.y_label),
        )
    )

    # Lay out y ticks first. X ticks keep their numerical x alignment but may
    # move below/above the axis to avoid the y tick nearest the intersection.
    label_x = max(2, y_start[0] - 42)
    tick_boxes: list[tuple[float, float, float, float]] = []
    for value in y_ticks:
        _, y = _map_point(
            y_axis_x,
            value,
            x_range=spec.x_range,
            y_range=spec.y_range,
        )
        text = _tick_text(value)
        baseline = y + 5
        elements.append(DiagramElement(kind="text", x=label_x, y=baseline, text=text))
        tick_boxes.append(_text_box(label_x, baseline, text))

    default_x_tick_y = min(CANVAS_HEIGHT - 8, x_start[1] + 22)
    for value in x_ticks:
        x, _ = _map_point(
            value,
            x_axis_y,
            x_range=spec.x_range,
            y_range=spec.y_range,
        )
        text = _tick_text(value)
        text_width = _text_box(0, 0, text)[2]
        text_x = min(max(2.0, x - text_width / 2), CANVAS_WIDTH - text_width - 2)
        candidate_baselines = (
            default_x_tick_y,
            default_x_tick_y + 26,
            x_start[1] - 10,
        )
        candidates = [
            (baseline, _text_box(text_x, baseline, text))
            for baseline in candidate_baselines
            if _box_inside_canvas(_text_box(text_x, baseline, text))
        ]
        chosen = next(
            (
                candidate
                for candidate in candidates
                if not any(_boxes_overlap(candidate[1], other) for other in tick_boxes)
            ),
            None,
        )
        if chosen is None:
            # Never delete a numeric tick. Choose the valid position with the
            # smallest visible overlap if an unusually dense range exhausts
            # the normal placements.
            chosen = min(
                candidates,
                key=lambda candidate: sum(
                    _overlap_area(candidate[1], other) for other in tick_boxes
                ),
            )
        baseline, box = chosen
        elements.append(DiagramElement(kind="text", x=text_x, y=baseline, text=text))
        tick_boxes.append(box)
    return elements


def _curve_elements(
    spec: MathPlotInput,
    curve: MathPlotCurve,
    tone: DiagramTone,
) -> list[DiagramElement]:
    domain = curve.domain or spec.x_range
    domain_start = max(domain[0], spec.x_range[0])
    domain_end = min(domain[1], spec.x_range[1])
    if domain_start >= domain_end:
        raise ValueError("curve domain does not overlap x_range")
    expression = parse_safe_expression(curve.expression, curve.variable)
    variable = Symbol(curve.variable)
    evaluator = lambdify(variable, expression, modules=["numpy"])
    xs = np.linspace(domain_start, domain_end, curve.samples)
    with np.errstate(all="ignore"):
        raw_values = evaluator(xs)
    ys = np.asarray(raw_values)
    if ys.ndim == 0:
        ys = np.full(xs.shape, float(ys))
    try:
        ys = ys.astype(float)
    except (TypeError, ValueError) as error:
        raise ValueError("curve did not evaluate to real numeric values") from error

    y_span = spec.y_range[1] - spec.y_range[0]
    drawable: list[DiagramElement] = []
    current: list[tuple[float, float]] = []
    previous_y: float | None = None

    def append_curve(points: list[tuple[float, float]]) -> None:
        # DiagramElement bounds every polyline to 120 points. Keep one point of
        # overlap so longer sampled curves remain visually continuous.
        for start in range(0, len(points) - 1, 119):
            chunk = points[start : start + 120]
            if len(chunk) >= 2:
                drawable.append(
                    DiagramElement(
                        kind="polyline",
                        points=chunk,
                        dashed=curve.dashed,
                        emphasis=curve.emphasis,
                        tone=tone,
                    )
                )

    for x_value, y_value in zip(xs, ys, strict=True):
        finite = math.isfinite(float(y_value))
        visible = spec.y_range[0] <= float(y_value) <= spec.y_range[1]
        continuous = previous_y is None or abs(float(y_value) - previous_y) <= y_span * 0.75
        if finite and visible and continuous:
            current.append(
                _map_point(
                    float(x_value),
                    float(y_value),
                    x_range=spec.x_range,
                    y_range=spec.y_range,
                )
            )
        else:
            if len(current) >= 2:
                append_curve(current)
            current = []
        previous_y = float(y_value) if finite else None
    if len(current) >= 2:
        append_curve(current)
    if not drawable:
        raise ValueError(f"curve {curve.expression!r} has no visible points in the plot range")
    return drawable


def _point_label_position(
    x: float,
    y: float,
    text: str,
    occupied: list[tuple[float, float, float, float]],
) -> tuple[float, float]:
    origin_box = _text_box(0, 0, text)
    width = origin_box[2] - origin_box[0]
    top_offset = -origin_box[1]
    bottom_offset = origin_box[3]
    above_y = y - 8 - bottom_offset
    below_y = y + 8 + top_offset
    candidates = (
        (x + 8, above_y),
        (x + 8, below_y),
        (x - 8 - width, above_y),
        (x - 8 - width, below_y),
        (x - width / 2, y - 14 - bottom_offset),
        (x - width / 2, y + 14 + top_offset),
    )
    valid_candidates = [
        (candidate_x, candidate_y, _text_box(candidate_x, candidate_y, text))
        for candidate_x, candidate_y in candidates
        if _box_inside_canvas(_text_box(candidate_x, candidate_y, text))
    ]
    for candidate_x, candidate_y, box in valid_candidates:
        if not any(_boxes_overlap(box, other) for other in occupied):
            occupied.append(box)
            return candidate_x, candidate_y
    if valid_candidates:
        candidate_x, candidate_y, box = min(
            valid_candidates,
            key=lambda candidate: sum(_overlap_area(candidate[2], other) for other in occupied),
        )
        occupied.append(box)
        return candidate_x, candidate_y
    fallback_x = min(max(2.0, x + 8), CANVAS_WIDTH - width - 2)
    fallback_y = min(
        max(top_offset + 2, above_y),
        CANVAS_HEIGHT - bottom_offset - 2,
    )
    occupied.append(_text_box(fallback_x, fallback_y, text))
    return fallback_x, fallback_y


def _occupied_text_box(element: DiagramElement) -> tuple[float, float, float, float] | None:
    if element.kind != "text" or element.x is None or element.y is None or not element.text:
        return None
    return _text_box(element.x, element.y, element.text)


def compile_math_plot(spec: MathPlotInput) -> AnswerDiagram:
    elements = _base_elements(spec)
    legend: list[DiagramLegendItem] = []
    for index, curve in enumerate(spec.curves):
        tone: DiagramTone = (
            CURVE_TONES[index % len(CURVE_TONES)] if curve.tone == "auto" else curve.tone
        )
        elements.extend(_curve_elements(spec, curve, tone))
        if curve.label:
            legend.append(DiagramLegendItem(label=curve.label, tone=tone))
    for segment in spec.segments:
        mapped = [
            _map_point(x, y, x_range=spec.x_range, y_range=spec.y_range) for x, y in segment.points
        ]
        elements.append(
            DiagramElement(
                kind="polyline",
                points=mapped,
                dashed=segment.dashed,
                emphasis=segment.emphasis,
                arrow_start=segment.arrow_start,
                arrow_end=segment.arrow_end,
                tone=segment.tone,
            )
        )
    explicit_labels: list[DiagramElement] = []
    for label in spec.labels:
        x, y = _map_point(
            label.x,
            label.y,
            x_range=spec.x_range,
            y_range=spec.y_range,
        )
        explicit_labels.append(
            DiagramElement(kind="text", x=x, y=y, text=label.text, tone=label.tone)
        )
    occupied_labels = [
        box
        for element in (*elements, *explicit_labels)
        if (box := _occupied_text_box(element)) is not None
    ]
    for point in spec.points:
        x, y = _map_point(
            point.x,
            point.y,
            x_range=spec.x_range,
            y_range=spec.y_range,
        )
        elements.append(
            DiagramElement(
                kind="point",
                x=x,
                y=y,
                emphasis=point.emphasis,
                tone=point.tone,
            )
        )
        if point.label:
            label_x, label_y = _point_label_position(
                x,
                y,
                point.label,
                occupied_labels,
            )
            elements.append(
                DiagramElement(
                    kind="text",
                    x=label_x,
                    y=label_y,
                    text=point.label,
                    tone=point.tone,
                )
            )
    elements.extend(explicit_labels)
    return AnswerDiagram(
        answer_anchor=spec.answer_anchor,
        title=spec.title,
        caption=spec.caption,
        tool_name="math_plot",
        view_box=(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT),
        elements=elements,
        legend=legend,
    )


class MathPlotTool:
    name = "math_plot"

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def create_math_plot(**kwargs: object) -> str:
            """Compile a high-level mathematical plot into a safe vector answer artifact."""

            spec = MathPlotInput.model_validate(kwargs)
            diagram = compile_math_plot(spec)
            overlay_mode = mathematics_source_plot_overlay_mode(context.task.question)
            if overlay_mode is not None:
                try:
                    diagram = compile_paper_plot_overlay(
                        spec,
                        diagram,
                        context.task.question_images,
                        context.task.question,
                        overlay_mode,
                        base_element_count=len(_base_elements(spec)),
                    )
                except PlotCalibrationError as error:
                    if overlay_mode != "blank_axes":
                        raise
                    fallback_note = (
                        "原卷坐标轴未能通过自动校准；以下为按相同数学范围生成的独立精确矢量图。"
                    )
                    diagram = diagram.model_copy(
                        update={
                            "caption": " ".join(
                                part for part in (diagram.caption, fallback_note) if part
                            )
                        }
                    )
                    calibration_failure = str(error)
                else:
                    calibration_failure = ""
            else:
                calibration_failure = ""
            diagram = context.add_diagram(diagram)
            canvas_description = (
                "a calibrated original-paper background"
                if diagram.source
                else "a standalone canvas"
            )
            result = (
                f"Plot '{diagram.title}' accepted with {len(spec.curves)} curves, "
                f"{len(diagram.elements)} rendered elements, and "
                f"{canvas_description}. It is anchored to answer "
                f"{diagram.answer_anchor!r} as {diagram.artifact_id}."
            )
            if calibration_failure:
                result += (
                    " Original-paper calibration was unavailable, so a mathematically "
                    f"equivalent standalone vector plot was used ({calibration_failure})."
                )
            return result

        return FunctionTool.from_defaults(
            async_fn=create_math_plot,
            name=self.name,
            fn_schema=MathPlotInput,
            description=(
                "Create function graphs, coordinate plots, cobweb/staircase diagrams, and "
                "statistical line plots from high-level mathematical coordinates. The server "
                "uses bounded SymPy + NumPy evaluation and emits a validated vector artifact. "
                "Prefer this over math_diagram for anything on coordinate axes. Use one call "
                "containing all curves, construction segments, points, and labels. Call only "
                "when the exam question explicitly requires a drawn/visual answer. When the "
                "question requires drawing on supplied axes, a figure, or a grid, the tool "
                "automatically detects the trusted paper figure and overlays deterministic "
                "vectors. If blank axes cannot be calibrated safely, it falls back to a "
                "mathematically equivalent standalone vector plot; it never replaces an exact "
                "coordinate answer with image generation."
            ),
        )
