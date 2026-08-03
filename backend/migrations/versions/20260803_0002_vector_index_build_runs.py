"""Add durable vector index build runs.

Revision ID: 20260803_0002
Revises: 20260803_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0002"
down_revision: str | Sequence[str] | None = "20260803_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vector_index_build_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("alias_name", sa.Text(), nullable=False),
        sa.Column("staging_collection", sa.Text(), nullable=False),
        sa.Column("previous_collection", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=True),
        sa.Column("expected_points", sa.Integer(), nullable=False),
        sa.Column("indexed_points", sa.Integer(), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("staging_collection"),
    )
    op.create_index(
        "idx_vector_index_build_subject",
        "vector_index_build_runs",
        ["subject_code", "created_at"],
    )
    op.create_index(
        "idx_vector_index_build_alias_status",
        "vector_index_build_runs",
        ["alias_name", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_vector_index_build_alias_status", table_name="vector_index_build_runs")
    op.drop_index("idx_vector_index_build_subject", table_name="vector_index_build_runs")
    op.drop_table("vector_index_build_runs")
