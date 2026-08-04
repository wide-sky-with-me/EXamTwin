from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass

from examtwin.config import Settings
from examtwin.persistence.session import create_session_factory
from examtwin.storage import build_storage_backend
from qdrant_client import QdrantClient
from sqlalchemy import text


@dataclass(frozen=True)
class InfrastructureHealth:
    postgresql: bool
    qdrant: bool
    object_storage: bool

    @property
    def available(self) -> bool:
        return self.postgresql and self.qdrant and self.object_storage


def _postgresql_available(settings: Settings) -> bool:
    try:
        with create_session_factory(settings.database_url)() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _qdrant_available(settings: Settings) -> bool:
    client: QdrantClient | None = None
    try:
        client = QdrantClient(url=settings.qdrant_url, timeout=2)
        client.get_collections()
        return True
    except Exception:
        return False
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


def _object_storage_available(settings: Settings) -> bool:
    try:
        build_storage_backend(settings).ping()
        return True
    except Exception:
        return False


def infrastructure_health(settings: Settings) -> InfrastructureHealth:
    return InfrastructureHealth(
        postgresql=_postgresql_available(settings),
        qdrant=_qdrant_available(settings),
        object_storage=_object_storage_available(settings),
    )
