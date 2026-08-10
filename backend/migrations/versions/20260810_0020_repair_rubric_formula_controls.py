"""repair control-character corruption in rubric formula text

Revision ID: 20260810_0020
Revises: 20260810_0019
"""

from __future__ import annotations

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0020"
down_revision: str | None = "20260810_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUBRIC_CRITERIA = sa.table(
    "rubric_criteria",
    sa.column("id", sa.Text()),
    sa.column("description", sa.Text()),
    sa.column("accuracy_requirement", sa.Text()),
    sa.column("follow_through_policy", sa.Text()),
    sa.column("source_excerpt", sa.Text()),
)
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TEXT_COLUMNS = (
    "description",
    "accuracy_requirement",
    "follow_through_policy",
    "source_excerpt",
)


def _repair_formula_text(value: str | None) -> str | None:
    if value is None:
        return None
    repaired = value.replace("\x1b[mathbf", r"\mathbf")
    if _CONTROL_CHARACTER.search(repaired):
        raise RuntimeError("rubric criterion contains an unsupported control character")
    return repaired


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.select(_RUBRIC_CRITERIA)).mappings().all()
    for row in rows:
        updates = {
            column: repaired
            for column in _TEXT_COLUMNS
            if (repaired := _repair_formula_text(row[column])) != row[column]
        }
        if not updates:
            continue
        connection.execute(
            sa.update(_RUBRIC_CRITERIA).where(_RUBRIC_CRITERIA.c.id == row["id"]).values(**updates)
        )


def downgrade() -> None:
    pass
