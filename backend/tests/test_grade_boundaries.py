import pytest
from examtwin.assessment.grade_boundaries import boundary_catalog, estimate_unit_grade


def estimate(**changes):
    values = dict(
        subject_code="9660",
        pair_key="9660:2019:JAN:P1",
        rubric_pair_key="9660:2019:JAN:P1",
        awarded=48,
        available=80,
        complete=True,
        pending_review=True,
    )
    values.update(changes)
    return estimate_unit_grade(**values)


@pytest.mark.parametrize("pair,row", boundary_catalog().items())
def test_every_official_threshold_and_just_below(pair, row):
    for index, (grade, threshold) in enumerate(row["thresholds"].items()):
        args = dict(
            subject_code=pair.split(":")[0],
            pair_key=pair,
            rubric_pair_key=pair,
            available=row["max_marks"],
        )
        assert estimate(**args, awarded=threshold).grade == grade
        assert estimate(**args, awarded=threshold - 0.01).grade == "BCDEU"[index]
    assert estimate(**args, awarded=0).grade == "U"
    assert estimate(**args, awarded=row["max_marks"]).grade == "A"


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"deferred": True},
        {"pair_key": ""},
        {"subject_code": "9640"},
        {"rubric_pair_key": "9660:2024:JAN:P1"},
        {"pair_key": "9660:2019:JUN:P1", "rubric_pair_key": "9660:2019:JUN:P1"},
        {"available": 79},
        {"awarded": 81},
        {"awarded": -1},
        {"awarded": float("nan")},
        {"available": float("inf")},
    ],
)
def test_no_grade_from_incomplete_wrong_or_unverifiable_evidence(changes):
    result = estimate(**changes)
    assert result.status == "unavailable"
    assert result.grade is None
    assert result.source_url is None


def test_review_state_and_distance_do_not_change_numeric_score():
    provisional = estimate()
    assert (provisional.grade, provisional.next_grade, provisional.marks_to_next_grade) == (
        "C",
        "B",
        7,
    )
    assert provisional.status == "provisional"
    assert estimate(pending_review=False).status == "reviewed"
    assert estimate(awarded=80).next_grade is None
    assert provisional.source_page == 1
    assert provisional.source_url.startswith("https://www.oxfordaqa.com/")


def test_same_score_can_have_different_unit_grade():
    assert estimate(awarded=60).grade == "B"
    assert (
        estimate(awarded=60, pair_key="9660:2024:JAN:P1", rubric_pair_key="9660:2024:JAN:P1").grade
        == "A"
    )
