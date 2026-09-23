from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class StrategyRequest(StrategyModel):
    target_score: float = Field(gt=0, le=1000)
    score_tolerance: float = Field(default=5, ge=0, le=50)
    study_budget_minutes: int = Field(gt=0, le=100_000)
    exam_budget_minutes: int = Field(gt=0, le=1440)
    reserve_minutes: int = Field(default=10, ge=0, le=120)
    preparation: str = Field(default="基础概念已接触，但尚未系统练习本卷题型。", max_length=2000)

    @model_validator(mode="after")
    def reserve_fits(self) -> StrategyRequest:
        if self.reserve_minutes >= self.exam_budget_minutes:
            raise ValueError("检查预留时间必须小于考试时长")
        return self


class StrategySkill(StrategyModel):
    code: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    study_minutes: int = Field(ge=0, le=10_000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    learning_goal: str = Field(min_length=1, max_length=600)


class StrategyOption(StrategyModel):
    id: str = Field(min_length=1, max_length=100)
    question_number: str
    subpart: str
    mode: Literal["full", "partial"]
    includes_required_artifact: bool = True
    expected_marks: float = Field(gt=0, le=100)
    lower_marks: float = Field(ge=0, le=100)
    upper_marks: float = Field(gt=0, le=100)
    exam_minutes: int = Field(gt=0, le=240)
    practice_minutes: int = Field(ge=0, le=10_000)
    skills: list[str] = Field(min_length=1, max_length=30)
    requires_options: list[str] = Field(default_factory=list, max_length=30)
    approach: str = Field(min_length=1, max_length=1000)
    stop_before: str = Field(default="", max_length=600)
    rationale: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def ordered_marks(self) -> StrategyOption:
        if not self.lower_marks <= self.expected_marks <= self.upper_marks:
            raise ValueError("得分估计必须满足下界 ≤ 预期 ≤ 上界")
        return self


class StrategyAnalysis(StrategyModel):
    skills: list[StrategySkill] = Field(min_length=1, max_length=150)
    options: list[StrategyOption] = Field(min_length=1, max_length=300)
    assumptions: list[str] = Field(min_length=1, max_length=20)


class StrategyRoute(StrategyModel):
    name: Literal["balanced", "less_study", "faster_exam"]
    option_ids: list[str]
    skill_codes: list[str]
    study_minutes: int
    exam_minutes: int
    expected_marks: float
    lower_marks: float
    upper_marks: float


class StrategyPlan(StrategyModel):
    version: Literal["target-score-v1", "target-score-v2"] = "target-score-v2"
    input_digest: str
    analysis_model: str | None = None
    request: StrategyRequest
    total_marks: int
    status: Literal["feasible_estimate", "target_not_reached"]
    analysis: StrategyAnalysis
    selected: StrategyRoute
    alternatives: list[StrategyRoute]
    skipped_subparts: list[str]
    warnings: list[str]
    search_truncated: bool
