from __future__ import annotations

import json
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    AssessmentModel,
    AssessmentRunModel,
    DifficultyEvidenceModel,
    KnowledgeBaseModel,
    KnowledgeBaseVersionModel,
    KnowledgeBuildRunModel,
    KnowledgePointModel,
    KnowledgeRelationModel,
    PaperJobModel,
    QuestionDifficultyModel,
    RetrievalTraceModel,
    ReviewModel,
    RubricSetModel,
    SourceDocumentModel,
    SubjectModel,
    VectorIndexBuildRunModel,
    VectorIndexPublicationModel,
)
from examtwin.platform.database.session import utcnow
from examtwin.subjects.document_assignment import KNOWLEDGE_SOURCE_TYPES

SUBJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
SUBJECT_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
SUBJECT_DELETION_TERMINAL_JOB_STATUSES = ("completed", "partial_failed", "failed")
SUBJECT_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
SUBJECT_ICONS = frozenset(
    {
        "book-open",
        "calculator",
        "chart-no-axes-combined",
        "flask-conical",
        "languages",
        "landmark",
        "atom",
        "graduation-cap",
    }
)
SUBJECT_PRESENTATION_DEFAULTS = {
    "9640": ("chart-no-axes-combined", "#0F766E"),
    "9660": ("calculator", "#2563EB"),
}


def _subject_presentation(subject_code: str) -> tuple[str, str]:
    return SUBJECT_PRESENTATION_DEFAULTS.get(subject_code, ("book-open", "#2F6FED"))


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
                icon, color = _subject_presentation(package.pack.subject_code)
                values = {
                    "id": subject_id,
                    "subject_code": package.pack.subject_code,
                    "title": package.pack.title,
                    "board_name": package.pack.board.name,
                    "language": "en",
                    "icon": icon,
                    "color": color,
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
                        set_={
                            key: value
                            for key, value in values.items()
                            if key not in {"created_at", "title", "icon", "color"}
                        },
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
        icon: str = "book-open",
        color: str = "#2F6FED",
    ) -> dict[str, Any]:
        subject_id = subject_id.strip().lower()
        subject_code = subject_code.strip()
        title = title.strip()
        board_name = board_name.strip()
        icon = icon.strip()
        color = color.strip().upper()
        if not SUBJECT_ID_PATTERN.fullmatch(subject_id):
            raise ValueError("科目标识只能包含小写字母、数字和连字符，长度为 2 到 63")
        if not SUBJECT_CODE_PATTERN.fullmatch(subject_code):
            raise ValueError("科目代码只能包含字母、数字、点、下划线和连字符，长度为 2 到 32")
        if not title or not board_name:
            raise ValueError("科目名称和课程体系不能为空")
        self._validate_presentation(icon, color)
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
                icon=icon,
                color=color,
                capability_profile_id=capability_profile_id,
                active_graph_version_id=None,
                status="active",
                created_at=now,
                updated_at=now,
            )
            session.add(subject)
            session.flush()
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

    @staticmethod
    def _validate_presentation(icon: str, color: str) -> None:
        if icon not in SUBJECT_ICONS:
            raise ValueError("科目图标不受支持")
        if not SUBJECT_COLOR_PATTERN.fullmatch(color):
            raise ValueError("科目颜色必须是六位十六进制颜色")

    def update_subject_presentation(
        self,
        subject_id: str,
        *,
        title: str,
        icon: str,
        color: str,
    ) -> dict[str, Any]:
        title = title.strip()
        icon = icon.strip()
        color = color.strip().upper()
        if not title:
            raise ValueError("科目名称不能为空")
        self._validate_presentation(icon, color)
        with self.sessions.begin() as session:
            subject = session.get(SubjectModel, subject_id)
            if subject is None or subject.status != "active":
                raise LookupError("科目工作区不存在")
            subject.title = title
            subject.icon = icon
            subject.color = color
            subject.updated_at = utcnow()
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

    def delete_subjects(self, subject_ids: Sequence[str]) -> list[str]:
        requested = tuple(subject_ids)
        unique_ids = tuple(dict.fromkeys(requested))
        if not requested:
            raise ValueError("至少选择一个科目工作区")
        if len(unique_ids) != len(requested):
            raise ValueError("批量删除不能包含重复的科目工作区")

        with self.sessions.begin() as session:
            subjects = list(
                session.scalars(
                    select(SubjectModel)
                    .where(SubjectModel.id.in_(unique_ids))
                    .order_by(SubjectModel.id)
                    .with_for_update()
                )
            )
            found = {subject.id: subject for subject in subjects}
            missing = [subject_id for subject_id in unique_ids if subject_id not in found]
            if missing:
                raise LookupError(f"科目工作区不存在：{', '.join(missing)}")

            subject_codes = tuple(found[subject_id].subject_code for subject_id in unique_ids)
            owned_jobs = (PaperJobModel.subject_pack_id.in_(unique_ids)) | (
                PaperJobModel.subject_code.in_(subject_codes)
            )
            active_job = session.scalar(
                select(PaperJobModel.id)
                .where(
                    owned_jobs,
                    PaperJobModel.status.not_in(SUBJECT_DELETION_TERMINAL_JOB_STATUSES),
                )
                .limit(1)
            )
            if active_job is not None:
                raise ValueError("选中的科目包含正在处理的试卷任务，完成或失败后才能删除")

            assessment_ids = select(AssessmentModel.id).where(
                AssessmentModel.subject_code.in_(subject_codes)
            )
            session.execute(
                delete(ReviewModel).where(ReviewModel.assessment_id.in_(assessment_ids))
            )
            session.execute(
                delete(AssessmentModel).where(AssessmentModel.subject_code.in_(subject_codes))
            )

            session.execute(
                delete(AssessmentRunModel).where(AssessmentRunModel.subject_id.in_(unique_ids))
            )
            job_ids = select(PaperJobModel.id).where(owned_jobs)
            session.execute(
                update(PaperJobModel)
                .where(PaperJobModel.id.in_(job_ids))
                .values(replacement_for_job_id=None)
            )
            session.execute(delete(PaperJobModel).where(owned_jobs))

            document_ids = select(SourceDocumentModel.id).where(
                (SourceDocumentModel.subject_id.in_(unique_ids))
                | (SourceDocumentModel.subject_code.in_(subject_codes))
            )
            session.execute(
                delete(QuestionDifficultyModel).where(
                    QuestionDifficultyModel.source_document_id.in_(document_ids)
                )
            )
            session.execute(delete(RubricSetModel).where(RubricSetModel.subject_id.in_(unique_ids)))
            session.execute(
                delete(SourceDocumentModel).where(
                    (SourceDocumentModel.subject_id.in_(unique_ids))
                    | (SourceDocumentModel.subject_code.in_(subject_codes))
                )
            )

            point_ids = select(KnowledgePointModel.id).where(
                KnowledgePointModel.subject_code.in_(subject_codes)
            )
            session.execute(
                delete(DifficultyEvidenceModel).where(
                    DifficultyEvidenceModel.knowledge_point_id.in_(point_ids)
                )
            )
            session.execute(
                delete(KnowledgeRelationModel).where(
                    (KnowledgeRelationModel.source_id.in_(point_ids))
                    | (KnowledgeRelationModel.target_id.in_(point_ids))
                )
            )
            session.execute(
                delete(KnowledgePointModel).where(
                    KnowledgePointModel.subject_code.in_(subject_codes)
                )
            )

            session.execute(
                delete(VectorIndexPublicationModel).where(
                    VectorIndexPublicationModel.subject_code.in_(subject_codes)
                )
            )
            session.execute(
                delete(VectorIndexBuildRunModel).where(
                    VectorIndexBuildRunModel.subject_code.in_(subject_codes)
                )
            )
            session.execute(
                delete(KnowledgeBuildRunModel).where(
                    (KnowledgeBuildRunModel.subject_pack_id.in_(unique_ids))
                    | (KnowledgeBuildRunModel.subject_code.in_(subject_codes))
                )
            )
            session.execute(
                delete(RetrievalTraceModel).where(
                    RetrievalTraceModel.subject_code.in_(subject_codes)
                )
            )
            session.execute(delete(SubjectModel).where(SubjectModel.id.in_(unique_ids)))

        return list(unique_ids)

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

    def documents_for_version(self, version_id: str) -> list[str]:
        version = self.require_version(version_id)
        snapshot = version["source_snapshot"]
        if isinstance(snapshot, dict):
            snapshot = snapshot.get("documents", [])
        return [str(item["document_id"]) for item in snapshot]
