from typing import Literal

from pydantic import Field

from examtwin.contracts.base import SerializedResponse

GradeLetter = Literal["A", "B", "C", "D", "E", "U"]


class UnitGradeEstimate(SerializedResponse):
    status: Literal["unavailable", "provisional", "reviewed"]
    grade: GradeLetter | None = None
    scope: Literal["unit"] = "unit"
    explanation: str
    pair_key: str | None = None
    unit_code: str | None = None
    source_url: str | None = None
    source_page: int | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)
    next_grade: str | None = None
    marks_to_next_grade: float | None = None
