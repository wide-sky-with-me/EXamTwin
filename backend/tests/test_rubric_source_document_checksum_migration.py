from datetime import UTC, datetime, timedelta
from importlib import import_module

import pytest
import sqlalchemy as sa

backfill_migration = import_module(
    "backend.migrations.versions.20260809_0016_rubric_source_document_checksum"
)
validation_migration = import_module(
    "backend.migrations.versions.20260809_0018_validate_rubric_source_checksum"
)

_BASE_TIME = datetime(2026, 8, 1, 10, tzinfo=UTC)
_CHECKSUMS = {
    "A": "checksum-a",
    "B": "checksum-b",
}


def _schema() -> tuple[sa.Engine, sa.Table, sa.Table, sa.Table]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    source_documents = sa.Table(
        "source_documents",
        metadata,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    source_document_versions = sa.Table(
        "source_document_versions",
        metadata,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("checksum", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "checksum"),
    )
    rubric_sets = sa.Table(
        "rubric_sets",
        metadata,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("source_document_id", sa.Text(), nullable=False),
        sa.Column("source_document_checksum", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    return engine, source_documents, source_document_versions, rubric_sets


def _insert_history(
    connection: sa.Connection,
    source_documents: sa.Table,
    versions: sa.Table,
    rubrics: sa.Table,
    *,
    transitions: tuple[str, ...],
    rubric_created_at: datetime,
    stored_checksum: str | None = None,
) -> None:
    connection.execute(
        source_documents.insert(),
        {
            "id": "mark-scheme",
            "checksum": _CHECKSUMS[transitions[-1]],
            "updated_at": _BASE_TIME + timedelta(hours=2 * len(transitions)),
        },
    )

    first_seen: dict[str, datetime] = {}
    for position, checksum_name in enumerate(transitions):
        first_seen.setdefault(
            checksum_name,
            _BASE_TIME + timedelta(hours=2 * position),
        )
    connection.execute(
        versions.insert(),
        [
            {
                "id": f"version-{checksum_name.lower()}",
                "document_id": "mark-scheme",
                "checksum": _CHECKSUMS[checksum_name],
                "created_at": created_at,
            }
            for checksum_name, created_at in first_seen.items()
        ],
    )
    connection.execute(
        rubrics.insert(),
        {
            "id": "rubric",
            "source_document_id": "mark-scheme",
            "source_document_checksum": stored_checksum,
            "created_at": rubric_created_at,
        },
    )


@pytest.mark.parametrize(
    ("transitions", "rubric_created_at"),
    [
        pytest.param(("A", "B"), _BASE_TIME + timedelta(hours=2), id="A-to-B-boundary"),
        pytest.param(("A", "B"), _BASE_TIME + timedelta(hours=3), id="A-to-B"),
        pytest.param(("A", "B", "A"), _BASE_TIME + timedelta(hours=5), id="A-to-B-to-A"),
        pytest.param(
            ("A", "B", "A", "B"),
            _BASE_TIME + timedelta(hours=7),
            id="A-to-B-to-A-to-B",
        ),
    ],
)
def test_backfill_rejects_every_rubric_at_or_after_second_distinct_version(
    transitions: tuple[str, ...],
    rubric_created_at: datetime,
) -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=transitions,
            rubric_created_at=rubric_created_at,
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "integrity error for rubric 'rubric'.*second distinct checksum first seen.*"
                "cannot establish the active checksum"
            ),
        ):
            backfill_migration._backfill_rubric_checksums(connection)


def test_backfill_uses_first_checksum_before_second_distinct_version() -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=("A", "B", "A", "B"),
            rubric_created_at=_BASE_TIME + timedelta(hours=1),
        )

        backfill_migration._backfill_rubric_checksums(connection)

        checksum = connection.execute(
            sa.select(rubrics.c.source_document_checksum).where(rubrics.c.id == "rubric")
        ).scalar_one()

    assert checksum == _CHECKSUMS["A"]


def test_backfill_uses_only_checksum_for_single_version_document() -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=("A",),
            rubric_created_at=_BASE_TIME + timedelta(days=30),
        )

        backfill_migration._backfill_rubric_checksums(connection)

        checksum = connection.execute(
            sa.select(rubrics.c.source_document_checksum).where(rubrics.c.id == "rubric")
        ).scalar_one()

    assert checksum == _CHECKSUMS["A"]


def test_backfill_rejects_rubric_before_first_seen_version() -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=("A",),
            rubric_created_at=_BASE_TIME - timedelta(hours=1),
        )

        with pytest.raises(
            RuntimeError,
            match="has no first-seen version at or before rubric creation time",
        ):
            backfill_migration._backfill_rubric_checksums(connection)


@pytest.mark.parametrize(
    ("transitions", "rubric_created_at", "stored_checksum"),
    [
        pytest.param(
            ("A", "B"),
            _BASE_TIME + timedelta(hours=3),
            _CHECKSUMS["B"],
            id="old-false-B-backfill",
        ),
        pytest.param(
            ("A", "B", "A"),
            _BASE_TIME + timedelta(hours=5),
            _CHECKSUMS["A"],
            id="A-to-B-to-A",
        ),
        pytest.param(
            ("A", "B", "A", "B"),
            _BASE_TIME + timedelta(hours=7),
            _CHECKSUMS["B"],
            id="A-to-B-to-A-to-B",
        ),
    ],
)
def test_validation_rejects_old_backfills_at_or_after_second_distinct_version(
    transitions: tuple[str, ...],
    rubric_created_at: datetime,
    stored_checksum: str,
) -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=transitions,
            rubric_created_at=rubric_created_at,
            stored_checksum=stored_checksum,
        )

        with pytest.raises(
            RuntimeError,
            match=(
                "integrity error for rubric 'rubric'.*second distinct checksum first seen.*"
                "cannot validate any stored checksum"
            ),
        ):
            validation_migration._validate_rubric_checksums(connection)


def test_validation_accepts_first_checksum_before_second_distinct_version() -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=("A", "B", "A", "B"),
            rubric_created_at=_BASE_TIME + timedelta(hours=1),
            stored_checksum=_CHECKSUMS["A"],
        )

        validation_migration._validate_rubric_checksums(connection)


def test_validation_rejects_wrong_checksum_in_first_version_interval() -> None:
    engine, source_documents, versions, rubrics = _schema()

    with engine.begin() as connection:
        _insert_history(
            connection,
            source_documents,
            versions,
            rubrics,
            transitions=("A", "B"),
            rubric_created_at=_BASE_TIME + timedelta(hours=1),
            stored_checksum=_CHECKSUMS["B"],
        )

        with pytest.raises(
            RuntimeError,
            match="stores checksum 'checksum-b'.*first-version checksum 'checksum-a'",
        ):
            validation_migration._validate_rubric_checksums(connection)
