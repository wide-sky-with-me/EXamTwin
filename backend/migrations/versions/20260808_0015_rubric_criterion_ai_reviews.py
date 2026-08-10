"""add append-only rubric criterion AI reviews

Revision ID: 20260808_0015
Revises: 20260807_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0015"
down_revision: str | None = "20260807_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rubric_criterion_ai_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
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
        sa.Column("criterion_fingerprint", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("suggested_updates_json", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_rubric_criterion_ai_reviews_rubric_set_id",
        "rubric_criterion_ai_reviews",
        ["rubric_set_id"],
    )
    op.create_index(
        "ix_rubric_criterion_ai_reviews_criterion_latest",
        "rubric_criterion_ai_reviews",
        ["criterion_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_rubric_criterion_ai_reviews_criterion_latest",
        table_name="rubric_criterion_ai_reviews",
    )
    op.drop_index(
        "ix_rubric_criterion_ai_reviews_rubric_set_id",
        table_name="rubric_criterion_ai_reviews",
    )
    op.drop_table("rubric_criterion_ai_reviews")
