"""add user-managed display names for grading materials

Revision ID: 20260811_0022
Revises: 20260810_0021
Create Date: 2026-08-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0022"
down_revision: str | None = "20260810_0021"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("paper_jobs", sa.Column("display_name", sa.Text(), nullable=True))
    op.add_column("source_documents", sa.Column("display_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_documents", "display_name")
    op.drop_column("paper_jobs", "display_name")
