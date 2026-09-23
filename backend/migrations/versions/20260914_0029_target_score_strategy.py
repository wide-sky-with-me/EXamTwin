"""Persist target score requests and frozen strategy plans."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0029"
down_revision = "20260820_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_jobs", sa.Column("strategy_request_json", sa.Text(), nullable=True))
    op.add_column("paper_jobs", sa.Column("strategy_plan_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("paper_jobs", "strategy_plan_json")
    op.drop_column("paper_jobs", "strategy_request_json")
