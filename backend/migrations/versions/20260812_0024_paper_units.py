"""introduce explicit paper units and document bindings

Revision ID: 20260812_0024
Revises: 20260812_0023
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0024"
down_revision: str | None = "20260812_0023"
branch_labels: str | None = None
depends_on: str | None = None

_ROLE_BY_SOURCE_TYPE = {
    "question_paper": "question_paper",
    "mark_scheme": "mark_scheme",
    "insert": "source_booklet",
}


def _paper_unit_id(subject_id: str, pair_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"examtwin:paper-unit:{subject_id}:{pair_key}"))


def _backfill_paper_units(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            """
            SELECT
                d.id AS document_id,
                COALESCE(d.subject_id, s.id) AS subject_id,
                d.subject_code,
                d.pair_key,
                d.unit_code,
                d.exam_year,
                d.exam_session,
                d.source_type,
                d.created_at,
                d.updated_at
            FROM source_documents AS d
            JOIN subjects AS s ON s.subject_code = d.subject_code
            WHERE d.status <> 'deleted'
              AND d.identity_status = 'complete'
              AND d.pair_key IS NOT NULL
              AND d.source_type IN ('question_paper', 'mark_scheme', 'insert')
            ORDER BY COALESCE(d.subject_id, s.id), d.pair_key, d.source_type, d.id
            """
        )
    ).mappings()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["subject_id"]), str(row["pair_key"]))].append(dict(row))

    for (subject_id, pair_key), documents in grouped.items():
        first = documents[0]
        if not any(document["source_type"] == "question_paper" for document in documents):
            continue
        if (
            first["unit_code"] is None
            or first["exam_year"] is None
            or first["exam_session"] is None
        ):
            raise RuntimeError(f"complete exam identity is missing fields: {pair_key}")
        paper_unit_id = _paper_unit_id(subject_id, pair_key)
        created_at = min(document["created_at"] for document in documents)
        updated_at = max(document["updated_at"] for document in documents)
        connection.execute(
            sa.text(
                """
                INSERT INTO paper_units (
                    id, subject_id, subject_code, pair_key, display_name,
                    unit_code, exam_year, exam_session, status, created_at, updated_at
                ) VALUES (
                    :id, :subject_id, :subject_code, :pair_key, NULL,
                    :unit_code, :exam_year, :exam_session, 'active', :created_at, :updated_at
                )
                """
            ),
            {
                "id": paper_unit_id,
                "subject_id": subject_id,
                "subject_code": str(first["subject_code"]),
                "pair_key": pair_key,
                "unit_code": str(first["unit_code"]),
                "exam_year": int(first["exam_year"]),
                "exam_session": str(first["exam_session"]),
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO paper_unit_documents (
                    paper_unit_id, document_id, role, created_at
                ) VALUES (
                    :paper_unit_id, :document_id, :role, :created_at
                )
                """
            ),
            [
                {
                    "paper_unit_id": paper_unit_id,
                    "document_id": str(document["document_id"]),
                    "role": _ROLE_BY_SOURCE_TYPE[str(document["source_type"])],
                    "created_at": document["created_at"],
                }
                for document in documents
            ],
        )

    for subject_id, pair_key in grouped:
        connection.execute(
            sa.text(
                """
                UPDATE paper_jobs
                SET paper_unit_id = :paper_unit_id
                WHERE subject_code = (
                    SELECT subject_code FROM paper_units WHERE id = :paper_unit_id
                )
                  AND pair_key = :pair_key
                  AND paper_unit_id IS NULL
                """
            ),
            {
                "paper_unit_id": _paper_unit_id(subject_id, pair_key),
                "pair_key": pair_key,
            },
        )


def upgrade() -> None:
    op.create_table(
        "paper_units",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("subject_code", sa.Text(), nullable=False),
        sa.Column("pair_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("unit_code", sa.Text(), nullable=False),
        sa.Column("exam_year", sa.Integer(), nullable=False),
        sa.Column("exam_session", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "pair_key"),
    )
    op.create_index(
        "idx_paper_units_subject_status",
        "paper_units",
        ["subject_id", "status", "updated_at"],
    )
    op.create_table(
        "paper_unit_documents",
        sa.Column("paper_unit_id", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_unit_id"], ["paper_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["source_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("paper_unit_id", "document_id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index(
        "idx_paper_unit_documents_role",
        "paper_unit_documents",
        ["paper_unit_id", "role"],
    )
    op.add_column("paper_jobs", sa.Column("paper_unit_id", sa.Text(), nullable=True))
    op.add_column(
        "paper_jobs",
        sa.Column("question_paper_document_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_paper_jobs_paper_unit_id",
        "paper_jobs",
        "paper_units",
        ["paper_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_paper_jobs_question_paper_document_id",
        "paper_jobs",
        "source_documents",
        ["question_paper_document_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("idx_paper_jobs_paper_unit", "paper_jobs", ["paper_unit_id"])
    _backfill_paper_units(op.get_bind())


def downgrade() -> None:
    op.drop_index("idx_paper_jobs_paper_unit", table_name="paper_jobs")
    op.drop_constraint("fk_paper_jobs_question_paper_document_id", "paper_jobs", type_="foreignkey")
    op.drop_constraint("fk_paper_jobs_paper_unit_id", "paper_jobs", type_="foreignkey")
    op.drop_column("paper_jobs", "question_paper_document_id")
    op.drop_column("paper_jobs", "paper_unit_id")
    op.drop_index("idx_paper_unit_documents_role", table_name="paper_unit_documents")
    op.drop_table("paper_unit_documents")
    op.drop_index("idx_paper_units_subject_status", table_name="paper_units")
    op.drop_table("paper_units")
