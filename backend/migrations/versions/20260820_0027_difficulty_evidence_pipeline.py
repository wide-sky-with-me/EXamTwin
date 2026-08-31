"""add reviewed examiner difficulty evidence pipeline

Revision ID: 20260820_0027
Revises: 20260820_0026
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0027"
down_revision: str | None = "20260820_0026"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "difficulty_evidence_runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_checksum", sa.Text(), nullable=False),
        sa.Column("question_paper_document_id", sa.Text(), nullable=False),
        sa.Column("question_paper_checksum", sa.Text(), nullable=False),
        sa.Column("question_catalog_json", sa.Text(), nullable=False),
        sa.Column("question_catalog_hash", sa.Text(), nullable=False),
        sa.Column("pair_key", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("package_digest", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("prompt_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["question_paper_document_id"],
            ["source_documents.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("subject_id", "input_hash"),
    )
    op.create_table(
        "difficulty_evidence_candidates",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_checksum", sa.Text(), nullable=False),
        sa.Column("pair_key", sa.Text(), nullable=False),
        sa.Column("unit_code", sa.Text()),
        sa.Column("question_number", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("evidence_level", sa.Text(), nullable=False),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.Text()),
        sa.Column("metric_text", sa.Text()),
        sa.Column("metric_value", sa.Float()),
        sa.Column("metric_scale", sa.Text()),
        sa.Column("metric_direction", sa.Text()),
        sa.Column("difficulty_score", sa.Float()),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("quote_hash", sa.Text(), nullable=False),
        sa.Column("block_hash", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("model_confidence", sa.Float()),
        sa.Column("validation_status", sa.Text(), nullable=False),
        sa.Column("validation_errors_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["difficulty_evidence_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("run_id", "question_number", "page_number", "quote_hash"),
        sa.CheckConstraint(
            "(evidence_level = 'B' AND evidence_type = 'qualitative' "
            "AND metric_name IS NULL AND metric_text IS NULL AND metric_value IS NULL "
            "AND metric_scale IS NULL AND metric_direction IS NULL "
            "AND difficulty_score IS NULL) OR "
            "(evidence_level = 'A' AND evidence_type = 'quantitative' "
            "AND metric_name IS NOT NULL AND metric_text IS NOT NULL "
            "AND metric_value IS NOT NULL AND metric_scale IS NOT NULL "
            "AND metric_direction IS NOT NULL)",
            name="ck_difficulty_candidate_level_shape",
        ),
    )
    op.create_index(
        "idx_difficulty_candidates_run_status",
        "difficulty_evidence_candidates",
        ["run_id", "validation_status"],
    )
    op.create_table(
        "difficulty_evidence_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("candidate_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("replacement_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["difficulty_evidence_candidates.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("candidate_id", "sequence"),
    )
    op.alter_column("question_difficulty", "difficulty_score", nullable=True)
    op.alter_column("question_difficulty", "difficulty_label", nullable=True)
    op.alter_column("question_difficulty", "confidence", nullable=True)
    op.add_column("question_difficulty", sa.Column("publication_run_id", sa.Text()))
    op.add_column("question_difficulty", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_question_difficulty_publication_run",
        "question_difficulty",
        "difficulty_evidence_runs",
        ["publication_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.execute("DELETE FROM question_difficulty WHERE publication_run_id IS NOT NULL")
    op.drop_constraint(
        "fk_question_difficulty_publication_run",
        "question_difficulty",
        type_="foreignkey",
    )
    op.drop_column("question_difficulty", "published_at")
    op.drop_column("question_difficulty", "publication_run_id")
    op.alter_column("question_difficulty", "confidence", nullable=False)
    op.alter_column("question_difficulty", "difficulty_label", nullable=False)
    op.alter_column("question_difficulty", "difficulty_score", nullable=False)
    op.drop_table("difficulty_evidence_reviews")
    op.drop_index(
        "idx_difficulty_candidates_run_status",
        table_name="difficulty_evidence_candidates",
    )
    op.drop_table("difficulty_evidence_candidates")
    op.drop_table("difficulty_evidence_runs")
