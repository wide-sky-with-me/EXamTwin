from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from examtwin.schemas.base import SerializedResponse
from examtwin.schemas.grading import GradeResponse


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


class RubricSetResponse(RubricSetSummary):
    criteria: list[RubricCriterionResponse] = Field(default_factory=list)


class CreateRubricRequest(BaseModel):
    paper_job_id: str
    source_document_id: str


class ReviewAllRubricRequest(BaseModel):
    review_status: Literal["accepted", "rejected"]


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


class GradingPaperSummary(SerializedResponse):
    job_id: str
    filename: str
    unit_code: str | None = None
    status: Literal["completed", "partial_failed"]
    total_questions: int
    completed_questions: int
    failed_questions: int
    updated_at: datetime
