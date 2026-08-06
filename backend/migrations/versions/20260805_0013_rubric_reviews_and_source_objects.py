"""add source object references and rubric criterion audit

Revision ID: 20260805_0013
Revises: 20260805_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0013"
down_revision: str | None = "20260805_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_documents", sa.Column("object_key", sa.Text(), nullable=True))
    op.add_column("rubric_sets", sa.Column("confirmed_by", sa.Text(), nullable=True))
    op.add_column("rubric_criteria", sa.Column("reviewed_by", sa.Text(), nullable=True))
    op.add_column(
        "rubric_criteria",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rubric_criterion_reviews",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "rubric_set_id",
            sa.Text(),
            sa.ForeignKey("rubric_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criterion_id",
            sa.Text(),
            sa.ForeignKey("rubric_criteria.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.Text(), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rubric_criterion_reviews_rubric_set_id",
        "rubric_criterion_reviews",
        ["rubric_set_id"],
    )
    op.create_index(
        "ix_rubric_criterion_reviews_criterion_id",
        "rubric_criterion_reviews",
        ["criterion_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rubric_criterion_reviews_criterion_id",
        table_name="rubric_criterion_reviews",
    )
    op.drop_index(
        "ix_rubric_criterion_reviews_rubric_set_id",
        table_name="rubric_criterion_reviews",
    )
    op.drop_table("rubric_criterion_reviews")
    op.drop_column("rubric_criteria", "reviewed_at")
    op.drop_column("rubric_criteria", "reviewed_by")
    op.drop_column("rubric_sets", "confirmed_by")
    op.drop_column("source_documents", "object_key")
