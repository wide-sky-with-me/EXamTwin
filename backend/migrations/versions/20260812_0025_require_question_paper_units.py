"""remove paper units without an active question paper

Revision ID: 20260812_0025
Revises: 20260812_0024
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0025"
down_revision: str | None = "20260812_0024"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    connection = op.get_bind()
    orphan_ids = connection.scalars(
        sa.text(
            """
            SELECT pu.id
            FROM paper_units AS pu
            WHERE NOT EXISTS (
                SELECT 1
                FROM paper_unit_documents AS pud
                JOIN source_documents AS d ON d.id = pud.document_id
                WHERE pud.paper_unit_id = pu.id
                  AND pud.role = 'question_paper'
                  AND d.source_type = 'question_paper'
                  AND d.status <> 'deleted'
            )
            """
        )
    ).all()
    if not orphan_ids:
        return
    linked_jobs = int(
        connection.scalar(
            sa.text(
                """
                SELECT count(*) FROM paper_jobs
                WHERE paper_unit_id IN :paper_unit_ids
                """
            ).bindparams(sa.bindparam("paper_unit_ids", expanding=True)),
            {"paper_unit_ids": orphan_ids},
        )
        or 0
    )
    if linked_jobs:
        raise RuntimeError("paper unit without Question Paper is referenced by paper jobs")
    connection.execute(
        sa.text("DELETE FROM paper_units WHERE id IN :paper_unit_ids").bindparams(
            sa.bindparam("paper_unit_ids", expanding=True)
        ),
        {"paper_unit_ids": orphan_ids},
    )


def downgrade() -> None:
    # Removed invalid aggregate rows cannot be reconstructed without violating the invariant.
    pass
