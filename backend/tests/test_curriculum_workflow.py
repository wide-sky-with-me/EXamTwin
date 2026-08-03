from __future__ import annotations

import hashlib
from pathlib import Path

from examtwin.services.curriculum import (
    get_curriculum_extractor,
    validate_curriculum_candidate,
)
from examtwin.subjects import get_subject_pack
from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATH_SYLLABUS_MARKDOWN = PROJECT_ROOT / "var/corpus/md/388f07f872568687e668a2b811858453e57c0aeb.md"


def test_real_9660_markdown_builds_complete_curriculum_without_seed_constants() -> None:
    subject_pack = get_subject_pack("oxfordaqa-mathematics-9660")
    markdown = MATH_SYLLABUS_MARKDOWN.read_text(encoding="utf-8")
    candidate = get_curriculum_extractor(subject_pack).extract(
        markdown,
        subject_pack,
        source_document_id="official-9660-spec",
        source_ref=subject_pack.specification_ref,
        input_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    validation = validate_curriculum_candidate(candidate, subject_pack)

    assert validation.passed is True
    assert validation.metrics == {
        "units": 5,
        "topics": 38,
        "objectives": 183,
        "topics_without_objectives": 0,
    }
    assert {topic.unit_code for topic in candidate.topics} == {
        "P1",
        "PSM1",
        "P2",
        "S2",
        "M2",
    }
    assert candidate.topics[0].code == "P1.1"
    assert candidate.objectives[0].code == "P1.1.O01"


def test_same_extractor_builds_economics_candidate_from_real_specification_text() -> None:
    subject_pack = get_subject_pack("oxfordaqa-economics-9640")
    specification = PROJECT_ROOT / subject_pack.specification_ref
    reader = PdfReader(str(specification))
    markdown = "\n".join(
        f"## Page {index}\n{page.extract_text() or ''}"
        for index, page in enumerate(reader.pages, start=1)
    )
    candidate = get_curriculum_extractor(subject_pack).extract(
        markdown,
        subject_pack,
        source_document_id="official-9640-spec",
        source_ref=subject_pack.specification_ref,
        input_hash=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
    validation = validate_curriculum_candidate(candidate, subject_pack)

    assert validation.passed is True
    assert validation.warnings == []
    assert validation.metrics == {
        "units": 4,
        "topics": 84,
        "objectives": 484,
        "topics_without_objectives": 0,
    }
    assert candidate.topics[0].code == "3.1.1.1"
    assert candidate.objectives[0].parent == "3.1.1.1"
