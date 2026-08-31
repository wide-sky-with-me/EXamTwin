from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from examtwin.contracts.base import SerializedResponse

EvidenceLevel = Literal["A", "B"]
MetricScale = Literal["proportion", "percent"]
MetricDirection = Literal["success", "difficulty"]
MetricComparator = Literal["eq", "approx", "gt", "gte", "lt", "lte"]
ReviewDecision = Literal["accepted", "rejected"]


class EvidencePage(SerializedResponse):
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)


class RawDifficultyCandidate(SerializedResponse):
    question_number: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
        max_length=64,
    )
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=8, max_length=4000)
    evidence_level: EvidenceLevel
    metric_name: str | None = Field(default=None, max_length=80)
    metric_text: str | None = Field(default=None, max_length=160)
    metric_value: float | None = None
    metric_scale: MetricScale | None = None
    metric_direction: MetricDirection | None = None
    metric_comparator: MetricComparator | None = None
    model_confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("question_number")
    @classmethod
    def canonicalize_question_number(cls, value: str) -> str:
        parts = value.split(".")
        if all(part.isdigit() for part in parts):
            return ".".join(str(int(part)) for part in parts)
        return value

    @field_validator("quote", "metric_name", "metric_text")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_level_contract(self) -> RawDifficultyCandidate:
        metric_fields = (
            self.metric_name,
            self.metric_text,
            self.metric_value,
            self.metric_scale,
            self.metric_direction,
            self.metric_comparator,
        )
        if self.evidence_level == "A" and any(item is None for item in metric_fields):
            raise ValueError("A-level evidence requires a complete official quantitative metric")
        if self.evidence_level == "B" and any(item is not None for item in metric_fields):
            raise ValueError("B-level evidence must remain qualitative without numeric projection")
        if self.metric_scale == "proportion" and self.metric_value is not None:
            if not 0 <= self.metric_value <= 1:
                raise ValueError("proportion metric_value must be in [0, 1]")
        if self.metric_scale == "percent" and self.metric_value is not None:
            if not 0 <= self.metric_value <= 100:
                raise ValueError("percent metric_value must be in [0, 100]")
        return self


class RawDifficultyCandidateBatch(SerializedResponse):
    candidates: list[RawDifficultyCandidate] = Field(default_factory=list, max_length=200)


class RawQuestionCatalogEntry(SerializedResponse):
    question_number: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
        max_length=64,
    )
    page_number: int = Field(ge=1)
    marker_quote: str = Field(min_length=1, max_length=240)


class RawQuestionCatalog(SerializedResponse):
    entries: list[RawQuestionCatalogEntry] = Field(default_factory=list, max_length=300)


class DifficultyCandidatePatch(SerializedResponse):
    question_number: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
        max_length=64,
    )
    page_number: int | None = Field(default=None, ge=1)
    quote: str | None = Field(default=None, min_length=8, max_length=4000)
    evidence_level: EvidenceLevel | None = None
    metric_name: str | None = Field(default=None, max_length=80)
    metric_text: str | None = Field(default=None, max_length=160)
    metric_value: float | None = None
    metric_scale: MetricScale | None = None
    metric_direction: MetricDirection | None = None
    metric_comparator: MetricComparator | None = None


class DifficultyReviewRequest(SerializedResponse):
    decision: ReviewDecision
    expected_candidate_fingerprint: str = Field(min_length=64, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)
    replacement: DifficultyCandidatePatch | None = None


class DifficultyRunCreateRequest(SerializedResponse):
    source_document_id: str = Field(min_length=1, max_length=128)


class DifficultyRunSummary(SerializedResponse):
    id: str
    subject_id: str
    subject_code: str
    source_document_id: str
    source_checksum: str
    question_paper_document_id: str
    question_paper_checksum: str
    question_catalog_hash: str
    package_digest: str
    prompt_digest: str
    pair_key: str
    input_hash: str
    extractor_version: str
    model_name: str
    status: str
    candidate_count: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    published_at: datetime | None = None


class DifficultyCandidateView(SerializedResponse):
    id: str
    run_id: str
    candidate_fingerprint: str
    question_number: str
    page_number: int
    evidence_level: EvidenceLevel
    evidence_type: Literal["quantitative", "qualitative"]
    metric_name: str | None = None
    metric_text: str | None = None
    metric_value: float | None = None
    metric_scale: MetricScale | None = None
    metric_direction: MetricDirection | None = None
    metric_comparator: MetricComparator | None = None
    difficulty_score: float | None = None
    quote: str
    quote_hash: str
    block_hash: str
    source_ref: str
    validation_status: str
    validation_errors: list[str] = Field(default_factory=list)
    review_decision: ReviewDecision | None = None
    review_replacement: dict[str, object] = Field(default_factory=dict)


class DifficultyRunDetail(DifficultyRunSummary):
    run_fingerprint: str
    candidates: list[DifficultyCandidateView] = Field(default_factory=list)


class DifficultyPublishRequest(SerializedResponse):
    expected_run_fingerprint: str = Field(min_length=64, max_length=64)
