"""add object storage lifecycle catalog

Revision ID: 20260803_0007
Revises: 20260803_0006
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0007"
down_revision: str | None = "20260803_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stored_objects",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("storage_backend", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text()),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.CheckConstraint(
            "state IN ('active', 'deleting', 'delete_failed', 'deleted')",
            name="ck_stored_objects_state",
        ),
    )
    op.create_index(
        "idx_stored_objects_gc",
        "stored_objects",
        ["state", "retain_until", "updated_at"],
    )
    op.create_index(
        "idx_stored_objects_owner",
        "stored_objects",
        ["owner_type", "owner_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_stored_objects_owner", table_name="stored_objects")
    op.drop_index("idx_stored_objects_gc", table_name="stored_objects")
    op.drop_table("stored_objects")
