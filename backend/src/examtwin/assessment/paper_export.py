"""Locate ruled answer spaces without guessing blank-page or figure semantics.

Coordinates are points in the displayed (rotated, cropped) page, from its top left.
Only uniquely attributed groups of ruled lines are proposed. Other areas remain
an explicit manual choice in the preview. This never changes answers or sources.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, cast

import pymupdf

from examtwin.contracts.paper_export import (
    PaperAnswerRegion,
    PaperExportLayout,
    PaperExportPage,
)
from examtwin.contracts.papers import PaperJobQuestion


def _anchor(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _lines(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    contents = cast(dict[str, Any], page.get_text("dict"))
    return sorted(
        (
            (pymupdf.Rect(line["bbox"]), text)
            for block in contents["blocks"]
            for line in block.get("lines", [])
            if (text := "".join(span["text"] for span in line["spans"]).strip())
        ),
        key=lambda item: (item[0].y0, item[0].x0),
    )


def _ruled_spaces(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Accept repeated, wide horizontal rules; exclude tables and text regions."""
    rules: list[pymupdf.Rect] = []
    obstacles: list[pymupdf.Rect] = []
    for drawing in page.get_drawings():
        rect = pymupdf.Rect(drawing["rect"])
        if rect.height <= 1.5 and rect.width >= 180:
            rules.append(rect)
        elif rect.width > 2 and rect.height > 2:
            # Page borders do not enclose answer content in this collision test.
            if rect.height < page.cropbox.height * 0.8:
                obstacles.append(rect)
    text_lines = _lines(page)
    for rect, text in text_lines:
        if re.fullmatch(r"[.·…_\s]{15,}", text) and rect.width >= 180:
            rules.append(pymupdf.Rect(rect.x0, rect.y1 - 2, rect.x1, rect.y1))
        else:
            obstacles.append(rect)
    for image in page.get_image_info():
        obstacles.append(pymupdf.Rect(image["bbox"]))
    groups: list[list[pymupdf.Rect]] = []
    for rect in sorted(rules, key=lambda r: (r.y0, r.x0)):
        if groups:
            last = groups[-1][-1]
            if abs(rect.y0 - last.y0) < 2:
                continue
            if (
                12 <= rect.y0 - last.y0 <= 36
                and abs(rect.x0 - last.x0) < 4
                and abs(rect.x1 - last.x1) < 4
            ):
                groups[-1].append(rect)
                continue
        groups.append([rect])
    spaces = []
    for group in groups:
        if len(group) < 2:
            continue
        first, last = group[0], group[-1]
        # Start just after the first line: never extrapolate upwards into a stem.
        space = pymupdf.Rect(first.x0 + 4, first.y1 + 2, first.x1 - 4, last.y0 - 2)
        if space.height < 20 or any(space.intersects(box) for box in obstacles):
            continue
        spaces.append(space)
    return spaces


def inspect_answer_layout(source: Path, questions: list[PaperJobQuestion]) -> PaperExportLayout:
    result = PaperExportLayout(
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), pages=[]
    )
    with pymupdf.open(source) as document:
        if document.needs_pass:
            raise ValueError("加密试卷需要先解密才能导出作答 PDF")
        if not 1 <= document.page_count <= 500:
            raise ValueError("原卷 PDF 页数必须在 1–500 页之间")
        for index in range(document.page_count):
            page = document[index]
            result.pages.append(
                PaperExportPage(
                    page_number=index + 1, width=page.rect.width, height=page.rect.height
                )
            )
            candidates = [q for q in questions if index + 1 in q.source_pages]
            if not candidates:
                continue
            lines = _lines(page)
            markers: list[tuple[float, int, str]] = []
            for box, text in lines:
                # Only the question-number gutter, not numeric expressions in the stem.
                if box.x0 > page.cropbox.width * 0.16:
                    continue
                compact = _anchor(text)
                printed_number = re.match(r"^(\d{1,3})(?=\s|[.(])", text)
                if printed_number and not any(
                    (q.number.lstrip("0") or "0") == (printed_number[1].lstrip("0") or "0")
                    for q in candidates
                ):
                    # An unrelated printed question ends the preceding question's area.
                    markers.append((box.y0, -1, "whole"))
                for question in candidates:
                    number = re.escape(question.number.lstrip("0") or "0")
                    match = re.match(rf"^0?{number}(?!\d)((?:\([a-zivx]+\))*)", compact)
                    if match:
                        label = match[1] or "whole"
                        markers.append((box.y0, question.position, label))
                    for requirement in question.answer_requirements:
                        label = _anchor(requirement.label)
                        # Decimal question numbering is used by some subject packs.
                        if label.startswith(".") and compact.startswith(
                            _anchor(question.number) + label
                        ):
                            markers.append((box.y0, question.position, requirement.label))
            for space in _ruled_spaces(page):
                preceding = [m for m in markers if m[0] < space.y0]
                if preceding:
                    last_y = max(m[0] for m in preceding)
                    matches = {(pos, label) for y, pos, label in preceding if abs(y - last_y) < 2}
                    if len(matches) != 1:
                        continue
                    position, label = next(iter(matches))
                    if position < 0:
                        continue
                elif len(candidates) == 1 and all(
                    r.label == "whole" for r in candidates[0].answer_requirements
                ):
                    position, label = candidates[0].position, "whole"
                else:
                    continue
                question = next(q for q in candidates if q.position == position)
                allowed = {_anchor(r.label) for r in question.answer_requirements} or {"whole"}
                if _anchor(label) not in allowed:
                    continue
                displayed = space * page.rotation_matrix
                result.regions.append(
                    PaperAnswerRegion(
                        question_position=position,
                        answer_anchor=label,
                        page_number=index + 1,
                        x=displayed.x0,
                        y=displayed.y0,
                        width=displayed.width,
                        height=displayed.height,
                    )
                )
    if not result.regions:
        result.warnings.append("未找到能可靠归属的答题横线，请在原卷上框选答题区。")
    result.warnings.append("自动位置需在预览中核对；填空、表格、选择题及扫描卷可手动框选。")
    return result
