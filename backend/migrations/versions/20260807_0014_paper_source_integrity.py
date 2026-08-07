"""persist paper split source integrity and replacement lineage

Revision ID: 20260807_0014
Revises: 20260805_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0014"
down_revision: str | None = "20260805_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_jobs",
        sa.Column(
            "source_integrity_status",
            sa.Text(),
            nullable=False,
            server_default="legacy_unverified",
        ),
    )
    op.add_column(
        "paper_jobs",
        sa.Column("split_contract_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "paper_jobs",
        sa.Column("split_source_digest", sa.Text(), nullable=True),
    )
    op.add_column(
        "paper_jobs",
        sa.Column("replacement_for_job_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_paper_jobs_replacement_for_job_id",
        "paper_jobs",
        "paper_jobs",
        ["replacement_for_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_paper_jobs_replacement_for_job_id",
        "paper_jobs",
        ["replacement_for_job_id"],
    )
    op.add_column(
        "paper_job_questions",
        sa.Column("source_kind", sa.Text(), nullable=True),
    )
    op.add_column(
        "paper_job_questions",
        sa.Column("source_digest", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_job_questions", "source_digest")
    op.drop_column("paper_job_questions", "source_kind")
    op.drop_constraint(
        "uq_paper_jobs_replacement_for_job_id",
        "paper_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_paper_jobs_replacement_for_job_id",
        "paper_jobs",
        type_="foreignkey",
    )
    op.drop_column("paper_jobs", "replacement_for_job_id")
    op.drop_column("paper_jobs", "split_source_digest")
    op.drop_column("paper_jobs", "split_contract_version")
    op.drop_column("paper_jobs", "source_integrity_status")
