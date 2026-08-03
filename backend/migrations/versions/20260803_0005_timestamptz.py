"""use native timestamptz for durable temporal state

Revision ID: 20260803_0005
Revises: 20260803_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0005"
down_revision: str | None = "20260803_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "source_documents": ("created_at", "updated_at"),
    "knowledge_build_runs": ("created_at", "updated_at", "completed_at"),
    "curriculum_candidates": ("created_at", "updated_at", "published_at"),
    "knowledge_points": ("updated_at",),
    "knowledge_evidence": ("created_at",),
    "difficulty_evidence": ("created_at",),
    "vector_index_build_runs": ("created_at", "updated_at", "published_at"),
    "vector_index_publications": ("updated_at",),
    "paper_jobs": (
        "lease_expires_at",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
    ),
    "paper_job_chunks": ("started_at", "completed_at"),
    "paper_job_questions": ("started_at", "completed_at"),
    "paper_agent_steps": ("created_at",),
    "question_difficulty": ("updated_at",),
    "assessments": ("created_at", "updated_at"),
    "reviews": ("created_at",),
}


def _require_parseable_values(table: str, column: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM "{table}"
                    WHERE "{column}" IS NOT NULL
                      AND NOT pg_input_is_valid("{column}", 'timestamp with time zone')
                ) THEN
                    RAISE EXCEPTION 'cannot migrate {table}.{column}: invalid timestamp text';
                END IF;
            END
            $$
            """
        )
    )


def upgrade() -> None:
    for table, columns in TIMESTAMP_COLUMNS.items():
        for column in columns:
            _require_parseable_values(table, column)
            op.alter_column(
                table,
                column,
                existing_type=sa.Text(),
                type_=sa.DateTime(timezone=True),
                postgresql_using=f'"{column}"::timestamptz',
            )


def downgrade() -> None:
    for table, columns in reversed(TIMESTAMP_COLUMNS.items()):
        for column in reversed(columns):
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.Text(),
                postgresql_using=f'"{column}"::text',
            )
