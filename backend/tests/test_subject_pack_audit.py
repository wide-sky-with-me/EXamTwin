from __future__ import annotations

from pathlib import Path

from examtwin.services.subject_pack_audit import audit_subject_pack_pdf
from examtwin.subjects import get_subject_pack

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_economics_subject_pack_matches_real_official_specification() -> None:
    subject_pack = get_subject_pack("oxfordaqa-economics-9640")
    result = audit_subject_pack_pdf(
        subject_pack,
        PROJECT_ROOT / subject_pack.specification_ref,
    )

    assert result["passed"] is True
    assert result["discovered_topics"] == 84
    assert result["mapped_topics"] == 84


def test_economics_subject_pack_parses_real_paper_names_and_syllabus_headings() -> None:
    subject_pack = get_subject_pack("oxfordaqa-economics-9640")

    assert subject_pack.parse_unit("QP-202605-Economics-U4A-Level-AQA-9640.pdf") == "U4"
    assert subject_pack.topic_heading_pattern().match("### 3.3.3.10 Consumer and producer surplus")
