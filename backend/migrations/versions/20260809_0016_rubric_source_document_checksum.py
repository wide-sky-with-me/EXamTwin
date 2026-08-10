"""freeze rubric source-document checksum

Revision ID: 20260809_0016
Revises: 20260808_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0016"
down_revision: str | None = "20260808_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RUBRIC_SETS = sa.table(
    "rubric_sets",
    sa.column("id", sa.Text()),
    sa.column("source_document_id", sa.Text()),
    sa.column("source_document_checksum", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_SOURCE_DOCUMENT_VERSIONS = sa.table(
    "source_document_versions",
    sa.column("document_id", sa.Text()),
    sa.column("checksum", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def _ordered_first_seen_versions() -> sa.Subquery:
    first_seen_versions = (
        sa.select(
            _SOURCE_DOCUMENT_VERSIONS.c.document_id,
            _SOURCE_DOCUMENT_VERSIONS.c.checksum,
            sa.func.min(_SOURCE_DOCUMENT_VERSIONS.c.created_at).label("first_seen_at"),
        )
        .group_by(
            _SOURCE_DOCUMENT_VERSIONS.c.document_id,
            _SOURCE_DOCUMENT_VERSIONS.c.checksum,
        )
        .subquery("first_seen_versions")
    )
    return sa.select(
        first_seen_versions,
        sa.func.row_number()
        .over(
            partition_by=first_seen_versions.c.document_id,
            order_by=(
                first_seen_versions.c.first_seen_at,
                first_seen_versions.c.checksum,
            ),
        )
        .label("version_position"),
    ).subquery("ordered_first_seen_versions")


def _backfill_rubric_checksums(connection: sa.Connection) -> None:
    ordered_versions = _ordered_first_seen_versions()
    first_version = ordered_versions.alias("first_version")
    second_version = ordered_versions.alias("second_version")

    first_checksum = (
        sa.select(first_version.c.checksum)
        .where(
            first_version.c.document_id == _RUBRIC_SETS.c.source_document_id,
            first_version.c.version_position == 1,
        )
        .correlate(_RUBRIC_SETS)
        .scalar_subquery()
    )
    first_seen_at = (
        sa.select(first_version.c.first_seen_at)
        .where(
            first_version.c.document_id == _RUBRIC_SETS.c.source_document_id,
            first_version.c.version_position == 1,
        )
        .correlate(_RUBRIC_SETS)
        .scalar_subquery()
    )
    second_seen_at = (
        sa.select(second_version.c.first_seen_at)
        .where(
            second_version.c.document_id == _RUBRIC_SETS.c.source_document_id,
            second_version.c.version_position == 2,
        )
        .correlate(_RUBRIC_SETS)
        .scalar_subquery()
    )

    missing = (
        connection.execute(
            sa.select(
                _RUBRIC_SETS.c.id,
                _RUBRIC_SETS.c.source_document_id,
                _RUBRIC_SETS.c.created_at,
            )
            .where(
                sa.or_(
                    first_seen_at.is_(None),
                    _RUBRIC_SETS.c.created_at < first_seen_at,
                )
            )
            .limit(1)
        )
        .mappings()
        .first()
    )
    if missing is not None:
        raise RuntimeError(
            "Cannot backfill rubric source-document checksum: integrity error for rubric "
            f"{missing['id']!r}; source document {missing['source_document_id']!r} has no "
            f"first-seen version at or before rubric creation time {missing['created_at']!s}"
        )

    ambiguous = (
        connection.execute(
            sa.select(
                _RUBRIC_SETS.c.id,
                _RUBRIC_SETS.c.source_document_id,
                _RUBRIC_SETS.c.created_at,
                second_seen_at.label("second_seen_at"),
            )
            .where(
                second_seen_at.is_not(None),
                _RUBRIC_SETS.c.created_at >= second_seen_at,
            )
            .limit(1)
        )
        .mappings()
        .first()
    )
    if ambiguous is not None:
        raise RuntimeError(
            "Cannot backfill rubric source-document checksum: integrity error for rubric "
            f"{ambiguous['id']!r}; source document {ambiguous['source_document_id']!r} has "
            f"a second distinct checksum first seen at {ambiguous['second_seen_at']!s}. "
            "First-seen checksum history cannot establish the active checksum at rubric "
            f"creation time {ambiguous['created_at']!s}"
        )

    connection.execute(sa.update(_RUBRIC_SETS).values(source_document_checksum=first_checksum))

    unresolved = connection.execute(
        sa.select(_RUBRIC_SETS.c.id)
        .where(_RUBRIC_SETS.c.source_document_checksum.is_(None))
        .limit(1)
    ).scalar_one_or_none()
    if unresolved is not None:
        raise RuntimeError(
            "Cannot backfill rubric source-document checksum: integrity error left rubric "
            f"{unresolved!r} unresolved"
        )


def upgrade() -> None:
    op.add_column(
        "rubric_sets",
        sa.Column("source_document_checksum", sa.Text(), nullable=True),
    )
    _backfill_rubric_checksums(op.get_bind())
    op.alter_column("rubric_sets", "source_document_checksum", nullable=False)


def downgrade() -> None:
    op.drop_column("rubric_sets", "source_document_checksum")
