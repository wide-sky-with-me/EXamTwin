from pathlib import Path

from examtwin.services.inventory import classify_source, parse_exam_identity
from examtwin.subjects import get_subject_pack

OXFORDAQA_MATHEMATICS_9660 = get_subject_pack("oxfordaqa-mathematics-9660")


def test_classifies_hyphenated_mark_scheme() -> None:
    path = Path("data/5.AQA/2022 January/a-level-maths-unit-3-mark-scheme-jan22.pdf")
    assert classify_source(path) == "mark_scheme"
    identity = parse_exam_identity(path, "mark_scheme", OXFORDAQA_MATHEMATICS_9660)
    assert identity == {
        "exam_year": 2022,
        "exam_session": "JAN",
        "unit_code": "P2",
        "pair_key": "9660:2022:JAN:P2",
        "identity_status": "complete",
        "identity_error": None,
    }


def test_strict_identity_for_vendor_filename() -> None:
    path = Path("A-Level-AQA数学-国际卷QP-202401-Mathematics-UPSM1-AS.pdf")
    assert classify_source(path) == "question_paper"
    identity = parse_exam_identity(path, "question_paper", OXFORDAQA_MATHEMATICS_9660)
    assert identity["pair_key"] == "9660:2024:JAN:PSM1"


def test_non_exam_source_has_no_pair_key() -> None:
    path = Path("International AS Level Mathematics Student Book.pdf")
    source_type = classify_source(Path("教材") / path)
    assert source_type == "textbook"
    assert parse_exam_identity(path, source_type, OXFORDAQA_MATHEMATICS_9660)["pair_key"] is None
