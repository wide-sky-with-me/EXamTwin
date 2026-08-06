from __future__ import annotations

from typing import Literal

from pydantic import Field

from examtwin.contracts.base import SerializedResponse
from examtwin.contracts.evidence import AnswerDiagram, AnswerImage, Citation, SubpartRequirement
from examtwin.contracts.knowledge import (
    KnowledgeDifficultySummary,
    KnowledgePathItem,
    KnowledgeRelationSummary,
)


class PaperKnowledgeReference(SerializedResponse):
    code: str
    title: str
    node_type: str
    difficulty_score: float
    difficulty_label: str
    difficulty_confidence: float
    evidence_level: str
    source_ref: str
    references: list[Citation] = Field(default_factory=list)
    definition: str = ""
    breadcrumb: str = ""
    path: list[KnowledgePathItem] = Field(default_factory=list)
    relations: list[KnowledgeRelationSummary] = Field(default_factory=list)
    difficulty: KnowledgeDifficultySummary | None = None


class PaperQuestionAnswer(SerializedResponse):
    number: str
    question_markdown: str
    answer_markdown: str
    diagrams: list[AnswerDiagram] = Field(default_factory=list)
    images: list[AnswerImage] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    knowledge_points: list[PaperKnowledgeReference] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    grounded: bool
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class PaperAnswerResponse(SerializedResponse):
    filename: str
    detected_questions: int
    succeeded: int
    failed: int
    questions: list[PaperQuestionAnswer]


class PaperJobCreated(SerializedResponse):
    job_id: str
    status: Literal["queued"]
    stage: Literal["queued"]


class AgentStepSummary(SerializedResponse):
    run_attempt: int = Field(ge=1)
    sequence: int = Field(ge=1)
    phase: Literal["preparing", "deciding", "tool", "verifying", "finalizing"]
    status: Literal["running", "completed", "failed"]
    tool_name: str | None = None
    message: str
    created_at: str


class PaperJobQuestion(SerializedResponse):
    position: int
    status: Literal["pending", "answering", "completed", "failed"]
    attempts: int = 0
    number: str
    question_markdown: str
    source_pages: list[int] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list)
    answer_requirements: list[SubpartRequirement] = Field(default_factory=list)
    total_marks: int | None = None
    answer_markdown: str = ""
    diagrams: list[AnswerDiagram] = Field(default_factory=list)
    images: list[AnswerImage] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    knowledge_points: list[PaperKnowledgeReference] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    grounded: bool = False
    warnings: list[str] = Field(default_factory=list)
    agent_steps: list[AgentStepSummary] = Field(default_factory=list)
    error: str | None = None


class PaperJobChunk(SerializedResponse):
    chunk_index: int
    page_start: int
    page_end: int
    status: Literal["pending", "parsing", "completed", "failed"]
    attempts: int
    error: str | None = None


class PaperJobResponse(SerializedResponse):
    job_id: str
    filename: str
    subject_pack_id: str
    subject_code: str
    unit_code: str | None
    knowledge_base_version_ids: list[str] = Field(default_factory=list)
    graph_version_id: str | None = None
    status: Literal[
        "queued",
        "parsing",
        "vision_review",
        "splitting",
        "answering",
        "completed",
        "partial_failed",
        "failed",
    ]
    stage: Literal["queued", "parsing", "vision_review", "splitting", "answering", "completed"]
    total_pages: int
    parsed_pages: int
    total_questions: int
    completed_questions: int
    failed_questions: int
    error: str | None = None
    created_at: str
    updated_at: str
    chunks: list[PaperJobChunk] = Field(default_factory=list)
    questions: list[PaperJobQuestion] = Field(default_factory=list)
