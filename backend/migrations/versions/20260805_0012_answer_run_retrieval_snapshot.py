"""record retrieval versions used by each answer run

Revision ID: 20260805_0012
Revises: 20260805_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0012"
down_revision: str | None = "20260805_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_agent_runs",
        sa.Column(
            "knowledge_base_version_ids_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "paper_agent_runs",
        sa.Column("graph_version_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_agent_runs", "graph_version_id")
    op.drop_column("paper_agent_runs", "knowledge_base_version_ids_json")
