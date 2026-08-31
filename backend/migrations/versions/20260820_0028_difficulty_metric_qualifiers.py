"""add difficulty metric qualifiers

Revision ID: 20260820_0028
Revises: 20260820_0027
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0028"
down_revision: str | None = "20260820_0027"
branch_labels: str | None = None
depends_on: str | None = None


def _shape_constraint(*, include_comparator: bool) -> str:
    comparator_b = "AND metric_comparator IS NULL " if include_comparator else ""
    comparator_a = (
        "AND metric_comparator IN ('eq', 'approx', 'gt', 'gte', 'lt', 'lte') "
        if include_comparator
        else ""
    )
    return (
        "(evidence_level = 'B' AND evidence_type = 'qualitative' "
        "AND metric_name IS NULL AND metric_text IS NULL AND metric_value IS NULL "
        f"AND metric_scale IS NULL AND metric_direction IS NULL {comparator_b}"
        "AND difficulty_score IS NULL) OR "
        "(evidence_level = 'A' AND evidence_type = 'quantitative' "
        "AND metric_name IS NOT NULL AND metric_text IS NOT NULL "
        "AND metric_value IS NOT NULL AND metric_scale IS NOT NULL "
        f"AND metric_direction IS NOT NULL {comparator_a})"
    )


def upgrade() -> None:
    op.drop_constraint(
        "ck_difficulty_candidate_level_shape",
        "difficulty_evidence_candidates",
        type_="check",
    )
    op.add_column(
        "difficulty_evidence_candidates",
        sa.Column("metric_comparator", sa.Text()),
    )
    op.execute(
        "UPDATE difficulty_evidence_candidates SET metric_comparator = CASE "
        "WHEN lower(metric_text) LIKE ANY (ARRAY['%approximately%', '%around%', "
        "'%about%', '%nearly%', '%close to%', '%~%']) THEN 'approx' "
        "WHEN lower(metric_text) LIKE ANY (ARRAY['%at least%', '%or more%', '%>=%']) THEN 'gte' "
        "WHEN lower(metric_text) LIKE ANY (ARRAY['%more than%', '%over %', '%>%']) THEN 'gt' "
        "WHEN lower(metric_text) LIKE ANY (ARRAY['%at most%', '%or less%', '%<=%']) THEN 'lte' "
        "WHEN lower(metric_text) LIKE ANY (ARRAY['%less than%', '%under %', '%<%']) THEN 'lt' "
        "ELSE 'eq' END WHERE evidence_level = 'A'"
    )
    op.execute(
        "UPDATE difficulty_evidence_candidates SET difficulty_score = NULL "
        "WHERE metric_comparator <> 'eq'"
    )
    op.execute(
        "UPDATE question_difficulty AS projection "
        "SET difficulty_score = NULL, difficulty_label = NULL "
        "FROM difficulty_evidence_candidates AS candidate "
        "WHERE projection.publication_run_id = candidate.run_id "
        "AND projection.question_number = candidate.question_number "
        "AND candidate.metric_comparator <> 'eq'"
    )
    op.create_check_constraint(
        "ck_difficulty_candidate_level_shape",
        "difficulty_evidence_candidates",
        _shape_constraint(include_comparator=True),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_difficulty_candidate_level_shape",
        "difficulty_evidence_candidates",
        type_="check",
    )
    op.drop_column("difficulty_evidence_candidates", "metric_comparator")
    op.create_check_constraint(
        "ck_difficulty_candidate_level_shape",
        "difficulty_evidence_candidates",
        _shape_constraint(include_comparator=False),
    )
