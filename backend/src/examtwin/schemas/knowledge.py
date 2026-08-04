from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from examtwin.schemas.base import SerializedResponse
from examtwin.schemas.evidence import AnswerDiagram, AnswerImage, Citation


class DifficultyFeatures(BaseModel):
    syllabus_complexity: float = Field(default=0.5, ge=0, le=1)
    prerequisite_depth: int = Field(default=0, ge=0)
    cognitive_demand: float = Field(default=0.5, ge=0, le=1)
    facility_rate: float | None = Field(default=None, ge=0, le=1)
    solution_steps: int = Field(default=3, ge=1)
    examiner_severity: float | None = Field(default=None, ge=0, le=1)
    evidence_confidence: float = Field(default=0.35, ge=0, le=1)


class DifficultyResult(SerializedResponse):
    score: float
    label: Literal["easy", "medium", "hard"]
    confidence: float
    raw_score: float
    contributions: dict[str, float]


class KnowledgePathItem(SerializedResponse):
    code: str
    title: str
    node_type: str


class KnowledgeRelationSummary(SerializedResponse):
    relation_type: str
    direction: Literal["outgoing", "incoming"]
    code: str
    title: str
    node_type: str
    confidence: float
    source_ref: str


class KnowledgeRelationResponse(SerializedResponse):
    id: int
    source_code: str
    source_title: str
    target_code: str
    target_title: str
    relation_type: str
    confidence: float
    source_ref: str


class KnowledgeDifficultySummary(SerializedResponse):
    score: float
    label: Literal["easy", "medium", "hard"]
    confidence: float
    evidence_level: str
    method: str
    rationale: str
    features: dict[str, float | int | None] = Field(default_factory=dict)


class KnowledgePointResponse(SerializedResponse):
    id: str
    code: str
    title: str
    unit_code: str
    strand: str
    parent_id: str | None
    difficulty_score: float
    difficulty_label: str
    difficulty_confidence: float
    evidence_level: str
    source_ref: str
    features: dict[str, Any] = Field(default_factory=dict)
    definition: str = ""
    breadcrumb: str = ""
    path: list[KnowledgePathItem] = Field(default_factory=list)
    relations: list[KnowledgeRelationSummary] = Field(default_factory=list)
    difficulty: KnowledgeDifficultySummary | None = None
    references: list[Citation] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=2)
    subject_code: str = Field(min_length=1)
    unit_code: str | None = None
    pair_key: str | None = None
    source_types: list[str] = Field(default_factory=list)
    authority_tiers: list[str] = Field(default_factory=lambda: ["official", "licensed_core"])
    top_k: int | None = Field(default=None, ge=1, le=50)


class AskResponse(SerializedResponse):
    answer_markdown: str
    citations: list[Citation]
    diagrams: list[AnswerDiagram] = Field(default_factory=list)
    images: list[AnswerImage] = Field(default_factory=list)
    confidence: float
    grounded: bool
    warnings: list[str] = Field(default_factory=list)


class SourceContextResponse(SerializedResponse):
    document_id: str
    source: str
    page: int | None = None
    content_markdown: str
    truncated: bool = False
