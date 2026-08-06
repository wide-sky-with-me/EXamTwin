from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    KnowledgeBaseModel,
    KnowledgeBaseVersionModel,
    SourceDocumentModel,
    SubjectModel,
    VectorIndexBuildRunModel,
)
from examtwin.platform.database.session import utcnow

SUBJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SUBJECT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
KNOWLEDGE_SOURCE_TYPES = frozenset(
    {"syllabus", "textbook", "slide", "revision_note", "topic_practice"}
)
ASSESSMENT_SOURCE_TYPES = frozenset(
    {
        "question_paper",
        "insert",
        "mark_scheme",
        "examiner_report",
        "answer_booklet",
        "specimen_paper",
    }
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://examtwin.local/{kind}/" + "/".join(parts)))


def _subject_dict(row: SubjectModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in SubjectModel.__table__.columns}


def _base_dict(row: KnowledgeBaseModel) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name) for column in KnowledgeBaseModel.__table__.columns
    }


def _version_dict(row: KnowledgeBaseVersionModel) -> dict[str, Any]:
    result = {
        column.name: getattr(row, column.name)
        for column in KnowledgeBaseVersionModel.__table__.columns
    }
    result["source_snapshot"] = json.loads(row.source_snapshot_json)
    return result


class WorkspaceRepository:
    """Own dynamic subjects and immutable knowledge-base publication state."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def synchronize_installed_subjects(self, packages: Sequence[Any]) -> None:
        now = utcnow()
        with self.sessions.begin() as session:
            for package in packages:
                subject_id = package.pack.id
                values = {
                    "id": subject_id,
                    "subject_code": package.pack.subject_code,
                    "title": package.pack.title,
                    "board_name": package.pack.board.name,
                    "language": "en",
                    "capability_profile_id": subject_id,
                    "status": "active",
                    "created_at": now,
                    "updated_at": now,
                }
                session.execute(
                    insert(SubjectModel)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[SubjectModel.id],
                        set_={key: value for key, value in values.items() if key != "created_at"},
                    )
                )
                default_base_id = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"https://examtwin.local/{package.pack.id}/core")
                )
                supplementary_base_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"https://examtwin.local/{package.pack.id}/supplementary",
                    )
                )
                if session.get(KnowledgeBaseModel, default_base_id) is None:
                    session.add(
                        KnowledgeBaseModel(
                            id=default_base_id,
                            subject_id=subject_id,
                            name="Core Knowledge Base",
                            kind="core",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                if session.get(KnowledgeBaseModel, supplementary_base_id) is None:
                    session.add(
                        KnowledgeBaseModel(
                            id=supplementary_base_id,
                            subject_id=subject_id,
                            name="Supplementary Knowledge Base",
                            kind="supplementary",
                            created_at=now,
                            updated_at=now,
                        )
                    )
                core_source = (SourceDocumentModel.source_type == "syllabus") | (
                    (SourceDocumentModel.source_type == "textbook")
                    & (SourceDocumentModel.authority_tier == "licensed_core")
                )
                supplementary_source = (
                    SourceDocumentModel.source_type.in_(
                        ("textbook", "slide", "revision_note", "topic_practice")
                    )
                    & ~core_source
                )
                assessment_source = SourceDocumentModel.source_type.in_(
                    ("question_paper", "mark_scheme", "insert", "examiner_report")
                )
                session.execute(
                    update(SourceDocumentModel)
                    .where(
                        SourceDocumentModel.subject_code == package.pack.subject_code,
                        SourceDocumentModel.subject_id.is_(None),
                    )
                    .values(
                        subject_id=subject_id,
                        source_role=case(
                            (core_source, "core_knowledge"),
                            (supplementary_source, "supplementary_knowledge"),
                            (assessment_source, "assessment_only"),
                            else_="excluded",
                        ),
                        knowledge_base_id=case(
                            (core_source, default_base_id),
                            (supplementary_source, supplementary_base_id),
                            else_=None,
                        ),
                        license_confirmed=case(
                            (SourceDocumentModel.authority_tier == "licensed_core", True),
                            else_=SourceDocumentModel.license_confirmed,
                        ),
                    )
                )

    def create_subject(
        self,
        *,
        subject_id: str,
        subject_code: str,
        title: str,
        board_name: str,
        language: str = "en",
        capability_profile_id: str | None = None,
    ) -> dict[str, Any]:
        subject_id = subject_id.strip().lower()
        subject_code = subject_code.strip()
        title = title.strip()
        board_name = board_name.strip()
        if not SUBJECT_ID_PATTERN.fullmatch(subject_id):
            raise ValueError("科目标识只能包含小写字母、数字和连字符，长度为 2 到 63")
        if not SUBJECT_CODE_PATTERN.fullmatch(subject_code):
            raise ValueError("科目代码只能包含字母、数字、点、下划线和连字符，长度为 2 到 32")
        if not title or not board_name:
            raise ValueError("科目名称和课程体系不能为空")
        now = utcnow()
        with self.sessions.begin() as session:
            if session.get(SubjectModel, subject_id) is not None:
                raise ValueError("科目标识已存在")
            if session.scalar(
                select(SubjectModel.id).where(SubjectModel.subject_code == subject_code)
            ):
                raise ValueError("科目代码已存在")
            subject = SubjectModel(
                id=subject_id,
                subject_code=subject_code,
                title=title,
                board_name=board_name,
                language=language.strip() or "en",
                capability_profile_id=capability_profile_id,
                active_graph_version_id=None,
                status="active",
                created_at=now,
                updated_at=now,
            )
            session.add(subject)
            for kind, name in (("core", "核心知识库"), ("supplementary", "补充知识库")):
                session.add(
                    KnowledgeBaseModel(
                        id=stable_id("knowledge-base", subject_id, kind),
                        subject_id=subject_id,
                        name=name,
                        kind=kind,
                        active_version_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return self.require_subject(subject_id)

    def list_subjects(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(SubjectModel)
                    .where(SubjectModel.status == "active")
                    .order_by(SubjectModel.subject_code)
                )
            )
        return [self._subject_with_bases(row) for row in rows]

    def resolve_subject(self, selector: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalar(
                select(SubjectModel).where(
                    (SubjectModel.id == selector) | (SubjectModel.subject_code == selector)
                )
            )
        return None if row is None else self._subject_with_bases(row)

    def require_subject(self, selector: str) -> dict[str, Any]:
        subject = self.resolve_subject(selector)
        if subject is None:
            raise LookupError(f"未知科目：{selector}")
        return subject

    def _subject_with_bases(self, row: SubjectModel) -> dict[str, Any]:
        subject = _subject_dict(row)
        with self.sessions() as session:
            bases = list(
                session.scalars(
                    select(KnowledgeBaseModel)
                    .where(KnowledgeBaseModel.subject_id == row.id)
                    .order_by(KnowledgeBaseModel.kind)
                )
            )
            versions = (
                {
                    version.id: version
                    for version in session.scalars(
                        select(KnowledgeBaseVersionModel).where(
                            KnowledgeBaseVersionModel.knowledge_base_id.in_(
                                tuple(base.id for base in bases)
                            )
                        )
                    )
                }
                if bases
                else {}
            )
            build_points = {
                build.id: build.indexed_points
                for build in session.scalars(
                    select(VectorIndexBuildRunModel).where(
                        VectorIndexBuildRunModel.id.in_(
                            tuple(
                                version.vector_build_id
                                for version in versions.values()
                                if version.vector_build_id
                            )
                        )
                    )
                )
            }
        subject["knowledge_bases"] = []
        for base in bases:
            item = _base_dict(base)
            active = versions.get(base.active_version_id or "")
            if active is None:
                item["active_version"] = None
            else:
                active_version = _version_dict(active)
                active_version["vector_points"] = build_points.get(active.vector_build_id or "", 0)
                item["active_version"] = active_version
            subject["knowledge_bases"].append(item)
        return subject

    def require_base(self, base_id: str, *, subject_id: str | None = None) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(KnowledgeBaseModel, base_id)
        if row is None or (subject_id is not None and row.subject_id != subject_id):
            raise LookupError("知识库不存在于当前科目")
        return _base_dict(row)

    def create_version(self, base_id: str) -> dict[str, Any]:
        now = utcnow()
        with self.sessions.begin() as session:
            base = session.scalar(
                select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == base_id).with_for_update()
            )
            if base is None:
                raise LookupError("知识库不存在")
            documents = list(
                session.scalars(
                    select(SourceDocumentModel).where(
                        SourceDocumentModel.knowledge_base_id == base_id,
                        SourceDocumentModel.source_role.in_(
                            ("core_knowledge", "supplementary_knowledge")
                        ),
                    )
                )
            )
            allowed = (
                {"syllabus", "textbook"}
                if base.kind == "core"
                else KNOWLEDGE_SOURCE_TYPES - {"syllabus"}
            )
            invalid = [row.filename for row in documents if row.source_type not in allowed]
            if invalid:
                raise ValueError("知识库包含不允许的资料类型：" + "、".join(invalid[:5]))
            if base.kind == "core":
                types = {row.source_type for row in documents}
                if "syllabus" not in types or "textbook" not in types:
                    raise ValueError("核心知识库发布前必须同时包含课程大纲和教材")
                unlicensed = [
                    row.filename
                    for row in documents
                    if row.source_type == "textbook" and not row.license_confirmed
                ]
                if unlicensed:
                    raise ValueError("教材授权尚未确认：" + "、".join(unlicensed[:5]))
            if not documents:
                raise ValueError("知识库没有可构建的资料")
            number = (
                int(
                    session.scalar(
                        select(
                            func.coalesce(func.max(KnowledgeBaseVersionModel.version_number), 0)
                        ).where(KnowledgeBaseVersionModel.knowledge_base_id == base_id)
                    )
                    or 0
                )
                + 1
            )
            version_id = str(uuid.uuid4())
            alias_name = f"examtwin_{base.subject_id.replace('-', '_')}_{base.kind}_live"
            snapshot = [
                {
                    "document_id": row.id,
                    "checksum": row.checksum,
                    "source_type": row.source_type,
                    "source_role": row.source_role,
                }
                for row in sorted(documents, key=lambda item: item.id)
            ]
            version = KnowledgeBaseVersionModel(
                id=version_id,
                knowledge_base_id=base_id,
                version_number=number,
                status="building",
                alias_name=alias_name,
                collection_name=None,
                vector_build_id=None,
                source_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                parser_version="hierarchical-v1",
                created_at=now,
                updated_at=now,
                published_at=None,
            )
            session.add(version)
        return _version_dict(version)

    def require_version(self, version_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(KnowledgeBaseVersionModel, version_id)
        if row is None:
            raise LookupError("知识库版本不存在")
        return _version_dict(row)

    def fail_version(self, version_id: str, error: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(KnowledgeBaseVersionModel, version_id)
            if row is None:
                raise LookupError("知识库版本不存在")
            row.status = "failed"
            row.updated_at = utcnow()
            snapshot = json.loads(row.source_snapshot_json)
            row.source_snapshot_json = json.dumps(
                {"documents": snapshot, "error": error[:2000]}, ensure_ascii=False
            )

    def publish_version(
        self,
        version_id: str,
        *,
        build_id: str,
        collection_name: str,
    ) -> None:
        now = utcnow()
        with self.sessions.begin() as session:
            version = session.scalar(
                select(KnowledgeBaseVersionModel)
                .where(KnowledgeBaseVersionModel.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise LookupError("知识库版本不存在")
            base = session.get(KnowledgeBaseModel, version.knowledge_base_id)
            if base is None:
                raise LookupError("知识库不存在")
            version.status = "published"
            version.vector_build_id = build_id
            version.collection_name = collection_name
            version.updated_at = now
            version.published_at = now
            base.active_version_id = version.id
            base.updated_at = now

    def retrieval_snapshot_for_versions(
        self,
        subject_id: str,
        version_ids: Sequence[str],
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(version_ids))
        if not requested:
            return self.active_retrieval_snapshot(subject_id)
        with self.sessions() as session:
            rows = list(
                session.execute(
                    select(KnowledgeBaseVersionModel, KnowledgeBaseModel)
                    .join(
                        KnowledgeBaseModel,
                        KnowledgeBaseModel.id == KnowledgeBaseVersionModel.knowledge_base_id,
                    )
                    .where(KnowledgeBaseVersionModel.id.in_(tuple(requested)))
                )
            )
        by_id = {version.id: (version, base) for version, base in rows}
        if set(by_id) != set(requested):
            raise LookupError("所选知识库版本不存在")
        base_ids: set[str] = set()
        collections: list[str] = []
        for version_id in requested:
            version, base = by_id[version_id]
            if base.subject_id != subject_id:
                raise ValueError("所选知识库版本不属于当前科目")
            if version.status != "published" or not version.collection_name:
                raise ValueError("所选知识库版本尚未发布")
            if base.id in base_ids:
                raise ValueError("同一知识库只能选择一个版本")
            base_ids.add(base.id)
            collections.append(version.collection_name)
        subject = self.require_subject(subject_id)
        return {
            "version_ids": requested,
            "collections": collections,
            "graph_version_id": subject.get("active_graph_version_id"),
        }

    def active_retrieval_snapshot(
        self,
        subject_id: str,
        *,
        include_supplementary: bool = False,
    ) -> dict[str, Any]:
        subject = self.require_subject(subject_id)
        versions: list[dict[str, Any]] = []
        for base in subject["knowledge_bases"]:
            if base["kind"] == "supplementary" and not include_supplementary:
                continue
            active = base.get("active_version")
            if active is not None and active.get("collection_name"):
                versions.append(active)
        return {
            "version_ids": [item["id"] for item in versions],
            "collections": [item["collection_name"] for item in versions],
            "graph_version_id": subject.get("active_graph_version_id"),
        }

    def assign_document(
        self,
        document_id: str,
        *,
        subject_id: str,
        knowledge_base_id: str | None,
        source_type: str,
        license_confirmed: bool,
    ) -> None:
        if source_type not in KNOWLEDGE_SOURCE_TYPES | ASSESSMENT_SOURCE_TYPES | {"other"}:
            raise ValueError("未知资料类型")
        if source_type == "textbook" and not license_confirmed:
            raise ValueError("教材必须确认已获授权后才能进入知识库")
        with self.sessions.begin() as session:
            subject = session.get(SubjectModel, subject_id)
            document = session.get(SourceDocumentModel, document_id)
            if subject is None or document is None or document.subject_code != subject.subject_code:
                raise LookupError("资料不存在于当前科目")
            role = "excluded"
            if source_type in ASSESSMENT_SOURCE_TYPES:
                if knowledge_base_id is not None:
                    raise ValueError("试卷、Insert、Mark Scheme 和考官报告不能进入知识库")
                role = "assessment_only"
            elif source_type in KNOWLEDGE_SOURCE_TYPES:
                if knowledge_base_id is None:
                    raise ValueError("知识资料必须归属知识库")
                base = session.get(KnowledgeBaseModel, knowledge_base_id)
                if base is None or base.subject_id != subject_id:
                    raise LookupError("知识库不存在于当前科目")
                if base.kind == "core":
                    if source_type not in {"syllabus", "textbook"}:
                        raise ValueError("核心知识库只接受考纲和已授权教材")
                    role = "core_knowledge"
                else:
                    if source_type == "syllabus":
                        raise ValueError("考纲必须归属核心知识库")
                    role = "supplementary_knowledge"
            elif knowledge_base_id is not None:
                raise ValueError("未分类资料不能进入知识库")
            document.subject_id = subject_id
            document.knowledge_base_id = knowledge_base_id
            document.source_type = source_type
            document.source_role = role
            document.license_confirmed = license_confirmed
            document.updated_at = utcnow()

    def documents_for_version(self, version_id: str) -> list[str]:
        version = self.require_version(version_id)
        snapshot = version["source_snapshot"]
        if isinstance(snapshot, dict):
            snapshot = snapshot.get("documents", [])
        return [str(item["document_id"]) for item in snapshot]
