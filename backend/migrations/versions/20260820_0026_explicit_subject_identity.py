"""require explicit subject identity on knowledge writes

Revision ID: 20260820_0026
Revises: 20260812_0025
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0026"
down_revision: str | None = "20260812_0025"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column(
        "source_documents",
        "subject_code",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=None,
    )
    op.alter_column(
        "knowledge_points",
        "subject_code",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    legacy_default = sa.text("'9660'")
    op.alter_column(
        "knowledge_points",
        "subject_code",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=legacy_default,
    )
    op.alter_column(
        "source_documents",
        "subject_code",
        existing_type=sa.Text(),
        existing_nullable=False,
        server_default=legacy_default,
    )
