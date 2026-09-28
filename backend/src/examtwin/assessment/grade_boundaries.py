"""Deterministic, exact-session unit grades. Never infer qualification grades."""

import json
import math
from functools import lru_cache
from importlib.resources import files

from examtwin.contracts.grades import GradeLetter, UnitGradeEstimate

PASS_GRADES: tuple[GradeLetter, ...] = ("A", "B", "C", "D", "E")


@lru_cache(maxsize=1)
def boundary_catalog() -> dict[str, dict]:
    rows = json.loads(files("examtwin.assessment").joinpath("grade_boundaries.json").read_text())
    catalog = {}
    for row in rows:
        thresholds = row["thresholds"]
        values = list(thresholds.values())
        if (
            list(thresholds) != list("ABCDE")
            or not all(math.isfinite(v) for v in values)
            or not row["max_marks"] >= values[0] > values[1] > values[2] > values[3] > values[4] > 0
            or row["pair_key"] in catalog
        ):
            raise ValueError("Invalid or duplicate official grade boundaries")
        catalog[row["pair_key"]] = row
    return catalog


def estimate_unit_grade(
    *,
    subject_code: str,
    pair_key: str,
    rubric_pair_key: str,
    awarded: float,
    available: float,
    complete: bool,
    pending_review: bool,
    deferred: bool = False,
) -> UnitGradeEstimate:
    def unavailable(reason: str) -> UnitGradeEstimate:
        return UnitGradeEstimate(status="unavailable", explanation=reason)

    if not complete:
        return unavailable("整卷评分尚未完成，暂不估计等级。")
    if deferred:
        return unavailable("存在暂缓授分的证据，零分占位不能用于等级估计。")
    if not pair_key or pair_key != rubric_pair_key or pair_key.split(":")[0] != subject_code:
        return unavailable("试卷与评分规则缺少一致的考试身份，暂不估计等级。")
    row = boundary_catalog().get(pair_key)
    if row is None:
        return unavailable("尚未收录该科目、年份、考季及单元的官方分数线。")
    if (
        not math.isfinite(awarded)
        or not math.isfinite(available)
        or available != row["max_marks"]
        or not 0 <= awarded <= available
    ):
        return unavailable("分值无效或整卷满分与官方单元不一致，暂不估计等级。")
    thresholds = row["thresholds"]
    grade: GradeLetter = "U"
    for candidate in PASS_GRADES:
        if awarded >= thresholds[candidate]:
            grade = candidate
            break
    above = [(g, threshold) for g, threshold in thresholds.items() if threshold > awarded]
    next_grade, next_threshold = above[-1] if above else (None, None)
    return UnitGradeEstimate(
        status="provisional" if pending_review else "reviewed",
        grade=grade,
        explanation=(
            "根据待复核分数换算的暂定单元等级。"
            if pending_review
            else "根据已复核分数换算的单元等级。"
        )
        + "仅适用于本次单元试卷，不代表完整 AS/A-level 资格等级或正式考试结果。",
        pair_key=pair_key,
        unit_code=row["unit_code"],
        source_url=row["source_url"],
        source_page=row["source_page"],
        thresholds=thresholds,
        next_grade=next_grade,
        marks_to_next_grade=round(next_threshold - awarded, 4) if next_threshold else None,
    )
