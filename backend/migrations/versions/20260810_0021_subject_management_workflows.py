"""add subject presentation and uploaded answer workflow fields

Revision ID: 20260810_0021
Revises: 20260810_0020
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0021"
down_revision: str | None = "20260810_0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column("icon", sa.Text(), nullable=False, server_default="book-open"),
    )
    op.add_column(
        "subjects",
        sa.Column("color", sa.Text(), nullable=False, server_default="#2F6FED"),
    )
    op.execute(
        "UPDATE subjects SET icon = 'chart-no-axes-combined', color = '#B45309' "
        "WHERE subject_code = '9640'"
    )
    op.execute(
        "UPDATE subjects SET icon = 'calculator', color = '#2563EB' WHERE subject_code = '9660'"
    )

    op.add_column(
        "paper_jobs",
        sa.Column("answer_mode", sa.Text(), nullable=False, server_default="generated"),
    )
    op.add_column("paper_jobs", sa.Column("answer_filename", sa.Text(), nullable=True))
    op.add_column("paper_jobs", sa.Column("answer_suffix", sa.Text(), nullable=True))
    op.add_column("paper_jobs", sa.Column("answer_source_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_jobs", "answer_source_path")
    op.drop_column("paper_jobs", "answer_suffix")
    op.drop_column("paper_jobs", "answer_filename")
    op.drop_column("paper_jobs", "answer_mode")
    op.drop_column("subjects", "color")
    op.drop_column("subjects", "icon")
