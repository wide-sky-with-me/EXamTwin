from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SourceDocumentModel(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, unique=True)
    filename: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(Text)
    authority_tier: Mapped[str] = mapped_column(Text, default="supplementary")
    checksum: Mapped[str] = mapped_column(Text, default="")
    pair_key: Mapped[str | None] = mapped_column(Text)
    unit_code: Mapped[str | None] = mapped_column(Text)
    exam_year: Mapped[int | None] = mapped_column(Integer)
    exam_session: Mapped[str | None] = mapped_column(Text)
    identity_status: Mapped[str] = mapped_column(Text, default="not_applicable")
    identity_error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    markdown_path: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SourceDocumentLocationModel(Base):
    __tablename__ = "source_document_locations"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("source_documents.id", ondelete="CASCADE"),
    )
    relative_path: Mapped[str] = mapped_column(Text)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceDocumentVersionModel(Base):
    __tablename__ = "source_document_versions"
    __table_args__ = (UniqueConstraint("document_id", "checksum"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("source_documents.id", ondelete="CASCADE"),
    )
    checksum: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StoredObjectModel(Base):
    __tablename__ = "stored_objects"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    storage_backend: Mapped[str] = mapped_column(Text)
    bucket: Mapped[str | None] = mapped_column(Text)
    checksum_sha256: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    owner_type: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, default="active")
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class KnowledgeBuildRunModel(Base):
    __tablename__ = "knowledge_build_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_pack_id: Mapped[str] = mapped_column(Text)
    subject_code: Mapped[str] = mapped_column(Text)
    source_document_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    pipeline_version: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    artifact_json: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CurriculumCandidateModel(Base):
    __tablename__ = "curriculum_candidates"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    build_run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("knowledge_build_runs.id", ondelete="CASCADE"),
        unique=True,
    )
    subject_pack_id: Mapped[str] = mapped_column(Text)
    subject_code: Mapped[str] = mapped_column(Text)
    source_document_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("source_documents.id", ondelete="CASCADE"),
    )
    input_hash: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    extractor_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text)
    candidate_json: Mapped[str] = mapped_column(Text)
    validation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgePointModel(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    unit_code: Mapped[str] = mapped_column(Text, default="")
    strand: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(Text, ForeignKey("knowledge_points.id"))
    difficulty_score: Mapped[float] = mapped_column(Float, default=0)
    difficulty_label: Mapped[str] = mapped_column(Text, default="medium")
    difficulty_confidence: Mapped[float] = mapped_column(Float, default=0)
    evidence_level: Mapped[str] = mapped_column(Text, default="D")
    source_ref: Mapped[str] = mapped_column(Text, default="")
    features_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class KnowledgeEvidenceModel(Base):
    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_point_id",
            "source_document_id",
            "page",
            "section",
            "content_hash",
            "build_id",
            name="uq_knowledge_evidence_version",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_point_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
    )
    source_document_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("source_documents.id", ondelete="CASCADE"),
    )
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    section_path_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_role: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    build_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("vector_index_build_runs.id", ondelete="CASCADE"),
    )
    confidence: Mapped[float] = mapped_column(Float)
    source_ref: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DifficultyEvidenceModel(Base):
    __tablename__ = "difficulty_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_point_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("knowledge_points.id"),
    )
    question_ref: Mapped[str | None] = mapped_column(Text)
    evidence_type: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    evidence_level: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run_id: Mapped[str | None] = mapped_column(Text)
    method_key: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class VectorIndexBuildRunModel(Base):
    __tablename__ = "vector_index_build_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    alias_name: Mapped[str] = mapped_column(Text)
    staging_collection: Mapped[str] = mapped_column(Text)
    previous_collection: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(Text)
    expected_points: Mapped[int] = mapped_column(Integer)
    indexed_points: Mapped[int] = mapped_column(Integer)
    document_count: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VectorIndexPublicationModel(Base):
    __tablename__ = "vector_index_publications"

    subject_code: Mapped[str] = mapped_column(Text, primary_key=True)
    alias_name: Mapped[str] = mapped_column(Text, unique=True)
    active_build_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("vector_index_build_runs.id"),
    )
    collection_name: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperJobModel(Base):
    __tablename__ = "paper_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_pack_id: Mapped[str] = mapped_column(Text)
    subject_code: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    suffix: Mapped[str] = mapped_column(Text)
    unit_code: Mapped[str | None] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    parsed_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    completed_questions: Mapped[int] = mapped_column(Integer, default=0)
    failed_questions: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    lease_token: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperJobChunkModel(Base):
    __tablename__ = "paper_job_chunks"
    __table_args__ = (UniqueConstraint("job_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="CASCADE"),
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="pending")
    markdown_path: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperJobQuestionModel(Base):
    __tablename__ = "paper_job_questions"
    __table_args__ = (UniqueConstraint("job_id", "position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="CASCADE"),
    )
    position: Mapped[int] = mapped_column(Integer)
    number: Mapped[str] = mapped_column(Text)
    question_markdown: Mapped[str] = mapped_column(Text)
    source_pages_json: Mapped[str] = mapped_column(Text, default="[]")
    requires_visual_context: Mapped[bool | None] = mapped_column(Boolean)
    knowledge_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    requirements_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(Text, default="pending")
    answer_json: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperAgentStepModel(Base):
    __tablename__ = "paper_agent_steps"
    __table_args__ = (UniqueConstraint("job_id", "question_position", "run_attempt", "sequence"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="CASCADE"),
    )
    question_position: Mapped[int] = mapped_column(Integer)
    run_attempt: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    phase: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaperAgentRunModel(Base):
    __tablename__ = "paper_agent_runs"
    __table_args__ = (UniqueConstraint("job_id", "question_position", "run_attempt"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="CASCADE"),
    )
    question_position: Mapped[int] = mapped_column(Integer)
    run_attempt: Mapped[int] = mapped_column(Integer)
    package_id: Mapped[str] = mapped_column(Text)
    package_version: Mapped[str] = mapped_column(Text)
    package_digest: Mapped[str] = mapped_column(Text)
    skill_digest: Mapped[str] = mapped_column(Text)
    prompt_digest: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str] = mapped_column(Text)
    max_iterations: Mapped[int] = mapped_column(Integer)
    max_tool_calls: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperAgentToolCallModel(Base):
    __tablename__ = "paper_agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("job_id", "question_position", "run_attempt", "call_key"),
        Index(
            "idx_paper_agent_tool_replay",
            "job_id",
            "question_position",
            "call_key",
            "execution_fingerprint",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="CASCADE"),
    )
    question_position: Mapped[int] = mapped_column(Integer)
    run_attempt: Mapped[int] = mapped_column(Integer)
    call_key: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text)
    input_digest: Mapped[str] = mapped_column(Text)
    execution_fingerprint: Mapped[str] = mapped_column(Text)
    replay_safe: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(Text)
    result_digest: Mapped[str | None] = mapped_column(Text)
    replay_json: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeRelationModel(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_points.id"))
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("knowledge_points.id"))
    relation_type: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    source_ref: Mapped[str] = mapped_column(Text)


class QuestionDifficultyModel(Base):
    __tablename__ = "question_difficulty"
    __table_args__ = (UniqueConstraint("source_document_id", "question_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_document_id: Mapped[str] = mapped_column(Text, ForeignKey("source_documents.id"))
    question_ref: Mapped[str] = mapped_column(Text)
    pair_key: Mapped[str | None] = mapped_column(Text)
    question_number: Mapped[str] = mapped_column(Text)
    difficulty_score: Mapped[float] = mapped_column(Float)
    difficulty_label: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    evidence_level: Mapped[str] = mapped_column(Text)
    knowledge_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_json: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentModel(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    question_ref: Mapped[str | None] = mapped_column(Text)
    answer_markdown: Mapped[str] = mapped_column(Text)
    total_awarded: Mapped[float] = mapped_column(Float)
    total_available: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewModel(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assessment_id: Mapped[str] = mapped_column(Text, ForeignKey("assessments.id"))
    reviewer: Mapped[str] = mapped_column(Text)
    decision: Mapped[str] = mapped_column(Text)
    override_mark: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
