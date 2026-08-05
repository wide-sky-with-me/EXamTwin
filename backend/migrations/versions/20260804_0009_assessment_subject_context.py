"""scope grading assessments to a subject context

Revision ID: 20260804_0009
Revises: 20260804_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0009"
down_revision: str | None = "20260804_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("subject_code", sa.Text(), nullable=True))
    # Every assessment predating multi-subject runtime selection was produced by the
    # only deployed 9660 context. Preserve it explicitly instead of leaving ambiguous rows.
    op.execute(sa.text("UPDATE assessments SET subject_code = '9660' WHERE subject_code IS NULL"))
    op.alter_column("assessments", "subject_code", nullable=False)
    op.create_index(
        "idx_assessments_subject_status",
        "assessments",
        ["subject_code", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_assessments_subject_status", table_name="assessments")
    op.drop_column("assessments", "subject_code")
