"""bind converted Markdown to its source checksum

Revision ID: 20260809_0017
Revises: 20260809_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0017"
down_revision: str | None = "20260809_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("converted_source_checksum", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_documents", "converted_source_checksum")
