from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    AssessmentModel,
    PaperJobModel,
    PaperUnitDocumentModel,
    PaperUnitModel,
    ReviewModel,
    SourceDocumentLocationModel,
    SourceDocumentModel,
    StoredObjectModel,
)
from examtwin.platform.database.session import utcnow


def _row_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _document_dict(
    binding: PaperUnitDocumentModel,
    document: SourceDocumentModel,
) -> dict[str, Any]:
    return {
        "id": document.id,
        "filename": document.filename,
        "display_name": document.display_name,
        "role": binding.role,
        "source_type": document.source_type,
        "status": document.status,
        "checksum": document.checksum,
        "page_count": document.page_count,
    }


class PaperUnitRepository:
    """Own paper-unit identity, explicit document membership, and lifecycle state."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def _hydrate(self, units: Sequence[PaperUnitModel]) -> list[dict[str, Any]]:
        if not units:
            return []
        unit_ids = tuple(unit.id for unit in units)
        with self.sessions() as session:
            document_rows = list(
                session.execute(
                    select(PaperUnitDocumentModel, SourceDocumentModel)
                    .join(
                        SourceDocumentModel,
                        SourceDocumentModel.id == PaperUnitDocumentModel.document_id,
                    )
                    .where(PaperUnitDocumentModel.paper_unit_id.in_(unit_ids))
                    .order_by(
                        PaperUnitDocumentModel.paper_unit_id,
                        PaperUnitDocumentModel.role,
                        SourceDocumentModel.filename,
                        SourceDocumentModel.id,
                    )
                )
            )
            job_counts = {
                str(unit_id): int(count)
                for unit_id, count in session.execute(
                    select(PaperJobModel.paper_unit_id, func.count(PaperJobModel.id))
                    .where(PaperJobModel.paper_unit_id.in_(unit_ids))
                    .group_by(PaperJobModel.paper_unit_id)
                )
                if unit_id is not None
            }
        documents_by_unit: dict[str, list[dict[str, Any]]] = {unit_id: [] for unit_id in unit_ids}
        for binding, document in document_rows:
            documents_by_unit[str(binding.paper_unit_id)].append(_document_dict(binding, document))
        return [
            {
                **_row_dict(unit),
                "documents": documents_by_unit[unit.id],
                "paper_job_count": job_counts.get(unit.id, 0),
                "created_at": str(unit.created_at),
                "updated_at": str(unit.updated_at),
            }
            for unit in units
        ]

    def list_for_subject(
        self,
        subject_id: str,
        *,
        query: str | None = None,
        unit_code: str | None = None,
        exam_year: int | None = None,
        exam_session: str | None = None,
        limit: int = 20,
        offset: int = 0,
        status: str = "active",
    ) -> tuple[list[dict[str, Any]], int, dict[str, list[Any]]]:
        conditions = [
            PaperUnitModel.subject_id == subject_id,
            PaperUnitModel.status == status,
        ]
        if query and query.strip():
            pattern = f"%{query.strip()}%"
            matching_document = exists(
                select(PaperUnitDocumentModel.document_id)
                .join(
                    SourceDocumentModel,
                    SourceDocumentModel.id == PaperUnitDocumentModel.document_id,
                )
                .where(
                    PaperUnitDocumentModel.paper_unit_id == PaperUnitModel.id,
                    or_(
                        SourceDocumentModel.filename.ilike(pattern),
                        SourceDocumentModel.display_name.ilike(pattern),
                    ),
                )
            )
            conditions.append(
                or_(
                    PaperUnitModel.display_name.ilike(pattern),
                    PaperUnitModel.pair_key.ilike(pattern),
                    matching_document,
                )
            )
        if unit_code:
            conditions.append(PaperUnitModel.unit_code == unit_code)
        if exam_year is not None:
            conditions.append(PaperUnitModel.exam_year == exam_year)
        if exam_session:
            conditions.append(PaperUnitModel.exam_session == exam_session)

        statement = (
            select(PaperUnitModel)
            .where(*conditions)
            .order_by(
                PaperUnitModel.exam_year.desc(),
                PaperUnitModel.exam_session,
                PaperUnitModel.unit_code,
                PaperUnitModel.id,
            )
            .limit(limit)
            .offset(offset)
        )
        active_scope = (
            PaperUnitModel.subject_id == subject_id,
            PaperUnitModel.status == status,
        )
        with self.sessions() as session:
            units = list(session.scalars(statement))
            total = int(
                session.scalar(select(func.count(PaperUnitModel.id)).where(*conditions)) or 0
            )
            available_units = list(
                session.scalars(
                    select(PaperUnitModel.unit_code)
                    .where(*active_scope)
                    .distinct()
                    .order_by(PaperUnitModel.unit_code)
                )
            )
            available_years = list(
                session.scalars(
                    select(PaperUnitModel.exam_year)
                    .where(*active_scope)
                    .distinct()
                    .order_by(PaperUnitModel.exam_year.desc())
                )
            )
            available_sessions = list(
                session.scalars(
                    select(PaperUnitModel.exam_session)
                    .where(*active_scope)
                    .distinct()
                    .order_by(PaperUnitModel.exam_session)
                )
            )
        facets: dict[str, list[Any]] = {
            "units": available_units,
            "years": available_years,
            "sessions": available_sessions,
        }
        return self._hydrate(units), total, facets

    def get(self, paper_unit_id: str, *, subject_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            unit = session.scalar(
                select(PaperUnitModel).where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "active",
                )
            )
        rows = self._hydrate((unit,)) if unit is not None else []
        return rows[0] if rows else None

    def find_by_pair(
        self,
        *,
        subject_id: str,
        pair_key: str,
        status: str = "active",
    ) -> dict[str, Any] | None:
        with self.sessions() as session:
            unit = session.scalar(
                select(PaperUnitModel).where(
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.pair_key == pair_key,
                    PaperUnitModel.status == status,
                )
            )
        rows = self._hydrate((unit,)) if unit is not None else []
        return rows[0] if rows else None

    def create(
        self,
        *,
        subject_id: str,
        subject_code: str,
        pair_key: str,
        display_name: str | None,
        unit_code: str,
        exam_year: int,
        exam_session: str,
        documents: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        now = utcnow()
        paper_unit_id = str(uuid4())
        with self.sessions.begin() as session:
            self._require_documents_available(session, paper_unit_id, documents)
            session.add(
                PaperUnitModel(
                    id=paper_unit_id,
                    subject_id=subject_id,
                    subject_code=subject_code,
                    pair_key=pair_key,
                    display_name=display_name,
                    unit_code=unit_code,
                    exam_year=exam_year,
                    exam_session=exam_session,
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            # There is intentionally no ORM relationship between the aggregate
            # root and its document bindings.  Flush the root explicitly so
            # PostgreSQL cannot insert the bindings before their FK target.
            session.flush()
            session.add_all(
                PaperUnitDocumentModel(
                    paper_unit_id=paper_unit_id,
                    document_id=document["document_id"],
                    role=document["role"],
                    created_at=now,
                )
                for document in documents
            )
        created = self.get(paper_unit_id, subject_id=subject_id)
        if created is None:
            raise RuntimeError("试卷单元创建失败")
        return created

    def update(
        self,
        paper_unit_id: str,
        *,
        subject_id: str,
        display_name: str | None,
        display_name_set: bool,
        documents: Sequence[Mapping[str, str]] | None,
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            unit = session.scalar(
                select(PaperUnitModel)
                .where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "active",
                )
                .with_for_update()
            )
            if unit is None:
                raise LookupError("试卷单元不存在")
            if display_name_set:
                unit.display_name = display_name
            if documents is not None:
                self._require_documents_available(session, paper_unit_id, documents)
                session.execute(
                    delete(PaperUnitDocumentModel).where(
                        PaperUnitDocumentModel.paper_unit_id == paper_unit_id
                    )
                )
                now = utcnow()
                session.add_all(
                    PaperUnitDocumentModel(
                        paper_unit_id=paper_unit_id,
                        document_id=document["document_id"],
                        role=document["role"],
                        created_at=now,
                    )
                    for document in documents
                )
            unit.updated_at = utcnow()
        updated = self.get(paper_unit_id, subject_id=subject_id)
        if updated is None:
            raise RuntimeError("试卷单元更新失败")
        return updated

    def restore(
        self,
        paper_unit_id: str,
        *,
        subject_id: str,
        display_name: str | None,
        documents: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        """Reactivate a deleted unit while preserving its stable exam identity."""

        with self.sessions.begin() as session:
            unit = session.scalar(
                select(PaperUnitModel)
                .where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "archived",
                )
                .with_for_update()
            )
            if unit is None:
                raise LookupError("已删除的试卷单元不存在")
            job_count = int(
                session.scalar(
                    select(func.count(PaperJobModel.id)).where(
                        PaperJobModel.paper_unit_id == paper_unit_id
                    )
                )
                or 0
            )
            if job_count:
                raise ValueError("试卷单元存在历史作答或评分记录，不能恢复并替换资料")
            self._require_documents_available(session, paper_unit_id, documents)
            session.execute(
                delete(PaperUnitDocumentModel).where(
                    PaperUnitDocumentModel.paper_unit_id == paper_unit_id
                )
            )
            now = utcnow()
            session.add_all(
                PaperUnitDocumentModel(
                    paper_unit_id=paper_unit_id,
                    document_id=document["document_id"],
                    role=document["role"],
                    created_at=now,
                )
                for document in documents
            )
            unit.display_name = display_name
            unit.status = "active"
            unit.updated_at = now
        restored = self.get(paper_unit_id, subject_id=subject_id)
        if restored is None:
            raise RuntimeError("试卷单元恢复失败")
        return restored

    def restore_archived(self, paper_unit_id: str, *, subject_id: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            unit = session.scalar(
                select(PaperUnitModel)
                .where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "archived",
                )
                .with_for_update()
            )
            if unit is None:
                raise LookupError("回收站中的试卷不存在")
            unit.status = "active"
            unit.updated_at = utcnow()
        restored = self.get(paper_unit_id, subject_id=subject_id)
        if restored is None:
            raise RuntimeError("试卷恢复失败")
        return restored

    def permanently_delete(self, paper_unit_id: str, *, subject_id: str) -> None:
        """Delete an archived paper and all workflow lineage in one transaction."""

        with self.sessions.begin() as session:
            unit = session.scalar(
                select(PaperUnitModel)
                .where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "archived",
                )
                .with_for_update()
            )
            if unit is None:
                raise LookupError("回收站中的试卷不存在")
            document_ids = tuple(
                session.scalars(
                    select(PaperUnitDocumentModel.document_id).where(
                        PaperUnitDocumentModel.paper_unit_id == paper_unit_id
                    )
                )
            )
            jobs = list(
                session.scalars(
                    select(PaperJobModel)
                    .where(PaperJobModel.paper_unit_id == paper_unit_id)
                    .order_by(PaperJobModel.id)
                    .with_for_update()
                )
            )
            now = datetime.now(UTC)
            if any(
                job.lease_token is not None
                and (job.lease_expires_at is None or job.lease_expires_at > now)
                for job in jobs
            ):
                raise ValueError("试卷仍有任务正在处理，暂时不能永久删除")
            job_ids = tuple(str(job.id) for job in jobs)
            if job_ids:
                external_replacement = session.scalar(
                    select(func.count(PaperJobModel.id)).where(
                        PaperJobModel.replacement_for_job_id.in_(job_ids),
                        PaperJobModel.id.not_in(job_ids),
                    )
                )
                if external_replacement:
                    raise ValueError("试卷存在跨单元替代审计关系，不能永久删除")
                assessment_ids = select(AssessmentModel.id).where(
                    AssessmentModel.paper_job_id.in_(job_ids)
                )
                session.execute(
                    delete(ReviewModel).where(ReviewModel.assessment_id.in_(assessment_ids))
                )
                session.execute(
                    delete(AssessmentModel).where(AssessmentModel.paper_job_id.in_(job_ids))
                )
                session.execute(
                    update(StoredObjectModel)
                    .where(
                        StoredObjectModel.owner_type == "paper_job",
                        StoredObjectModel.owner_id.in_(job_ids),
                        StoredObjectModel.state == "active",
                    )
                    .values(retain_until=now, updated_at=now)
                )
                for job in jobs:
                    job.replacement_for_job_id = None
                session.flush()
                for job in jobs:
                    session.delete(job)
                session.flush()
            session.delete(unit)
            session.flush()
            if document_ids:
                session.execute(
                    update(SourceDocumentModel)
                    .where(SourceDocumentModel.id.in_(document_ids))
                    .values(status="deleted", updated_at=now)
                )
                session.execute(
                    update(SourceDocumentLocationModel)
                    .where(SourceDocumentLocationModel.document_id.in_(document_ids))
                    .values(present=False, last_seen_at=now)
                )
                session.execute(
                    update(StoredObjectModel)
                    .where(
                        StoredObjectModel.owner_type == "source_document",
                        StoredObjectModel.owner_id.in_(document_ids),
                        StoredObjectModel.state == "active",
                    )
                    .values(retain_until=now, updated_at=now)
                )

    def archive(self, paper_unit_id: str, *, subject_id: str) -> None:
        with self.sessions.begin() as session:
            unit = session.scalar(
                select(PaperUnitModel)
                .where(
                    PaperUnitModel.id == paper_unit_id,
                    PaperUnitModel.subject_id == subject_id,
                    PaperUnitModel.status == "active",
                )
                .with_for_update()
            )
            if unit is None:
                raise LookupError("试卷单元不存在")
            unit.status = "archived"
            unit.updated_at = utcnow()

    @staticmethod
    def _require_documents_available(
        session: Session,
        paper_unit_id: str,
        documents: Sequence[Mapping[str, str]],
    ) -> None:
        document_ids = tuple(document["document_id"] for document in documents)
        existing = list(
            session.scalars(
                select(PaperUnitDocumentModel).where(
                    PaperUnitDocumentModel.document_id.in_(document_ids),
                    PaperUnitDocumentModel.paper_unit_id != paper_unit_id,
                )
            )
        )
        if existing:
            raise ValueError("资料已属于其他试卷单元")
