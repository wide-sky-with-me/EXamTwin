from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def utcnow() -> datetime:
    return datetime.now(UTC)


def sqlalchemy_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache(maxsize=8)
def create_session_factory(database_url: str) -> sessionmaker[Session]:
    engine: Engine = create_engine(
        sqlalchemy_database_url(database_url),
        pool_pre_ping=True,
    )
    return sessionmaker(bind=engine, expire_on_commit=False)
