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

PaperJobStatus = Literal[
    "queued",
    "parsing",
    "vision_review",
    "splitting",
    "answering",
    "completed",
    "partial_failed",
    "failed",
]
PaperJobFilterStatus = Literal[
    "active",
    "queued",
    "parsing",
    "vision_review",
    "splitting",
    "answering",
    "completed",
    "partial_failed",
    "failed",
]
PaperAnswerMode = Literal["generated", "uploaded"]
PaperJobStage = Literal[
    "queued",
    "parsing",
    "vision_review",
    "splitting",
    "answering",
    "completed",
]
PaperSourceIntegrityStatus = Literal[
    "pending",
    "verified",
    "legacy_unverified",
    "replacement_queued",
]


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
    source_kind: Literal["primary"] | None = None
    source_digest: str | None = None
    requires_visual_context: bool | None = None
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


class PaperJobBulkDeleteRequest(SerializedResponse):
    job_ids: list[str] = Field(min_length=1)


class PaperJobBulkDeleteResponse(SerializedResponse):
    deleted_count: int = Field(ge=1)


class RenamePaperJobRequest(SerializedResponse):
    display_name: str = Field(min_length=1, max_length=200)


class PaperJobSummary(SerializedResponse):
    job_id: str
    filename: str
    display_name: str | None = None
    answer_mode: PaperAnswerMode = "generated"
    pair_key: str | None = None
    paper_unit_id: str | None = None
    question_paper_document_id: str | None = None
    source_booklet_document_id: str | None = None
    source_booklet_checksum: str | None = None
    source_booklet_filename: str | None = None
    unit_code: str | None
    status: PaperJobStatus
    stage: PaperJobStage
    total_questions: int
    completed_questions: int
    failed_questions: int
    source_integrity_status: PaperSourceIntegrityStatus
    split_contract_version: str | None = None
    replacement_for_job_id: str | None = None
    replaced_by_job_id: str | None = None
    created_at: str
    updated_at: str


class PaperJobListResponse(SerializedResponse):
    items: list[PaperJobSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)


class PaperJobResponse(SerializedResponse):
    job_id: str
    filename: str
    display_name: str | None = None
    answer_mode: PaperAnswerMode = "generated"
    pair_key: str | None = None
    paper_unit_id: str | None = None
    question_paper_document_id: str | None = None
    source_booklet_document_id: str | None = None
    source_booklet_checksum: str | None = None
    source_booklet_filename: str | None = None
    subject_pack_id: str
    subject_code: str
    unit_code: str | None
    knowledge_base_version_ids: list[str] = Field(default_factory=list)
    graph_version_id: str | None = None
    status: PaperJobStatus
    stage: PaperJobStage
    total_pages: int
    parsed_pages: int
    total_questions: int
    completed_questions: int
    failed_questions: int
    error: str | None = None
    source_integrity_status: PaperSourceIntegrityStatus
    split_contract_version: str | None = None
    split_source_digest: str | None = None
    replacement_for_job_id: str | None = None
    replaced_by_job_id: str | None = None
    created_at: str
    updated_at: str
    chunks: list[PaperJobChunk] = Field(default_factory=list)
    questions: list[PaperJobQuestion] = Field(default_factory=list)
