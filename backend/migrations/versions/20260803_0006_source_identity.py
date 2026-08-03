"""add stable source locations, versions, and pairing diagnostics

Revision ID: 20260803_0006
Revises: 20260803_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0006"
down_revision: str | None = "20260803_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_documents",
        sa.Column("identity_status", sa.Text(), nullable=False, server_default="not_applicable"),
    )
    op.add_column("source_documents", sa.Column("identity_error", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE source_documents
        SET identity_status = CASE
            WHEN source_type NOT IN ('question_paper','mark_scheme','examiner_report','insert')
                THEN 'not_applicable'
            WHEN pair_key IS NOT NULL THEN 'complete'
            ELSE 'incomplete'
        END,
        identity_error = CASE
            WHEN source_type IN ('question_paper','mark_scheme','examiner_report','insert')
                 AND pair_key IS NULL THEN 'legacy:identity_incomplete'
            ELSE NULL
        END
        """
    )
    op.create_index("idx_source_identity_status", "source_documents", ["identity_status"])
    op.create_table(
        "source_document_locations",
        sa.Column("path", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_source_locations_document", "source_document_locations", ["document_id", "present"]
    )
    op.create_table(
        "source_document_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "checksum"),
    )
    op.execute(
        """
        INSERT INTO source_document_locations
            (path, document_id, relative_path, present, first_seen_at, last_seen_at)
        SELECT path, id, COALESCE(metadata_json::jsonb->>'relative_path', filename),
               true, created_at, updated_at
        FROM source_documents
        ON CONFLICT (path) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO source_document_versions (id, document_id, checksum, size_bytes, created_at)
        SELECT id || ':' || LEFT(checksum, 16), id, checksum, 0, created_at
        FROM source_documents
        WHERE checksum <> ''
        ON CONFLICT (document_id, checksum) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("source_document_versions")
    op.drop_index("idx_source_locations_document", table_name="source_document_locations")
    op.drop_table("source_document_locations")
    op.drop_index("idx_source_identity_status", table_name="source_documents")
    op.drop_column("source_documents", "identity_error")
    op.drop_column("source_documents", "identity_status")
