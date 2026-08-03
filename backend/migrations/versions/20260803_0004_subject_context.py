"""persist the subject boundary on durable paper jobs

Revision ID: 20260803_0004
Revises: 20260803_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0004"
down_revision: str | None = "20260803_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_jobs",
        sa.Column(
            "subject_pack_id",
            sa.Text(),
            nullable=False,
            server_default="oxfordaqa-mathematics-9660",
        ),
    )
    op.add_column(
        "paper_jobs",
        sa.Column("subject_code", sa.Text(), nullable=False, server_default="9660"),
    )
    op.alter_column("paper_jobs", "subject_pack_id", server_default=None)
    op.alter_column("paper_jobs", "subject_code", server_default=None)
    op.create_index("idx_paper_jobs_subject", "paper_jobs", ["subject_code", "created_at"])
    op.add_column("knowledge_evidence", sa.Column("build_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_evidence_build",
        "knowledge_evidence",
        "vector_index_build_runs",
        ["build_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # PostgreSQL truncates the unnamed baseline constraint to 63 characters.
    # Use the actual catalog name, and also accept the short downgrade name so
    # upgrade -> downgrade -> upgrade remains reversible.
    op.execute(
        sa.text(
            "ALTER TABLE knowledge_evidence DROP CONSTRAINT IF EXISTS "
            '"knowledge_evidence_knowledge_point_id_source_document_id_pa_key"'
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE knowledge_evidence DROP CONSTRAINT IF EXISTS "
            '"uq_knowledge_evidence_source"'
        )
    )
    op.create_unique_constraint(
        "uq_knowledge_evidence_version",
        "knowledge_evidence",
        [
            "knowledge_point_id",
            "source_document_id",
            "page",
            "section",
            "content_hash",
            "build_id",
        ],
    )
    op.create_index("idx_knowledge_evidence_build", "knowledge_evidence", ["build_id"])
    op.create_table(
        "vector_index_publications",
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("alias_name", sa.Text(), nullable=False),
        sa.Column("active_build_id", sa.Text(), nullable=False),
        sa.Column("collection_name", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["active_build_id"], ["vector_index_build_runs.id"]),
        sa.PrimaryKeyConstraint("subject_code"),
        sa.UniqueConstraint("alias_name"),
    )


def downgrade() -> None:
    op.drop_table("vector_index_publications")
    op.drop_index("idx_knowledge_evidence_build", table_name="knowledge_evidence")
    op.drop_constraint("uq_knowledge_evidence_version", "knowledge_evidence", type_="unique")
    op.create_unique_constraint(
        "uq_knowledge_evidence_source",
        "knowledge_evidence",
        ["knowledge_point_id", "source_document_id", "page", "section", "content_hash"],
    )
    op.drop_constraint(
        "fk_knowledge_evidence_build",
        "knowledge_evidence",
        type_="foreignkey",
    )
    op.drop_column("knowledge_evidence", "build_id")
    op.drop_index("idx_paper_jobs_subject", table_name="paper_jobs")
    op.drop_column("paper_jobs", "subject_code")
    op.drop_column("paper_jobs", "subject_pack_id")
