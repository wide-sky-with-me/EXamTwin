from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from examtwin.contracts.base import SerializedResponse
from examtwin.contracts.grades import UnitGradeEstimate
from examtwin.contracts.grading import GradeResponse


class RubricCriterionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scoring_mode: Literal["point_based", "levels_based"] | None = None
    mark_type: str | None = None
    max_marks: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1)
    dependencies: list[str] | None = None
    alternatives: list[str] | None = None
    accuracy_requirement: str | None = None
    units: list[str] | None = None
    follow_through_policy: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_excerpt: str | None = None

    @model_validator(mode="after")
    def reject_null_required_updates(self) -> RubricCriterionPatch:
        required = {
            "scoring_mode",
            "max_marks",
            "description",
            "dependencies",
            "alternatives",
            "units",
            "source_excerpt",
        }
        null_field = next(
            (
                field
                for field in sorted(required & self.model_fields_set)
                if getattr(self, field) is None
            ),
            None,
        )
        if null_field is not None:
            raise ValueError(f"{null_field} cannot be null")
        return self


class AiRubricCriterionReviewResponse(SerializedResponse):
    criterion_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    recommendation: Literal["accept", "reject", "revise"]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    suggested_updates: RubricCriterionPatch | None = None
    model: str
    reviewed_at: datetime


class RubricCriterionResponse(SerializedResponse):
    id: str
    question_number: str
    subpart: str
    criterion_id: str
    scoring_mode: Literal["point_based", "levels_based"]
    mark_type: str | None = None
    max_marks: float
    description: str
    dependencies: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    accuracy_requirement: str | None = None
    units: list[str] = Field(default_factory=list)
    follow_through_policy: str | None = None
    source_page: int | None = None
    source_excerpt: str
    confidence: float
    review_status: Literal["pending", "accepted", "rejected"]
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    ai_review: AiRubricCriterionReviewResponse | None = None


class RubricSetSummary(SerializedResponse):
    id: str
    subject_id: str
    paper_job_id: str
    source_document_id: str
    version_number: int
    status: Literal["draft", "confirmed"]
    identity: dict[str, str] = Field(default_factory=dict)
    parser_model: str | None = None
    parser_version: str
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None


class RubricSetResponse(RubricSetSummary):
    criteria: list[RubricCriterionResponse] = Field(default_factory=list)


class CreateRubricRequest(BaseModel):
    paper_job_id: str
    source_document_id: str


class GenerateRubricRequest(BaseModel):
    paper_job_id: str


class BatchRubricCriterionDecision(BaseModel):
    criterion_id: str = Field(min_length=1)
    expected_criterion_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    review_status: Literal["accepted", "rejected"]
    note: str | None = None
    updates: RubricCriterionPatch | None = None


class BatchReviewRubricCriteriaRequest(BaseModel):
    reviewer: str = Field(min_length=1)
    decisions: list[BatchRubricCriterionDecision] = Field(min_length=1, max_length=200)


class AiReviewRubricCriteriaRequest(BaseModel):
    criterion_ids: list[str] = Field(min_length=1, max_length=200)


class ReviewRubricCriterionRequest(BaseModel):
    review_status: Literal["accepted", "rejected"]
    reviewer: str = Field(min_length=1)
    note: str | None = None
    updates: RubricCriterionPatch | None = None


class ConfirmRubricRequest(BaseModel):
    reviewer: str = Field(min_length=1)


class GradePaperQuestionRequest(BaseModel):
    rubric_set_id: str


class PaperAssessmentResponse(SerializedResponse):
    id: str
    paper_job_id: str
    question_position: int
    rubric_set_id: str
    status: Literal["pending_review", "confirmed", "overridden"]
    result: GradeResponse
    created_at: datetime


class GradingOverviewQuestionResponse(SerializedResponse):
    position: int
    question_number: str
    status: Literal["unassessed", "pending_review", "confirmed", "overridden"]
    awarded: float | None = None
    available: float
    confidence: float | None = None
    error_types: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class GradingOverviewResponse(SerializedResponse):
    grade_estimate: UnitGradeEstimate | None = None
    paper_job_id: str
    rubric_set_id: str
    total_awarded: float
    total_available: float
    percentage: float | None
    completed_questions: int
    total_questions: int
    pending_review_count: int
    confirmed_count: int
    overridden_count: int
    incomplete: bool
    overall_suggestion: str
    common_error_types: list[str] = Field(default_factory=list)
    questions: list[GradingOverviewQuestionResponse] = Field(default_factory=list)


class GradingPaperSummary(SerializedResponse):
    job_id: str
    filename: str
    display_name: str | None = None
    paper_unit_id: str | None = None
    question_paper_document_id: str | None = None
    unit_code: str | None = None
    status: Literal["completed", "partial_failed"]
    total_questions: int
    completed_questions: int
    failed_questions: int
    updated_at: datetime
