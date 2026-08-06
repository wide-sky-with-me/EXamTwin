"""add subject workspaces, versioned knowledge, graphs, and rubric workflows

Revision ID: 20260805_0011
Revises: 20260805_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0011"
down_revision: str | None = "20260805_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("subject_code", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("board_name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False, server_default="en"),
        sa.Column("capability_profile_id", sa.Text(), nullable=True),
        sa.Column("active_graph_version_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Text(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("active_version_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_id", "kind"),
    )
    op.create_table(
        "knowledge_base_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "knowledge_base_id",
            sa.Text(),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("alias_name", sa.Text(), nullable=False),
        sa.Column("collection_name", sa.Text(), nullable=True),
        sa.Column("vector_build_id", sa.Text(), nullable=True),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("parser_version", sa.Text(), nullable=False, server_default="hierarchical-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("knowledge_base_id", "version_number"),
    )
    op.create_table(
        "graph_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Text(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_base_version_id",
            sa.Text(),
            sa.ForeignKey("knowledge_base_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("source_hash", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column(
            "prompt_version", sa.Text(), nullable=False, server_default="concept-extraction-v1"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subject_id", "version_number"),
    )
    op.create_table(
        "graph_nodes",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "graph_version_id",
            sa.Text(),
            sa.ForeignKey("graph_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stable_key", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("parent_key", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("graph_version_id", "stable_key"),
    )
    op.create_table(
        "graph_edges",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "graph_version_id",
            sa.Text(),
            sa.ForeignKey("graph_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("target_key", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("graph_version_id", "source_key", "target_key", "relation_type"),
    )

    op.add_column("source_documents", sa.Column("subject_id", sa.Text(), nullable=True))
    op.add_column("source_documents", sa.Column("knowledge_base_id", sa.Text(), nullable=True))
    op.add_column(
        "source_documents",
        sa.Column("source_role", sa.Text(), nullable=False, server_default="excluded"),
    )
    op.add_column(
        "source_documents",
        sa.Column("license_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_source_documents_subject",
        "source_documents",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_source_documents_knowledge_base",
        "source_documents",
        "knowledge_bases",
        ["knowledge_base_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "knowledge_points", sa.Column("description", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "knowledge_points",
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("knowledge_points", sa.Column("graph_version_id", sa.Text(), nullable=True))
    op.add_column(
        "knowledge_points",
        sa.Column("review_status", sa.Text(), nullable=False, server_default="accepted"),
    )
    op.add_column("knowledge_relations", sa.Column("graph_version_id", sa.Text(), nullable=True))
    op.add_column(
        "knowledge_relations",
        sa.Column("evidence_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "knowledge_relations",
        sa.Column("review_status", sa.Text(), nullable=False, server_default="accepted"),
    )
    op.add_column(
        "vector_index_build_runs",
        sa.Column(
            "knowledge_base_version_id",
            sa.Text(),
            sa.ForeignKey("knowledge_base_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "paper_jobs",
        sa.Column(
            "knowledge_base_version_ids_json", sa.Text(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "paper_jobs",
        sa.Column(
            "knowledge_collection_names_json", sa.Text(), nullable=False, server_default="[]"
        ),
    )
    op.add_column("paper_jobs", sa.Column("graph_version_id", sa.Text(), nullable=True))
    op.add_column(
        "assessments",
        sa.Column(
            "paper_job_id",
            sa.Text(),
            sa.ForeignKey("paper_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("assessments", sa.Column("question_position", sa.Integer(), nullable=True))
    op.add_column("assessments", sa.Column("rubric_set_id", sa.Text(), nullable=True))
    op.add_column(
        "assessments",
        sa.Column(
            "knowledge_base_version_ids_json", sa.Text(), nullable=False, server_default="[]"
        ),
    )
    op.add_column("assessments", sa.Column("graph_version_id", sa.Text(), nullable=True))

    op.create_table(
        "document_blocks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Text(),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_base_version_id",
            sa.Text(),
            sa.ForeignKey("knowledge_base_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("parent_block_id", sa.Text(), nullable=True),
        sa.Column("previous_block_id", sa.Text(), nullable=True),
        sa.Column("next_block_id", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.Text(), nullable=True),
        sa.Column("section_path_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("block_kind", sa.Text(), nullable=False),
        sa.Column("source_role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("knowledge_codes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_document_blocks_build_document",
        "document_blocks",
        ["build_id", "document_id"],
    )

    op.create_table(
        "rubric_sets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Text(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_job_id",
            sa.Text(),
            sa.ForeignKey("paper_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            sa.Text(),
            sa.ForeignKey("source_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("identity_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("parser_model", sa.Text(), nullable=True),
        sa.Column(
            "parser_version", sa.Text(), nullable=False, server_default="rubric-extraction-v1"
        ),
        sa.Column("warnings_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("paper_job_id", "version_number"),
    )
    op.create_table(
        "rubric_criteria",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "rubric_set_id",
            sa.Text(),
            sa.ForeignKey("rubric_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_number", sa.Text(), nullable=False),
        sa.Column("subpart", sa.Text(), nullable=False, server_default="whole"),
        sa.Column("criterion_id", sa.Text(), nullable=False),
        sa.Column("scoring_mode", sa.Text(), nullable=False),
        sa.Column("mark_type", sa.Text(), nullable=True),
        sa.Column("max_marks", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("dependencies_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("alternatives_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("accuracy_requirement", sa.Text(), nullable=True),
        sa.Column("units_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("follow_through_policy", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
        sa.UniqueConstraint("rubric_set_id", "question_number", "criterion_id"),
    )
    op.create_table(
        "assessment_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "subject_id",
            sa.Text(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_job_id",
            sa.Text(),
            sa.ForeignKey("paper_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rubric_set_id",
            sa.Text(),
            sa.ForeignKey("rubric_sets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("completed_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("assessment_runs")
    op.drop_table("rubric_criteria")
    op.drop_table("rubric_sets")
    op.drop_index("idx_document_blocks_build_document", table_name="document_blocks")
    op.drop_table("document_blocks")
    op.drop_column("assessments", "graph_version_id")
    op.drop_column("assessments", "knowledge_base_version_ids_json")
    op.drop_column("assessments", "rubric_set_id")
    op.drop_column("assessments", "question_position")
    op.drop_column("assessments", "paper_job_id")
    op.drop_column("paper_jobs", "graph_version_id")
    op.drop_column("paper_jobs", "knowledge_collection_names_json")
    op.drop_column("paper_jobs", "knowledge_base_version_ids_json")
    op.drop_column("vector_index_build_runs", "knowledge_base_version_id")
    op.drop_column("knowledge_relations", "review_status")
    op.drop_column("knowledge_relations", "evidence_json")
    op.drop_column("knowledge_relations", "graph_version_id")
    op.drop_column("knowledge_points", "review_status")
    op.drop_column("knowledge_points", "graph_version_id")
    op.drop_column("knowledge_points", "aliases_json")
    op.drop_column("knowledge_points", "description")
    op.drop_constraint("fk_source_documents_knowledge_base", "source_documents", type_="foreignkey")
    op.drop_constraint("fk_source_documents_subject", "source_documents", type_="foreignkey")
    op.drop_column("source_documents", "license_confirmed")
    op.drop_column("source_documents", "source_role")
    op.drop_column("source_documents", "knowledge_base_id")
    op.drop_column("source_documents", "subject_id")
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
    op.drop_table("graph_versions")
    op.drop_table("knowledge_base_versions")
    op.drop_table("knowledge_bases")
    op.drop_table("subjects")
