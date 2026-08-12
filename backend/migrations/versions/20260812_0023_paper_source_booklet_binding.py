"""freeze exact-pair source booklets on paper jobs

Revision ID: 20260812_0023
Revises: 20260811_0022
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0023"
down_revision: str | None = "20260811_0022"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("paper_jobs", sa.Column("pair_key", sa.Text(), nullable=True))
    op.add_column(
        "paper_jobs",
        sa.Column(
            "source_booklet_document_id",
            sa.Text(),
            sa.ForeignKey("source_documents.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("paper_jobs", sa.Column("source_booklet_checksum", sa.Text(), nullable=True))
    op.add_column("paper_jobs", sa.Column("source_booklet_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_jobs", "source_booklet_filename")
    op.drop_column("paper_jobs", "source_booklet_checksum")
    op.drop_column("paper_jobs", "source_booklet_document_id")
    op.drop_column("paper_jobs", "pair_key")
