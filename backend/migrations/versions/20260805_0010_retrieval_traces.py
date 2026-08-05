"""persist retrieval traces for evidence-quality diagnostics

Revision ID: 20260805_0010
Revises: 20260804_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0010"
down_revision: str | None = "20260804_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("retrieval_mode", sa.Text(), nullable=False),
        sa.Column("candidate_limit", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("postfilter_count", sa.Integer(), nullable=False),
        sa.Column("reranked_count", sa.Integer(), nullable=False),
        sa.Column("card_count", sa.Integer(), nullable=False),
        sa.Column("raw_fallback_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("index_build_id", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_retrieval_traces_subject_created",
        "retrieval_traces",
        ["subject_code", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_retrieval_traces_subject_created", table_name="retrieval_traces")
    op.drop_table("retrieval_traces")
