from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from examtwin.contracts.base import SerializedResponse
from examtwin.contracts.evidence import Citation


class ExpectedExpression(BaseModel):
    student: str
    expected: str
    variable: str | None = None


class GradeRequest(BaseModel):
    answer_markdown: str = Field(min_length=1)
    question_ref: str | None = None
    question_markdown: str | None = None
    mark_scheme_markdown: str | None = None
    max_marks: float | None = Field(default=None, gt=0)
    unit_code: str | None = None
    expected_expressions: list[ExpectedExpression] = Field(default_factory=list)
    knowledge_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_question_context(self) -> GradeRequest:
        if not self.question_ref and not self.question_markdown:
            raise ValueError("question_ref or question_markdown is required")
        return self


class RubricAward(SerializedResponse):
    criterion_id: str
    description: str
    mark_type: str | None = None
    max_marks: float
    awarded: float
    student_evidence: str | None = None
    rationale: str
    confidence: float = Field(ge=0, le=1)
    source_ref: str | None = None
    knowledge_codes: list[str] = Field(default_factory=list)
    error_types: list[
        Literal[
            "conceptual",
            "procedural",
            "calculation",
            "notation",
            "unit",
            "diagram",
            "omission",
        ]
    ] = Field(default_factory=list)
    improvement_suggestion: str | None = None


class SymbolicCheck(SerializedResponse):
    student: str
    expected: str
    equivalent: bool | None
    detail: str


class GradeResponse(SerializedResponse):
    assessment_id: str
    subject_code: str
    question_ref: str | None
    total_awarded: float
    total_available: float
    confidence: float
    status: Literal["pending_review", "confirmed", "overridden"]
    rubric_awards: list[RubricAward]
    symbolic_checks: list[SymbolicCheck] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    manual_review_required: bool = True


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1)
    decision: Literal["confirm", "override"]
    override_mark: float | None = Field(default=None, ge=0)
    note: str | None = None

    @model_validator(mode="after")
    def require_override(self) -> ReviewRequest:
        if self.decision == "override" and self.override_mark is None:
            raise ValueError("override_mark is required when decision=override")
        return self


class ReviewQueueItem(SerializedResponse):
    id: str
    subject_code: str
    subject_id: str
    question_ref: str | None
    total_awarded: float
    total_available: float
    confidence: float
    status: Literal["pending_review"]
    result: GradeResponse
    created_at: datetime


class ReviewDecisionResponse(SerializedResponse):
    assessment_id: str
    status: Literal["confirmed", "overridden"]
    final_mark: float
    reviewed_by: str
