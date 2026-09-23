from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest
from examtwin.assessment.paper_export import inspect_answer_layout
from examtwin.contracts.papers import PaperJobQuestion


def _question(position: int, number: str, label: str = "whole") -> PaperJobQuestion:
    return PaperJobQuestion(
        position=position,
        number=number,
        status="completed",
        question_markdown="Question",
        source_pages=[1],
        answer_markdown="Answer",
        answer_requirements=[{"label": label}],
    )


def _paper(path: Path, *, rotation: int = 0, obstacle: bool = False) -> bytes:
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=800)
        page.insert_text((50, 65), "1 (a) Explain the first result.")
        for y in range(100, 221, 24):
            page.draw_line((90, y), (510, y))
        page.insert_text((50, 320), "2 Explain the second result.")
        for y in range(350, 471, 24):
            page.draw_line((90, y), (510, y))
        if obstacle:
            page.insert_text((110, 170), "DO NOT OVERWRITE THIS STEM")
        page.set_rotation(rotation)
        document.save(path)
    return path.read_bytes()


def test_layout_assigns_each_region_to_exact_question_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    before = _paper(source)
    layout = inspect_answer_layout(source, [_question(0, "1", "(a)"), _question(1, "2")])
    assert [(r.question_position, r.answer_anchor) for r in layout.regions] == [
        (0, "(a)"),
        (1, "whole"),
    ]
    assert layout.regions[0].y > 100
    assert layout.regions[0].y + layout.regions[0].height < 221
    assert source.read_bytes() == before
    assert layout.source_sha256 == hashlib.sha256(before).hexdigest()


def test_layout_rejects_space_containing_printed_content(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source, obstacle=True)
    result = inspect_answer_layout(source, [_question(0, "1", "(a)"), _question(1, "2")])
    assert [r.question_position for r in result.regions] == [1]


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_layout_uses_displayed_page_coordinates(tmp_path: Path, rotation: int) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source, rotation=rotation)
    layout = inspect_answer_layout(source, [_question(0, "1", "(a)"), _question(1, "2")])
    assert len(layout.regions) == 2
    page = layout.pages[0]
    assert page.width == (800 if rotation in {90, 270} else 600)
    for region in layout.regions:
        assert 0 <= region.x < region.x + region.width <= page.width
        assert 0 <= region.y < region.y + region.height <= page.height


def test_unattributed_and_scan_only_pages_require_manual_selection(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source)
    questions = [_question(0, "7", "(a)"), _question(1, "8", "(b)")]
    assert not inspect_answer_layout(source, questions).regions
    with pymupdf.open(source) as original:
        image = original[0].get_pixmap().tobytes("png")
    with pymupdf.open() as scanned:
        page = scanned.new_page(width=600, height=800)
        page.insert_image(page.rect, stream=image)
        scanned.save(tmp_path / "scan.pdf")
    result = inspect_answer_layout(tmp_path / "scan.pdf", [_question(0, "1")])
    assert not result.regions
    assert any("框选" in message for message in result.warnings)


def test_layout_does_not_use_other_questions_source_pages(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source)
    question = _question(0, "1", "(a)").model_copy(update={"source_pages": [2]})
    assert not inspect_answer_layout(source, [question]).regions


def test_later_unrelated_question_does_not_inherit_previous_identity(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source)
    result = inspect_answer_layout(source, [_question(0, "1", "(a)")])
    assert len(result.regions) == 1
    assert result.regions[0].y < 220


def test_numeric_formula_near_heading_is_not_another_question(tmp_path: Path) -> None:
    source = tmp_path / "paper.pdf"
    _paper(source)
    with pymupdf.open(source) as pdf:
        pdf[0].insert_text((145, 65), "5 2")
        pdf.save(tmp_path / "with-formula.pdf")
    result = inspect_answer_layout(tmp_path / "with-formula.pdf", [_question(0, "1", "(a)")])
    assert len(result.regions) == 1
