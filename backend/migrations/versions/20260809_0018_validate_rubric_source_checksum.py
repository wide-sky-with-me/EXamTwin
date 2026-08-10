"""validate frozen rubric source-document checksums

Revision ID: 20260809_0018
Revises: 20260809_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0018"
down_revision: str | None = "20260809_0017"
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


def _validate_rubric_checksums(connection: sa.Connection) -> None:
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
            "Cannot validate rubric source-document checksum: integrity error for rubric "
            f"{missing['id']!r}; source document {missing['source_document_id']!r} has no "
            f"provable first-version interval at rubric creation time {missing['created_at']!s}"
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
            "Cannot validate rubric source-document checksum: integrity error for rubric "
            f"{ambiguous['id']!r}; source document {ambiguous['source_document_id']!r} has "
            f"a second distinct checksum first seen at {ambiguous['second_seen_at']!s}. "
            "First-seen checksum history cannot validate any stored checksum at rubric "
            f"creation time {ambiguous['created_at']!s}"
        )

    inconsistent = (
        connection.execute(
            sa.select(
                _RUBRIC_SETS.c.id,
                _RUBRIC_SETS.c.source_document_id,
                _RUBRIC_SETS.c.source_document_checksum,
                first_checksum.label("expected_checksum"),
            )
            .where(
                sa.or_(
                    _RUBRIC_SETS.c.source_document_checksum.is_(None),
                    _RUBRIC_SETS.c.source_document_checksum != first_checksum,
                )
            )
            .limit(1)
        )
        .mappings()
        .first()
    )
    if inconsistent is not None:
        raise RuntimeError(
            "Cannot validate rubric source-document checksum: integrity error for rubric "
            f"{inconsistent['id']!r}; source document "
            f"{inconsistent['source_document_id']!r} stores checksum "
            f"{inconsistent['source_document_checksum']!r}, expected the only provable "
            f"first-version checksum {inconsistent['expected_checksum']!r}"
        )


def upgrade() -> None:
    _validate_rubric_checksums(op.get_bind())


def downgrade() -> None:
    pass
