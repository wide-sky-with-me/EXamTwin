from __future__ import annotations

import ipaddress
from contextlib import suppress
from dataclasses import dataclass

from qdrant_client import QdrantClient
from sqlalchemy import text

from examtwin.platform.config import Settings
from examtwin.platform.database.session import create_session_factory
from examtwin.platform.storage import build_storage_backend


@dataclass(frozen=True)
class InfrastructureHealth:
    postgresql: bool
    qdrant: bool
    object_storage: bool

    @property
    def available(self) -> bool:
        return self.postgresql and self.qdrant and self.object_storage


def access_boundary_warning(settings: Settings) -> str | None:
    if settings.local_access_only:
        return None
    host = settings.api_bind_host.strip().strip("[]")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.casefold() == "localhost"
    if loopback:
        return None
    return (
        "LOCAL_ACCESS_ONLY=false while API_BIND_HOST is non-loopback; "
        "the API has no authentication boundary"
    )


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
