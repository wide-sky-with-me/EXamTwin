"""Add versioned curriculum candidates.

Revision ID: 20260803_0003
Revises: 20260803_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0003"
down_revision: str | Sequence[str] | None = "20260803_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "curriculum_candidates",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("build_run_id", sa.Text(), nullable=False),
        sa.Column("subject_pack_id", sa.Text(), nullable=False),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("extractor_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("review_status", sa.Text(), nullable=False),
        sa.Column("candidate_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["build_run_id"],
            ["knowledge_build_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["source_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("build_run_id"),
    )
    op.create_index(
        "idx_curriculum_candidate_subject",
        "curriculum_candidates",
        ["subject_code", "created_at"],
    )
    op.create_index(
        "idx_curriculum_candidate_content",
        "curriculum_candidates",
        ["subject_code", "input_hash", "extractor_version"],
    )


def downgrade() -> None:
    op.drop_index("idx_curriculum_candidate_content", table_name="curriculum_candidates")
    op.drop_index("idx_curriculum_candidate_subject", table_name="curriculum_candidates")
    op.drop_table("curriculum_candidates")
