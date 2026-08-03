from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import psycopg

TASK_EVENT_CHANNEL = "examtwin_task_events"


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(frozen=True)
class TaskEvent:
    topic: str
    resource_id: str


class PostgresTaskEvents:
    """Cross-process task notifications backed by PostgreSQL LISTEN/NOTIFY."""

    def __init__(self, database_url: str):
        self.database_url = _psycopg_url(database_url)

    @asynccontextmanager
    async def subscribe(
        self,
        topic: str,
        resource_id: str,
    ) -> AsyncIterator[AsyncIterator[TaskEvent]]:
        connection = await psycopg.AsyncConnection.connect(
            self.database_url,
            autocommit=True,
        )
        try:
            await connection.execute(f"LISTEN {TASK_EVENT_CHANNEL}")
            yield self._matching_events(connection, topic, resource_id)
        finally:
            await connection.close()

    async def _matching_events(
        self,
        connection: psycopg.AsyncConnection[object],
        topic: str,
        resource_id: str,
    ) -> AsyncIterator[TaskEvent]:
        async for notification in connection.notifies():
            try:
                payload = json.loads(notification.payload)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("topic") != topic or payload.get("resource_id") != resource_id:
                continue
            yield TaskEvent(topic=topic, resource_id=resource_id)


class PaperJobWakeup(Protocol):
    """Wait until a paper-job event arrives or the fallback interval elapses."""

    def wait(self, timeout_seconds: float) -> None: ...


class SleepPaperJobWakeup:
    """Portable fallback used when no cross-process notifier is configured."""

    def wait(self, timeout_seconds: float) -> None:
        import time

        time.sleep(timeout_seconds)


class PostgresPaperJobWakeup:
    """Wake idle workers from PostgreSQL NOTIFY while durable rows remain the queue."""

    def __init__(self, database_url: str) -> None:
        self.database_url = _psycopg_url(database_url)
        self._connection: psycopg.Connection[object] | None = None

    def wait(self, timeout_seconds: float) -> None:
        try:
            connection = self._connected()
            next(connection.notifies(timeout=timeout_seconds, stop_after=1), None)
        except psycopg.Error:
            self.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connected(self) -> psycopg.Connection[object]:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(self.database_url, autocommit=True)
            self._connection.execute(f"LISTEN {TASK_EVENT_CHANNEL}")
        return self._connection
