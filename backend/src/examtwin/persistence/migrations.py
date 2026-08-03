from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from examtwin.persistence.session import sqlalchemy_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def upgrade_database(database_url: str, revision: str = "head") -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "backend/migrations"))
    config.set_main_option("sqlalchemy.url", sqlalchemy_database_url(database_url))
    command.upgrade(config, revision)
