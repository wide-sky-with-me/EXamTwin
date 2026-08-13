from datetime import UTC, datetime, timedelta
from importlib import import_module

import sqlalchemy as sa

migration = import_module("backend.migrations.versions.20260812_0024_paper_units")


def _schema() -> tuple[sa.Engine, sa.MetaData]:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "subjects",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("subject_code", sa.Text, nullable=False, unique=True),
    )
    sa.Table(
        "source_documents",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("subject_id", sa.Text),
        sa.Column("subject_code", sa.Text, nullable=False),
        sa.Column("pair_key", sa.Text),
        sa.Column("unit_code", sa.Text),
        sa.Column("exam_year", sa.Integer),
        sa.Column("exam_session", sa.Text),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("identity_status", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    sa.Table(
        "paper_units",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("subject_id", sa.Text, nullable=False),
        sa.Column("subject_code", sa.Text, nullable=False),
        sa.Column("pair_key", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text),
        sa.Column("unit_code", sa.Text, nullable=False),
        sa.Column("exam_year", sa.Integer, nullable=False),
        sa.Column("exam_session", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subject_id", "pair_key"),
    )
    sa.Table(
        "paper_unit_documents",
        metadata,
        sa.Column("paper_unit_id", sa.Text, primary_key=True),
        sa.Column("document_id", sa.Text, primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id"),
    )
    sa.Table(
        "paper_jobs",
        metadata,
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("subject_code", sa.Text, nullable=False),
        sa.Column("pair_key", sa.Text),
        sa.Column("paper_unit_id", sa.Text),
        sa.Column("question_paper_document_id", sa.Text),
    )
    metadata.create_all(engine)
    return engine, metadata


def test_backfill_preserves_duplicate_documents_and_links_legacy_jobs() -> None:
    engine, metadata = _schema()
    subjects = metadata.tables["subjects"]
    documents = metadata.tables["source_documents"]
    jobs = metadata.tables["paper_jobs"]
    now = datetime(2026, 8, 12, tzinfo=UTC)
    pair_key = "9660:2023:JUN:P1"
    document_rows = [
        {
            "id": document_id,
            "subject_id": subject_id,
            "subject_code": "9660",
            "pair_key": pair_key,
            "unit_code": "P1",
            "exam_year": 2023,
            "exam_session": "JUN",
            "source_type": source_type,
            "identity_status": "complete",
            "status": "converted",
            "created_at": now + timedelta(minutes=index),
            "updated_at": now + timedelta(minutes=index),
        }
        for index, (document_id, source_type, subject_id) in enumerate(
            (
                ("qp-primary", "question_paper", "subject-9660"),
                ("qp-second-source", "question_paper", None),
                ("ms", "mark_scheme", "subject-9660"),
                ("insert", "insert", "subject-9660"),
            )
        )
    ]
    document_rows.append(
        {
            **document_rows[2],
            "id": "deleted-ms",
            "status": "deleted",
        }
    )
    with engine.begin() as connection:
        connection.execute(subjects.insert(), {"id": "subject-9660", "subject_code": "9660"})
        connection.execute(documents.insert(), document_rows)
        connection.execute(
            jobs.insert(),
            {
                "id": "legacy-job",
                "subject_code": "9660",
                "pair_key": pair_key,
                "paper_unit_id": None,
                "question_paper_document_id": None,
            },
        )
        migration._backfill_paper_units(connection)

        units = connection.execute(sa.select(metadata.tables["paper_units"])).mappings().all()
        bindings = (
            connection.execute(
                sa.select(metadata.tables["paper_unit_documents"]).order_by(
                    metadata.tables["paper_unit_documents"].c.document_id
                )
            )
            .mappings()
            .all()
        )
        job = connection.execute(sa.select(jobs)).mappings().one()

    assert len(units) == 1
    assert units[0]["pair_key"] == pair_key
    assert [(row["document_id"], row["role"]) for row in bindings] == [
        ("insert", "source_booklet"),
        ("ms", "mark_scheme"),
        ("qp-primary", "question_paper"),
        ("qp-second-source", "question_paper"),
    ]
    assert job["paper_unit_id"] == units[0]["id"]
    assert job["question_paper_document_id"] is None


def test_backfill_ignores_incomplete_identity() -> None:
    engine, metadata = _schema()
    now = datetime(2026, 8, 12, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["subjects"].insert(),
            {"id": "subject-9660", "subject_code": "9660"},
        )
        connection.execute(
            metadata.tables["source_documents"].insert(),
            {
                "id": "incomplete",
                "subject_id": "subject-9660",
                "subject_code": "9660",
                "pair_key": None,
                "unit_code": "P1",
                "exam_year": None,
                "exam_session": None,
                "source_type": "question_paper",
                "identity_status": "incomplete",
                "status": "discovered",
                "created_at": now,
                "updated_at": now,
            },
        )
        migration._backfill_paper_units(connection)
        count = connection.scalar(
            sa.select(sa.func.count()).select_from(metadata.tables["paper_units"])
        )

    assert count == 0
