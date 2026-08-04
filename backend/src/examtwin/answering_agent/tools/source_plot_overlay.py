from __future__ import annotations

import io
import math
import re
from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image

from examtwin.answering_agent.contracts import QuestionImage
from examtwin.schemas.evidence import (
    AnswerDiagram,
    DiagramElement,
    DiagramLegendItem,
    PaperDiagramSource,
)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_TRAPEZIA_COUNT = re.compile(
    r"\b(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
    r"\s+trapez(?:ium|ia|oid)s?\b",
    re.IGNORECASE,
)


class PlotCalibrationError(ValueError):
    """The trusted page does not contain a safely calibratable requested figure."""


def _decode(image: QuestionImage) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(image.content)) as source:
            source.load()
            gray = source.convert("L")
    except OSError as error:
        raise PlotCalibrationError("trusted question page is not a readable image") from error
    width, height = gray.size
    if width < 64 or height < 64 or width > 10_000 or height > 10_000:
        raise PlotCalibrationError("trusted question page dimensions are outside safe bounds")
    return np.asarray(gray, dtype=np.uint8)


def _group_centers(values: np.ndarray | list[int], *, gap: int = 2) -> list[int]:
    if len(values) == 0:
        return []
    ordered = [int(value) for value in values]
    groups: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value > previous + gap:
            groups.append((start, previous))
            start = value
        previous = value
    groups.append((start, previous))
    return [round((start + end) / 2) for start, end in groups]


def _span_at_anchor(mask: np.ndarray, anchor: int, *, max_gap: int = 2) -> tuple[int, int]:
    values = np.flatnonzero(mask)
    if len(values) == 0:
        raise PlotCalibrationError("calibration line has no visible pixels")
    groups: list[tuple[int, int]] = []
    start = previous = int(values[0])
    for raw in values[1:]:
        value = int(raw)
        if value > previous + max_gap + 1:
            groups.append((start, previous))
            start = value
        previous = value
    groups.append((start, previous))
    near = [group for group in groups if group[0] - 2 <= anchor <= group[1] + 2]
    if not near:
        raise PlotCalibrationError("perpendicular calibration lines do not intersect")
    return max(near, key=lambda group: group[1] - group[0])


def _detect_blank_axes(gray: np.ndarray) -> tuple[int, int, int, int, int, int]:
    height, width = gray.shape
    dark = gray < 195
    x_start, x_end = round(width * 0.12), round(width * 0.88)
    y_start, y_end = round(height * 0.12), round(height * 0.78)
    row_counts = dark[:, x_start:x_end].sum(axis=1)
    column_counts = dark[y_start:y_end, :].sum(axis=0)
    row_candidates = _group_centers(
        np.flatnonzero(
            (row_counts >= width * 0.28)
            & (row_counts <= width * 0.72)
            & (np.arange(height) >= y_start)
            & (np.arange(height) <= y_end)
        )
    )
    column_candidates = _group_centers(
        np.flatnonzero(
            (column_counts >= height * 0.18)
            & (np.arange(width) >= round(width * 0.15))
            & (np.arange(width) <= round(width * 0.85))
        )
    )
    best: tuple[float, tuple[int, int, int, int, int, int]] | None = None
    for axis_y in row_candidates:
        for axis_x in column_candidates:
            if gray[axis_y, axis_x] > 225:
                continue
            try:
                left, right = _span_at_anchor(dark[axis_y], axis_x)
                top, bottom = _span_at_anchor(dark[:, axis_x], axis_y)
            except PlotCalibrationError:
                continue
            horizontal = right - left
            vertical = bottom - top
            if horizontal < width * 0.28 or vertical < height * 0.18:
                continue
            score = horizontal * vertical
            candidate = (left, right, top, bottom, axis_x, axis_y)
            if best is None or score > best[0]:
                best = (score, candidate)
    if best is None:
        raise PlotCalibrationError("no intersecting blank coordinate axes were detected")
    return best[1]


def _regular_sequence(points: list[int]) -> list[int]:
    """Select the longest nearly equally spaced sequence of grid lines."""

    best: list[int] = []
    for start_index, start in enumerate(points):
        sequence = [start]
        steps: list[int] = []
        for point in points[start_index + 1 :]:
            step = point - sequence[-1]
            if step < 18 or step > 100:
                break
            if steps and abs(step - float(np.median(steps))) > 4:
                break
            steps.append(step)
            sequence.append(point)
        if len(sequence) > len(best):
            best = sequence
    if len(best) < 6:
        raise PlotCalibrationError("no regular coordinate grid was detected")
    return best


def _detect_grid(gray: np.ndarray) -> tuple[list[int], list[int]]:
    height, width = gray.shape
    grid = gray < 225
    y_start, y_end = round(height * 0.10), round(height * 0.80)
    column_counts = grid[y_start:y_end].sum(axis=0)
    candidates = _group_centers(
        np.flatnonzero(
            (column_counts >= height * 0.25)
            & (np.arange(width) >= round(width * 0.15))
            & (np.arange(width) <= round(width * 0.85))
        )
    )
    verticals = _regular_sequence(candidates)
    left, right = verticals[0], verticals[-1]
    row_counts = grid[:, left : right + 1].sum(axis=1)
    horizontals = _group_centers(
        np.flatnonzero(
            (row_counts >= (right - left) * 0.72)
            & (np.arange(height) >= y_start)
            & (np.arange(height) <= y_end)
        )
    )
    horizontals = _regular_sequence(horizontals)
    return verticals, horizontals


def _strip_count(question: str) -> int:
    match = _TRAPEZIA_COUNT.search(question)
    if match is None:
        raise PlotCalibrationError("the requested number of trapezia is not explicit")
    raw = match.group("count").casefold()
    count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    if count < 1 or count > 20:
        raise PlotCalibrationError("the requested number of trapezia is outside safe bounds")
    return count


def _numeric_label_score(gray: np.ndarray, x: int, baseline_y: int) -> int:
    height, width = gray.shape
    left, right = max(0, x - 14), min(width, x + 15)
    top, bottom = min(height, baseline_y + 3), min(height, baseline_y + 48)
    if top >= bottom:
        return 0
    return int((gray[top:bottom, left:right] < 145).sum())


def _curve_y(gray: np.ndarray, x: int, top: int, bottom: int, *, first: bool) -> float:
    height, width = gray.shape
    columns = range(x + 4, min(width, x + 11)) if first else range(max(0, x - 1), min(width, x + 2))
    candidates: list[tuple[int, float]] = []
    for column in columns:
        values = np.flatnonzero(gray[top + 8 : bottom - 8, column] < 110) + top + 8
        if len(values) == 0:
            continue
        groups: list[list[int]] = []
        current = [int(values[0])]
        for raw in values[1:]:
            value = int(raw)
            if value > current[-1] + 2:
                groups.append(current)
                current = [value]
            else:
                current.append(value)
        groups.append(current)
        for group in groups:
            if len(group) > max(48, (bottom - top) * 0.12):
                continue
            candidates.append((len(group), float(np.median(group))))
    if not candidates:
        raise PlotCalibrationError("the printed curve could not be sampled at an ordinate")
    if first:
        return max(value for _size, value in candidates)
    largest = max(size for size, _value in candidates)
    return float(np.median([value for size, value in candidates if size == largest]))


def _clamp_crop(
    left: float,
    top: float,
    right: float,
    bottom: float,
    *,
    width: int,
    height: int,
) -> tuple[float, float, float, float]:
    crop_left = max(0.0, math.floor(left))
    crop_top = max(0.0, math.floor(top))
    crop_right = min(float(width), math.ceil(right))
    crop_bottom = min(float(height), math.ceil(bottom))
    return crop_left, crop_top, crop_right - crop_left, crop_bottom - crop_top


def _transform_element(
    element: DiagramElement,
    *,
    source_rect: tuple[float, float, float, float],
    target_rect: tuple[float, float, float, float],
) -> DiagramElement:
    source_left, source_top, source_right, source_bottom = source_rect
    target_left, target_top, target_right, target_bottom = target_rect
    scale_x = (target_right - target_left) / (source_right - source_left)
    scale_y = (target_bottom - target_top) / (source_bottom - source_top)

    def map_x(value: float | None) -> float | None:
        return None if value is None else target_left + (value - source_left) * scale_x

    def map_y(value: float | None) -> float | None:
        return None if value is None else target_top + (value - source_top) * scale_y

    if element.kind == "path":
        raise PlotCalibrationError("paper overlay does not accept opaque SVG paths")
    update: dict[str, Any] = {
        "x1": map_x(element.x1),
        "x2": map_x(element.x2),
        "x": map_x(element.x),
        "cx": map_x(element.cx),
        "y1": map_y(element.y1),
        "y2": map_y(element.y2),
        "y": map_y(element.y),
        "cy": map_y(element.cy),
        "points": [(map_x(x) or 0.0, map_y(y) or 0.0) for x, y in element.points],
    }
    if element.r is not None:
        update["r"] = element.r * min(abs(scale_x), abs(scale_y))
    if element.rx is not None:
        update["rx"] = element.rx * abs(scale_x)
    if element.ry is not None:
        update["ry"] = element.ry * abs(scale_y)
    return element.model_copy(update=update)


def _blank_axes_overlay(
    spec: Any,
    standalone: AnswerDiagram,
    image: QuestionImage,
    gray: np.ndarray,
    *,
    base_element_count: int,
) -> AnswerDiagram:
    left, right, top, bottom, origin_x, origin_y = _detect_blank_axes(gray)
    x_min, x_max = spec.x_range
    y_min, y_max = spec.y_range
    if not (x_min < 0 < x_max and y_min < 0 < y_max):
        raise PlotCalibrationError("blank source axes require x/y ranges that cross zero")
    x_scale = min((origin_x - left) / -x_min, (right - origin_x) / x_max) * 0.92
    y_scale = min((origin_y - top) / y_max, (bottom - origin_y) / -y_min) * 0.92
    target_rect = (
        origin_x + x_min * x_scale,
        origin_y - y_max * y_scale,
        origin_x + x_max * x_scale,
        origin_y - y_min * y_scale,
    )
    source_rect = (62.0, 22.0, 576.0, 312.0)
    elements = [
        _transform_element(element, source_rect=source_rect, target_rect=target_rect)
        for element in standalone.elements[base_element_count:]
    ]
    if not elements:
        raise PlotCalibrationError("the overlay contains no mathematical construction")
    height, width = gray.shape
    crop = _clamp_crop(
        left - 32,
        top - 28,
        right + 32,
        bottom + 34,
        width=width,
        height=height,
    )
    return standalone.model_copy(
        update={
            "caption": (f"{standalone.caption} " if standalone.caption else "")
            + (
                "Vector construction calibrated to the original axes on paper page "
                f"{image.page_number}."
            ),
            "view_box": crop,
            "elements": elements,
            "source": PaperDiagramSource(
                page_number=image.page_number,
                width=width,
                height=height,
                calibration="blank_axes",
            ),
        }
    )


def _trapezia_overlay(
    standalone: AnswerDiagram,
    image: QuestionImage,
    gray: np.ndarray,
    question: str,
) -> AnswerDiagram:
    verticals, horizontals = _detect_grid(gray)
    grid_top, axis_y = horizontals[0], horizontals[-1]
    labelled = [x for x in verticals if _numeric_label_score(gray, x, axis_y) >= 24]
    if len(labelled) < 2:
        raise PlotCalibrationError("the source graph endpoint labels could not be calibrated")
    origin_x = verticals[0]
    end_x = max(x for x in labelled if x > origin_x)
    count = _strip_count(question)
    spacing = (end_x - origin_x) / count
    ordinates: list[tuple[float, float]] = []
    regular_spacing = float(np.median(np.diff(verticals)))
    for index in range(count + 1):
        expected = origin_x + spacing * index
        nearest = min(verticals, key=lambda value: abs(value - expected))
        x = float(nearest if abs(nearest - expected) <= regular_spacing * 0.25 else expected)
        y = _curve_y(gray, round(x), grid_top, axis_y, first=index == 0)
        ordinates.append((x, y))
    elements: list[DiagramElement] = []
    for x, y in ordinates:
        elements.append(
            DiagramElement(
                kind="line",
                x1=x,
                y1=float(axis_y),
                x2=x,
                y2=y,
                emphasis=True,
                tone="primary",
            )
        )
    for start, end in zip(ordinates, ordinates[1:], strict=False):
        elements.append(
            DiagramElement(
                kind="line",
                x1=start[0],
                y1=start[1],
                x2=end[0],
                y2=end[1],
                emphasis=True,
                tone="primary",
            )
        )
    height, width = gray.shape
    crop = _clamp_crop(
        origin_x - 34,
        grid_top - 36,
        end_x + 64,
        axis_y + 58,
        width=width,
        height=height,
    )
    return AnswerDiagram(
        title=standalone.title,
        caption=(
            f"{count} trapezia snapped to the printed curve and x-axis on "
            f"the original paper page {image.page_number}."
        ),
        tool_name="math_plot",
        view_box=crop,
        elements=elements,
        legend=[DiagramLegendItem(label=f"{count} calibrated trapezia", tone="primary")],
        source=PaperDiagramSource(
            page_number=image.page_number,
            width=width,
            height=height,
            calibration="existing_curve_grid",
        ),
    )


def compile_paper_plot_overlay(
    spec: Any,
    standalone: AnswerDiagram,
    images: Sequence[QuestionImage],
    question: str,
    mode: str,
    *,
    base_element_count: int,
) -> AnswerDiagram:
    if not images:
        raise PlotCalibrationError("paper-backed drawing requires trusted question images")
    failures: list[str] = []
    for image in images:
        try:
            gray = _decode(image)
            if mode == "blank_axes":
                return _blank_axes_overlay(
                    spec,
                    standalone,
                    image,
                    gray,
                    base_element_count=base_element_count,
                )
            if mode == "existing_curve_grid":
                return _trapezia_overlay(standalone, image, gray, question)
            raise PlotCalibrationError(f"unsupported paper overlay mode: {mode}")
        except PlotCalibrationError as error:
            failures.append(f"p.{image.page_number}: {error}")
    raise PlotCalibrationError("; ".join(failures))
