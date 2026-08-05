from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from examtwin.config import get_settings
from examtwin.persistence.models import Base
from examtwin.persistence.session import sqlalchemy_database_url
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None and not logging.getLogger().handlers:
    # Alembic CLI still gets its own logger. Embedded migrations must preserve the
    # API/Worker JSON handler installed before upgrade_database() is called.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def configured_database_url() -> str:
    """Keep the standard Alembic CLI usable without a duplicated URL in alembic.ini."""

    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    database_url = sqlalchemy_database_url(get_settings().database_url)
    config.set_main_option("sqlalchemy.url", database_url)
    return database_url


def run_migrations_offline() -> None:
    context.configure(
        url=configured_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configured_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
