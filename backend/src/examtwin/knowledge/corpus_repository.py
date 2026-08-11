from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import case, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    SourceDocumentLocationModel,
    SourceDocumentModel,
    SourceDocumentVersionModel,
)
from examtwin.platform.database.results import affected_rows
from examtwin.platform.database.session import utcnow


def _document_dict(row: SourceDocumentModel) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name) for column in SourceDocumentModel.__table__.columns
    }


class CorpusRepository:
    """Own source-document inventory, filtering, and conversion state."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def register_generated_mark_scheme(
        self,
        *,
        document_id: str,
        subject_id: str,
        subject_code: str,
        filename: str,
        checksum: str,
        pair_key: str,
        markdown_path: str,
    ) -> dict[str, Any]:
        now = utcnow()
        values = {
            "id": document_id,
            "subject_id": subject_id,
            "subject_code": subject_code,
            "knowledge_base_id": None,
            "path": f"generated://mark-schemes/{document_id}",
            "filename": filename,
            "source_type": "mark_scheme",
            "authority_tier": "assessment",
            "source_role": "excluded",
            "license_confirmed": True,
            "checksum": checksum,
            "pair_key": pair_key,
            "unit_code": None,
            "exam_year": None,
            "exam_session": None,
            "identity_status": "complete",
            "identity_error": None,
            "page_count": None,
            "status": "converted",
            "object_key": None,
            "markdown_path": markdown_path,
            "converted_source_checksum": checksum,
            "metadata_json": json.dumps({"source_kind": "ai_generated"}, ensure_ascii=False),
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self.sessions.begin() as session:
            session.add(SourceDocumentModel(**values))
        document = self.get(document_id)
        if document is None:
            raise RuntimeError("AI Mark Scheme 保存失败")
        return document

    def register_discovery(
        self,
        document: Mapping[str, Any],
        *,
        relative_path: str,
        size_bytes: int,
        current_paths: set[str],
    ) -> str:
        """Register a physical location while preserving one logical document identity."""

        now = utcnow()
        values: dict[str, Any] = {
            "subject_code": "9660",
            "subject_id": None,
            "knowledge_base_id": None,
            "authority_tier": "supplementary",
            "source_role": "excluded",
            "license_confirmed": False,
            "pair_key": None,
            "unit_code": None,
            "exam_year": None,
            "exam_session": None,
            "page_count": None,
            "status": "discovered",
            "object_key": None,
            "markdown_path": None,
            "converted_source_checksum": None,
            "metadata_json": "{}",
            "error": None,
            "identity_status": "not_applicable",
            "identity_error": None,
            **dict(document),
            "created_at": now,
            "updated_at": now,
        }
        if not isinstance(values["metadata_json"], str):
            values["metadata_json"] = json.dumps(values["metadata_json"], ensure_ascii=False)
        with self.sessions.begin() as session:
            path = str(values["path"])
            document_id = session.scalar(
                select(SourceDocumentLocationModel.document_id).where(
                    SourceDocumentLocationModel.path == path
                )
            )
            if document_id is None:
                document_id = session.scalar(
                    select(SourceDocumentModel.id).where(SourceDocumentModel.path == path)
                )
            if document_id is None:
                document_id = session.scalar(
                    select(SourceDocumentModel.id)
                    .where(
                        SourceDocumentModel.subject_code == values["subject_code"],
                        SourceDocumentModel.source_type == values["source_type"],
                        SourceDocumentModel.checksum == values["checksum"],
                    )
                    .order_by(SourceDocumentModel.id)
                    .limit(1)
                )
            if document_id is None:
                document_id = hashlib.sha256(
                    (
                        f"{values['subject_code']}:{values['source_type']}:{values['checksum']}"
                    ).encode()
                ).hexdigest()

            existing = session.get(SourceDocumentModel, document_id)
            if existing is None:
                values["id"] = document_id
                session.add(SourceDocumentModel(**values))
            else:
                source_changed = existing.checksum != values["checksum"]
                primary_is_present = existing.path in current_paths
                if not primary_is_present:
                    existing.path = path
                    existing.filename = str(values["filename"])
                    existing.metadata_json = str(values["metadata_json"])
                for field in (
                    "subject_code",
                    "subject_id",
                    "knowledge_base_id",
                    "source_type",
                    "authority_tier",
                    "source_role",
                    "license_confirmed",
                    "checksum",
                    "object_key",
                    "pair_key",
                    "unit_code",
                    "exam_year",
                    "exam_session",
                    "identity_status",
                    "identity_error",
                    "page_count",
                    "updated_at",
                ):
                    setattr(existing, field, values[field])
                if source_changed:
                    existing.status = "discovered"
                    existing.markdown_path = None
                    existing.error = None

            location = session.get(SourceDocumentLocationModel, path)
            if location is None:
                session.add(
                    SourceDocumentLocationModel(
                        path=path,
                        document_id=document_id,
                        relative_path=relative_path,
                        present=True,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
            else:
                location.document_id = document_id
                location.relative_path = relative_path
                location.present = True
                location.last_seen_at = now

            version_id = hashlib.sha256(f"{document_id}:{values['checksum']}".encode()).hexdigest()
            session.execute(
                insert(SourceDocumentVersionModel)
                .values(
                    id=version_id,
                    document_id=document_id,
                    checksum=values["checksum"],
                    size_bytes=size_bytes,
                    created_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        SourceDocumentVersionModel.document_id,
                        SourceDocumentVersionModel.checksum,
                    ]
                )
            )
        return str(document_id)

    def find_by_checksum(
        self,
        *,
        subject_code: str,
        source_type: str,
        checksum: str,
    ) -> dict[str, Any] | None:
        statement = (
            select(SourceDocumentModel)
            .where(
                SourceDocumentModel.subject_code == subject_code,
                SourceDocumentModel.source_type == source_type,
                SourceDocumentModel.checksum == checksum,
            )
            .order_by(SourceDocumentModel.id)
            .limit(1)
        )
        with self.sessions() as session:
            row = session.scalar(statement)
            return _document_dict(row) if row is not None else None

    def finish_scan(self, subject_code: str, current_paths: set[str]) -> None:
        with self.sessions.begin() as session:
            statement = (
                update(SourceDocumentLocationModel)
                .where(
                    SourceDocumentLocationModel.document_id.in_(
                        select(SourceDocumentModel.id).where(
                            SourceDocumentModel.subject_code == subject_code
                        )
                    )
                )
                .values(present=False)
            )
            if current_paths:
                statement = statement.where(
                    SourceDocumentLocationModel.path.not_in(tuple(current_paths))
                )
            session.execute(statement)

    def update_status(
        self,
        document_id: str,
        status: str,
        *,
        markdown_path: str | None = None,
        error: str | None = None,
        converted_source_checksum: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status,
            "error": error,
            "updated_at": utcnow(),
        }
        if markdown_path is not None:
            values["markdown_path"] = markdown_path
        if converted_source_checksum is not None:
            values["converted_source_checksum"] = converted_source_checksum
        with self.sessions.begin() as session:
            result = session.execute(
                update(SourceDocumentModel)
                .where(SourceDocumentModel.id == document_id)
                .values(**values)
            )
            if affected_rows(result) != 1:
                raise LookupError(f"Source document does not exist: {document_id}")

    def get_converted(self, document_id: str) -> dict[str, Any] | None:
        statement = select(SourceDocumentModel).where(
            SourceDocumentModel.id == document_id,
            SourceDocumentModel.markdown_path.is_not(None),
        )
        with self.sessions() as session:
            row = session.scalar(statement)
        return None if row is None else _document_dict(row)

    def get(self, document_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(SourceDocumentModel, document_id)
        return None if row is None else _document_dict(row)

    def get_active(self, document_id: str) -> dict[str, Any] | None:
        statement = select(SourceDocumentModel).where(
            SourceDocumentModel.id == document_id,
            SourceDocumentModel.status != "deleted",
        )
        with self.sessions() as session:
            row = session.scalar(statement)
        return None if row is None else _document_dict(row)

    def rename(self, document_id: str, *, subject_code: str, display_name: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            result = session.execute(
                update(SourceDocumentModel)
                .where(
                    SourceDocumentModel.id == document_id,
                    SourceDocumentModel.subject_code == subject_code,
                    SourceDocumentModel.status != "deleted",
                )
                .values(display_name=display_name, updated_at=utcnow())
            )
            if affected_rows(result) != 1:
                raise LookupError("资料不存在或已删除")
        document = self.get_active(document_id)
        if document is None:
            raise LookupError("资料不存在或已删除")
        return document

    def archive(self, document_id: str, *, subject_code: str) -> None:
        now = utcnow()
        with self.sessions.begin() as session:
            result = session.execute(
                update(SourceDocumentModel)
                .where(
                    SourceDocumentModel.id == document_id,
                    SourceDocumentModel.subject_code == subject_code,
                    SourceDocumentModel.status != "deleted",
                )
                .values(status="deleted", updated_at=now)
            )
            if affected_rows(result) != 1:
                raise LookupError("资料不存在或已删除")
            session.execute(
                update(SourceDocumentLocationModel)
                .where(SourceDocumentLocationModel.document_id == document_id)
                .values(present=False, last_seen_at=now)
            )

    def list(
        self,
        *,
        document_ids: Sequence[str] | None = None,
        source_types: Sequence[str] | None = None,
        authority_tiers: Sequence[str] | None = None,
        subject_code: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(SourceDocumentModel)
        statement = statement.where(SourceDocumentModel.status != "deleted")
        if subject_code:
            statement = statement.where(SourceDocumentModel.subject_code == subject_code)
        if document_ids:
            statement = statement.where(SourceDocumentModel.id.in_(tuple(document_ids)))
        if source_types:
            statement = statement.where(SourceDocumentModel.source_type.in_(tuple(source_types)))
        if authority_tiers:
            statement = statement.where(
                SourceDocumentModel.authority_tier.in_(tuple(authority_tiers))
            )
        if status:
            statement = statement.where(SourceDocumentModel.status == status)
        statement = statement.order_by(SourceDocumentModel.path)
        if limit is not None:
            statement = statement.limit(limit)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_document_dict(row) for row in rows]

    def list_for_api(
        self,
        *,
        source_type: str | None,
        status: str | None,
        limit: int,
        subject_code: str | None = None,
    ) -> list[dict[str, Any]]:
        statement = select(SourceDocumentModel)
        statement = statement.where(SourceDocumentModel.status != "deleted")
        if subject_code:
            statement = statement.where(SourceDocumentModel.subject_code == subject_code)
        if source_type:
            statement = statement.where(SourceDocumentModel.source_type == source_type)
        if status:
            statement = statement.where(SourceDocumentModel.status == status)
        year_priority = case((SourceDocumentModel.exam_year.is_(None), 1), else_=0)
        statement = statement.order_by(
            SourceDocumentModel.source_type,
            year_priority,
            SourceDocumentModel.exam_year.desc(),
            SourceDocumentModel.filename,
        ).limit(limit)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        fields = (
            "id",
            "filename",
            "display_name",
            "source_type",
            "authority_tier",
            "source_role",
            "knowledge_base_id",
            "license_confirmed",
            "checksum",
            "pair_key",
            "unit_code",
            "exam_year",
            "exam_session",
            "identity_status",
            "identity_error",
            "page_count",
            "status",
            "error",
        )
        return [{field: getattr(row, field) for field in fields} for row in rows]

    def exact_pair_documents(self, pair_key: str, limit: int = 4) -> list[dict[str, Any]]:
        priority = case(
            (SourceDocumentModel.source_type == "mark_scheme", 0),
            (SourceDocumentModel.source_type == "insert", 1),
            (SourceDocumentModel.source_type == "examiner_report", 2),
            else_=3,
        )
        statement = (
            select(SourceDocumentModel)
            .where(
                SourceDocumentModel.pair_key == pair_key,
                SourceDocumentModel.markdown_path.is_not(None),
                SourceDocumentModel.source_type.in_(
                    ("mark_scheme", "insert", "examiner_report", "question_paper")
                ),
            )
            .order_by(priority, SourceDocumentModel.path)
            .limit(limit)
        )
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_document_dict(row) for row in rows]

    def resolve_reference(
        self,
        reference: str,
        *,
        subject_code: str | None = None,
    ) -> dict[str, Any] | None:
        priority = case((SourceDocumentModel.source_type == "question_paper", 0), else_=1)
        statement = (
            select(SourceDocumentModel)
            .where(
                or_(
                    SourceDocumentModel.id == reference,
                    SourceDocumentModel.pair_key == reference,
                    SourceDocumentModel.filename == reference,
                    SourceDocumentModel.path == reference,
                )
            )
            .order_by(priority)
            .limit(1)
        )
        if subject_code:
            statement = statement.where(SourceDocumentModel.subject_code == subject_code)
        with self.sessions() as session:
            row = session.scalar(statement)
        return None if row is None else _document_dict(row)

    def mark_schemes(
        self,
        pair_key: str,
        *,
        subject_code: str | None = None,
    ) -> list[dict[str, Any]]:
        statement = (
            select(SourceDocumentModel)
            .where(
                SourceDocumentModel.pair_key == pair_key,
                SourceDocumentModel.source_type == "mark_scheme",
                SourceDocumentModel.markdown_path.is_not(None),
            )
            .order_by(SourceDocumentModel.path)
        )
        if subject_code:
            statement = statement.where(SourceDocumentModel.subject_code == subject_code)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        return [_document_dict(row) for row in rows]
