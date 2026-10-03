"""Align the seeded Economics colour with its subject manifest.

Migration 0021 seeded 9640 with #B45309 while the manifest declares #0F766E, and installed
subject synchronisation preserves stored presentation. Only rows still holding the original
seed are updated, so colours chosen by users are kept.
"""

from alembic import op

revision = "20261003_0030"
down_revision = "20260914_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE subjects SET color = '#0F766E' "
        "WHERE subject_code = '9640' AND upper(color) = '#B45309'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE subjects SET color = '#B45309' "
        "WHERE subject_code = '9640' AND upper(color) = '#0F766E'"
    )
