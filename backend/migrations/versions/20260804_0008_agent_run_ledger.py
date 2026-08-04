"""add durable answering agent run ledger

Revision ID: 20260804_0008
Revises: 20260803_0007
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0008"
down_revision: str | None = "20260803_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_agent_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("paper_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_position", sa.Integer(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("package_id", sa.Text(), nullable=False),
        sa.Column("package_version", sa.Text(), nullable=False),
        sa.Column("package_digest", sa.Text(), nullable=False),
        sa.Column("skill_digest", sa.Text(), nullable=False),
        sa.Column("prompt_digest", sa.Text(), nullable=False),
        sa.Column("model_name", sa.Text(), nullable=False),
        sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("max_tool_calls", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "question_position", "run_attempt"),
    )
    op.create_table(
        "paper_agent_tool_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("paper_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_position", sa.Integer(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("call_key", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("input_digest", sa.Text(), nullable=False),
        sa.Column("execution_fingerprint", sa.Text(), nullable=False),
        sa.Column("replay_safe", sa.Boolean(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result_digest", sa.Text()),
        sa.Column("replay_json", sa.Text()),
        sa.Column("error_type", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "question_position", "run_attempt", "call_key"),
    )
    op.create_index(
        "idx_paper_agent_tool_replay",
        "paper_agent_tool_calls",
        [
            "job_id",
            "question_position",
            "call_key",
            "execution_fingerprint",
            "status",
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_paper_agent_tool_replay", table_name="paper_agent_tool_calls")
    op.drop_table("paper_agent_tool_calls")
    op.drop_table("paper_agent_runs")
