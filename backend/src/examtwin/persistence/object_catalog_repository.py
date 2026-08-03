from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.persistence.models import PaperJobModel, StoredObjectModel
from examtwin.persistence.session import utcnow
from examtwin.storage import ObjectMetadata, StoredObject


class ObjectCatalogRepository:
    """Durable ownership and deletion state for canonical stored objects."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def record_put(self, stored: StoredObject, metadata: ObjectMetadata) -> None:
        now = utcnow()
        values = {
            "key": stored.key,
            "storage_backend": stored.backend,
            "bucket": stored.bucket,
            "checksum_sha256": stored.checksum_sha256,
            "size_bytes": stored.size_bytes,
            "content_type": stored.content_type,
            "purpose": metadata.purpose,
            "owner_type": metadata.owner_type,
            "owner_id": metadata.owner_id,
            "state": "active",
            "retain_until": metadata.retain_until,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
            "last_error": None,
        }
        with self.sessions.begin() as session:
            statement = insert(StoredObjectModel).values(**values)
            statement = statement.on_conflict_do_update(
                index_elements=[StoredObjectModel.key],
                set_={
                    name: value
                    for name, value in values.items()
                    if name not in {"key", "created_at"}
                },
            )
            session.execute(statement)

    def claim_expired(self, *, limit: int) -> list[str]:
        now = utcnow()
        stale_claim = now - timedelta(minutes=15)
        active_paper_job = exists(
            select(PaperJobModel.id).where(
                PaperJobModel.id == StoredObjectModel.owner_id,
                PaperJobModel.status.in_(("queued", "parsing", "splitting", "answering")),
            )
        )
        with self.sessions.begin() as session:
            rows = list(
                session.scalars(
                    select(StoredObjectModel)
                    .where(
                        or_(
                            (StoredObjectModel.state == "active")
                            & (StoredObjectModel.retain_until.is_not(None))
                            & (StoredObjectModel.retain_until <= now),
                            StoredObjectModel.state == "delete_failed",
                            (StoredObjectModel.state == "deleting")
                            & (StoredObjectModel.updated_at <= stale_claim),
                        )
                    )
                    .where(
                        ~(
                            (StoredObjectModel.owner_type == "paper_job")
                            & active_paper_job
                        )
                    )
                    .order_by(StoredObjectModel.retain_until, StoredObjectModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            for row in rows:
                row.state = "deleting"
                row.updated_at = now
                row.last_error = None
            return [row.key for row in rows]

    def mark_deleted(self, key: str) -> None:
        now = utcnow()
        with self.sessions.begin() as session:
            row = session.get(StoredObjectModel, key)
            if row is None:
                return
            row.state = "deleted"
            row.deleted_at = now
            row.updated_at = now
            row.last_error = None

    def mark_delete_failed(self, key: str, error: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(StoredObjectModel, key)
            if row is None:
                return
            row.state = "delete_failed"
            row.updated_at = utcnow()
            row.last_error = error[:1000]

    def stats(self) -> dict[str, object]:
        with self.sessions() as session:
            rows = session.execute(
                select(
                    StoredObjectModel.state,
                    func.count(),
                    func.coalesce(func.sum(StoredObjectModel.size_bytes), 0),
                ).group_by(StoredObjectModel.state)
            ).all()
        by_state = {
            str(state): {"objects": int(count), "bytes": int(size)}
            for state, count, size in rows
        }
        return {
            "by_state": by_state,
            "objects": sum(item["objects"] for item in by_state.values()),
            "bytes": sum(item["bytes"] for item in by_state.values()),
        }

    def extend_retention(
        self,
        owner_type: str,
        owner_id: str,
        retain_until: datetime,
    ) -> None:
        with self.sessions.begin() as session:
            session.execute(
                update(StoredObjectModel)
                .where(
                    StoredObjectModel.owner_type == owner_type,
                    StoredObjectModel.owner_id == owner_id,
                    StoredObjectModel.state == "active",
                )
                .values(retain_until=retain_until, updated_at=utcnow())
            )
