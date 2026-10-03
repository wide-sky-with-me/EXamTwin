from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import DocumentBlockModel


def build_scoped_block_id(build_id: str, source_block_id: str) -> str:
    """Return a durable DB identity while vector block identities stay reusable."""

    import uuid

    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"https://examtwin.local/evidence/build/{build_id}/{source_block_id}",
        )
    )


class DocumentBlockRepository:
    """Persist immutable parent/child retrieval blocks for one index build."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def replace_build(self, build_id: str, blocks: Sequence[Mapping[str, Any]]) -> None:
        with self.sessions.begin() as session:
            session.execute(
                delete(DocumentBlockModel).where(DocumentBlockModel.build_id == build_id)
            )
            session.add_all(DocumentBlockModel(**dict(block)) for block in blocks)

    def parents(self, build_id: str, parent_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        if not parent_ids:
            return {}
        # Builds published before block IDs were build-scoped store the source IDs directly,
        # so match both forms within the same build.
        stored_to_source = {
            build_scoped_block_id(build_id, source_id): source_id for source_id in parent_ids
        }
        stored_to_source.update({source_id: source_id for source_id in parent_ids})
        statement = select(DocumentBlockModel).where(
            DocumentBlockModel.build_id == build_id,
            DocumentBlockModel.id.in_(tuple(stored_to_source)),
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return {
            stored_to_source[row.id]: {
                "id": stored_to_source[row.id],
                "document_id": row.document_id,
                "page": row.page,
                "section": row.section,
                "section_path": json.loads(row.section_path_json),
                "content": row.content,
                "block_kind": row.block_kind,
                "source_role": row.source_role,
            }
            for row in rows
        }

    def list_for_version(
        self,
        knowledge_base_version_id: str,
        *,
        block_kinds: Sequence[str] = ("section",),
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        statement = select(DocumentBlockModel).where(
            DocumentBlockModel.knowledge_base_version_id == knowledge_base_version_id,
            DocumentBlockModel.block_kind.in_(tuple(block_kinds)),
        )
        statement = statement.order_by(
            DocumentBlockModel.document_id, DocumentBlockModel.page, DocumentBlockModel.id
        )
        if limit is not None:
            statement = statement.limit(limit)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [
            {
                "id": row.id,
                "document_id": row.document_id,
                "parent_block_id": row.parent_block_id,
                "page": row.page,
                "section": row.section,
                "section_path": json.loads(row.section_path_json),
                "content": row.content,
                "content_hash": row.content_hash,
                "knowledge_codes": json.loads(row.knowledge_codes_json),
                "metadata": json.loads(row.metadata_json),
            }
            for row in rows
        ]
