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


class SubjectModel(Base):
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    board_name: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="en")
    capability_profile_id: Mapped[str | None] = mapped_column(Text)
    active_graph_version_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeBaseModel(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("subject_id", "kind"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, ForeignKey("subjects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    active_version_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KnowledgeBaseVersionModel(Base):
    __tablename__ = "knowledge_base_versions"
    __table_args__ = (UniqueConstraint("knowledge_base_id", "version_number"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    knowledge_base_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge_bases.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    alias_name: Mapped[str] = mapped_column(Text)
    collection_name: Mapped[str | None] = mapped_column(Text)
    vector_build_id: Mapped[str | None] = mapped_column(Text)
    source_snapshot_json: Mapped[str] = mapped_column(Text, default="[]")
    parser_version: Mapped[str] = mapped_column(Text, default="hierarchical-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphVersionModel(Base):
    __tablename__ = "graph_versions"
    __table_args__ = (UniqueConstraint("subject_id", "version_number"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, ForeignKey("subjects.id", ondelete="CASCADE"))
    knowledge_base_version_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("knowledge_base_versions.id", ondelete="SET NULL")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    source_hash: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text, default="concept-extraction-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphNodeModel(Base):
    __tablename__ = "graph_nodes"
    __table_args__ = (UniqueConstraint("graph_version_id", "stable_key"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    graph_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_versions.id", ondelete="CASCADE")
    )
    stable_key: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    node_type: Mapped[str] = mapped_column(Text)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    parent_key: Mapped[str | None] = mapped_column(Text)
    unit_code: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    review_status: Mapped[str] = mapped_column(Text, default="pending")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GraphEdgeModel(Base):
    __tablename__ = "graph_edges"
    __table_args__ = (
        UniqueConstraint("graph_version_id", "source_key", "target_key", "relation_type"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    graph_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("graph_versions.id", ondelete="CASCADE")
    )
    source_key: Mapped[str] = mapped_column(Text)
    target_key: Mapped[str] = mapped_column(Text)
    relation_type: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    review_status: Mapped[str] = mapped_column(Text, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceDocumentModel(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("subjects.id", ondelete="CASCADE")
    )
    knowledge_base_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("knowledge_bases.id", ondelete="SET NULL")
    )
    path: Mapped[str] = mapped_column(Text, unique=True)
    filename: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(Text)
    authority_tier: Mapped[str] = mapped_column(Text, default="supplementary")
    source_role: Mapped[str] = mapped_column(Text, default="excluded")
    license_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    checksum: Mapped[str] = mapped_column(Text, default="")
    pair_key: Mapped[str | None] = mapped_column(Text)
    unit_code: Mapped[str | None] = mapped_column(Text)
    exam_year: Mapped[int | None] = mapped_column(Integer)
    exam_session: Mapped[str | None] = mapped_column(Text)
    identity_status: Mapped[str] = mapped_column(Text, default="not_applicable")
    identity_error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    markdown_path: Mapped[str | None] = mapped_column(Text)
    converted_source_checksum: Mapped[str | None] = mapped_column(Text)
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


class DocumentBlockModel(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (Index("idx_document_blocks_build_document", "build_id", "document_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_documents.id", ondelete="CASCADE")
    )
    knowledge_base_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("knowledge_base_versions.id", ondelete="CASCADE")
    )
    build_id: Mapped[str] = mapped_column(Text)
    parent_block_id: Mapped[str | None] = mapped_column(Text)
    previous_block_id: Mapped[str | None] = mapped_column(Text)
    next_block_id: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(Text)
    section_path_json: Mapped[str] = mapped_column(Text, default="[]")
    block_kind: Mapped[str] = mapped_column(Text)
    source_role: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    knowledge_codes_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
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
    description: Mapped[str] = mapped_column(Text, default="")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    graph_version_id: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(Text, default="accepted")
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
    knowledge_base_version_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("knowledge_base_versions.id", ondelete="SET NULL")
    )
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
    knowledge_base_version_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    knowledge_collection_names_json: Mapped[str] = mapped_column(Text, default="[]")
    graph_version_id: Mapped[str | None] = mapped_column(Text)
    source_integrity_status: Mapped[str] = mapped_column(
        Text,
        default="legacy_unverified",
    )
    split_contract_version: Mapped[str | None] = mapped_column(Text)
    split_source_digest: Mapped[str | None] = mapped_column(Text)
    replacement_for_job_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("paper_jobs.id", ondelete="RESTRICT"),
        unique=True,
    )
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
    source_kind: Mapped[str | None] = mapped_column(Text)
    source_digest: Mapped[str | None] = mapped_column(Text)
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
    knowledge_base_version_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    graph_version_id: Mapped[str | None] = mapped_column(Text)
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
    graph_version_id: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    review_status: Mapped[str] = mapped_column(Text, default="accepted")
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


class RetrievalTraceModel(Base):
    __tablename__ = "retrieval_traces"
    __table_args__ = (Index("idx_retrieval_traces_subject_created", "subject_code", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    query_hash: Mapped[str] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text)
    filters_json: Mapped[str] = mapped_column(Text, default="{}")
    retrieval_mode: Mapped[str] = mapped_column(Text)
    candidate_limit: Mapped[int] = mapped_column(Integer)
    candidate_count: Mapped[int] = mapped_column(Integer)
    postfilter_count: Mapped[int] = mapped_column(Integer)
    reranked_count: Mapped[int] = mapped_column(Integer)
    card_count: Mapped[int] = mapped_column(Integer)
    raw_fallback_count: Mapped[int] = mapped_column(Integer)
    result_count: Mapped[int] = mapped_column(Integer)
    index_build_id: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text, default="[]")
    duration_ms: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentModel(Base):
    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_code: Mapped[str] = mapped_column(Text)
    paper_job_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("paper_jobs.id", ondelete="SET NULL")
    )
    question_position: Mapped[int | None] = mapped_column(Integer)
    rubric_set_id: Mapped[str | None] = mapped_column(Text)
    knowledge_base_version_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    graph_version_id: Mapped[str | None] = mapped_column(Text)
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


class RubricSetModel(Base):
    __tablename__ = "rubric_sets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, ForeignKey("subjects.id", ondelete="CASCADE"))
    paper_job_id: Mapped[str] = mapped_column(Text, ForeignKey("paper_jobs.id", ondelete="CASCADE"))
    source_document_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_documents.id", ondelete="RESTRICT")
    )
    source_document_checksum: Mapped[str] = mapped_column(Text)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    identity_json: Mapped[str] = mapped_column(Text, default="{}")
    parser_model: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(Text, default="rubric-extraction-v1")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(Text)


class RubricCriterionModel(Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (UniqueConstraint("rubric_set_id", "question_number", "criterion_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    rubric_set_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_sets.id", ondelete="CASCADE")
    )
    question_number: Mapped[str] = mapped_column(Text)
    subpart: Mapped[str] = mapped_column(Text, default="whole")
    criterion_id: Mapped[str] = mapped_column(Text)
    scoring_mode: Mapped[str] = mapped_column(Text)
    mark_type: Mapped[str | None] = mapped_column(Text)
    max_marks: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text)
    dependencies_json: Mapped[str] = mapped_column(Text, default="[]")
    alternatives_json: Mapped[str] = mapped_column(Text, default="[]")
    accuracy_requirement: Mapped[str | None] = mapped_column(Text)
    units_json: Mapped[str] = mapped_column(Text, default="[]")
    follow_through_policy: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_excerpt: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(Text, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RubricCriterionReviewModel(Base):
    __tablename__ = "rubric_criterion_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rubric_set_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_sets.id", ondelete="CASCADE")
    )
    criterion_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_criteria.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(Text)
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RubricCriterionAiReviewModel(Base):
    __tablename__ = "rubric_criterion_ai_reviews"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    rubric_set_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_sets.id", ondelete="CASCADE")
    )
    criterion_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_criteria.id", ondelete="CASCADE")
    )
    criterion_fingerprint: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    suggested_updates_json: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentRunModel(Base):
    __tablename__ = "assessment_runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    subject_id: Mapped[str] = mapped_column(Text, ForeignKey("subjects.id", ondelete="CASCADE"))
    paper_job_id: Mapped[str] = mapped_column(Text, ForeignKey("paper_jobs.id", ondelete="CASCADE"))
    rubric_set_id: Mapped[str] = mapped_column(
        Text, ForeignKey("rubric_sets.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text)
    total_questions: Mapped[int] = mapped_column(Integer)
    completed_questions: Mapped[int] = mapped_column(Integer, default=0)
    failed_questions: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
