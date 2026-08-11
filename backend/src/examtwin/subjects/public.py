from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from examtwin.platform.config import Settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects import BoardPack, SubjectPack, UnitRule, get_subject_pack
from examtwin.subjects.contracts import SubjectSkill
from examtwin.subjects.dashboard_repository import DashboardRepository
from examtwin.subjects.document_assignment import (
    DocumentAssignment,
    resolve_document_assignment,
    resolve_document_assignment_after_file_validation,
    resolve_document_assignment_before_file_validation,
    validate_document_source_type,
)
from examtwin.subjects.packages import (
    AnsweringManifest,
    CurriculumManifest,
    RuntimeManifest,
    SubjectPackage,
    SubjectPackageManifest,
    UnitRuleManifest,
    get_subject_package,
    subject_package_registry,
)
from examtwin.subjects.visual_policy import (
    VISUAL_TOOL_POLICIES,
    mathematics_source_plot_overlay_mode,
    select_economics_answer_visual_tool,
    select_mathematics_answer_visual_tool,
)
from examtwin.subjects.workspace_repository import WorkspaceRepository

GENERIC_KNOWLEDGE_INSTRUCTIONS = """
Answer only from the selected subject's retrieved knowledge evidence. Always call
knowledge_search before answering. Cite the source page or section for every substantive
claim. If the evidence is missing or conflicting, say so. This profile is for general
knowledge questions only; it must not identify examination papers, answer whole papers,
or grade student work.
""".strip()


@dataclass(frozen=True)
class SubjectContext:
    """Complete request/job-scoped subject and immutable retrieval boundary."""

    package: SubjectPackage
    workspace_id: str
    board_name: str
    capability_profile_id: str | None
    corpus_dir: Path
    vector_collection: str
    vector_alias: str
    knowledge_base_version_ids: tuple[str, ...] = ()
    vector_collections: tuple[str, ...] = ()
    graph_version_id: str | None = None

    @property
    def id(self) -> str:
        return self.workspace_id

    @property
    def pack(self) -> SubjectPack:
        return self.package.pack

    @property
    def subject_code(self) -> str:
        return self.pack.subject_code

    @property
    def paper_answering_enabled(self) -> bool:
        return self.capability_profile_id is not None and self.capability_profile_id == self.pack.id

    @property
    def answering_disabled_reason(self) -> str | None:
        if self.paper_answering_enabled:
            return self.package.answering_disabled_reason
        return "尚未绑定经过验证的考试能力模板，仅开放知识库、知识图谱和通用问答"

    def require(self, subject_code: str) -> None:
        if subject_code != self.subject_code:
            raise ValueError(
                f"科目 {subject_code} 不属于当前服务上下文；当前科目为 {self.subject_code}"
            )

    def require_paper_capability(self) -> None:
        if not self.paper_answering_enabled:
            raise ValueError(self.answering_disabled_reason or "当前科目未开放整卷作答与评分")

    def with_retrieval_snapshot(
        self,
        *,
        version_ids: tuple[str, ...],
        collections: tuple[str, ...],
        graph_version_id: str | None,
    ) -> SubjectContext:
        if not collections:
            raise ValueError("所选知识库版本尚未发布可检索集合")
        return replace(
            self,
            knowledge_base_version_ids=version_ids,
            vector_collections=collections,
            vector_collection=collections[0],
            vector_alias=collections[0],
            graph_version_id=graph_version_id,
        )

    def with_index_target(self, *, version_id: str, alias_name: str) -> SubjectContext:
        alias_name = alias_name.strip()
        if not alias_name:
            raise ValueError("知识库版本缺少向量别名")
        base_collection = (
            alias_name.removesuffix("_live")
            if alias_name.endswith("_live")
            else f"{alias_name}_base"
        )
        return replace(
            self,
            knowledge_base_version_ids=(version_id,),
            vector_collections=(),
            vector_collection=base_collection,
            vector_alias=alias_name,
        )

    def runtime_settings(self, settings: Settings) -> Settings:
        """Bind provider services to this subject without mutating global settings."""

        return settings.model_copy(
            update={
                "subject_pack": self.pack.id,
                "corpus_root": self.corpus_dir,
                "qdrant_collection": self.vector_collection,
                "qdrant_collection_alias": self.vector_alias,
            }
        )


def _generic_package(settings: Settings, workspace: dict) -> SubjectPackage:
    workspace_id = str(workspace["id"])
    subject_code = str(workspace["subject_code"])
    title = str(workspace["title"])
    board_name = str(workspace["board_name"])
    collection = f"examtwin_{workspace_id.replace('-', '_')}_core"
    alias = f"{collection}_live"
    corpus_dir = settings.object_store_root / "subjects" / workspace_id / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    manifest = SubjectPackageManifest(
        schema_version=1,
        version="managed-v1",
        id=workspace_id,
        subject_code=subject_code,
        title=title,
        board_id="managed",
        specification_ref="managed-workspace",
        runtime=RuntimeManifest(
            corpus_root=str(corpus_dir),
            vector_collection=collection,
            vector_alias=alias,
        ),
        curriculum=CurriculumManifest(
            unit_rules=(
                UnitRuleManifest(
                    code="ALL",
                    title="Whole subject",
                    strand="General",
                    source_page=1,
                    topic_prefixes=("ALL",),
                ),
            ),
            topic_code_pattern=r"[A-Za-z0-9][A-Za-z0-9._-]*",
            unit_patterns=((r"(?!)", "ALL"),),
            paper_unit_map={"0": "ALL"},
            minimum_topics=1,
            minimum_objectives=1,
        ),
        answering=AnsweringManifest(
            enabled=True,
            tool_names=("knowledge_search",),
            required_tool_names=("knowledge_search",),
            mandatory_tool_names=("knowledge_search",),
        ),
    )
    digest = hashlib.sha256(
        f"{workspace_id}:{subject_code}:{GENERIC_KNOWLEDGE_INSTRUCTIONS}".encode()
    ).hexdigest()
    skill = SubjectSkill(
        name=f"{workspace_id}-knowledge",
        subject_codes=(subject_code,),
        instructions=GENERIC_KNOWLEDGE_INSTRUCTIONS,
        tool_names=("knowledge_search",),
        required_tool_names=("knowledge_search",),
        mandatory_tool_names=("knowledge_search",),
        version="managed-v1",
        digest=digest,
        package_digest=digest,
    )
    pack = SubjectPack(
        id=workspace_id,
        subject_code=subject_code,
        title=title,
        board=BoardPack(id="managed", name=board_name, official_source_types=frozenset()),
        specification_ref="managed-workspace",
        unit_rules=(
            UnitRule(
                code="ALL",
                title="Whole subject",
                strand="General",
                source_page=1,
                topic_prefixes=("ALL",),
            ),
        ),
        topic_code_pattern=r"[A-Za-z0-9][A-Za-z0-9._-]*",
        unit_patterns=((r"(?!)", "ALL"),),
        paper_unit_map={"0": "ALL"},
        minimum_topics=1,
        minimum_objectives=1,
    )
    return SubjectPackage(
        manifest=manifest,
        pack=pack,
        skill=skill,
        digest=digest,
        skill_digest=digest,
        source_dir=corpus_dir,
    )


def _context_from_workspace(settings: Settings, workspace: dict) -> SubjectContext:
    registry = subject_package_registry(settings.subject_packages_dir)
    profile_id = workspace.get("capability_profile_id")
    if profile_id:
        package = registry.require(str(profile_id))
        if package.pack.subject_code != workspace["subject_code"]:
            raise ValueError("能力模板与科目代码不匹配")
    else:
        package = _generic_package(settings, workspace)
    active = [
        base["active_version"]
        for base in workspace.get("knowledge_bases", [])
        if base.get("kind") == "core" and base.get("active_version")
    ]
    collections = tuple(
        str(version["collection_name"]) for version in active if version.get("collection_name")
    )
    runtime = package.manifest.runtime
    corpus_dir = settings.object_store_root / "subjects" / str(workspace["id"]) / "corpus"
    if profile_id:
        corpus_dir = settings.resolved(Path(runtime.corpus_root))
    collection = collections[0] if collections else runtime.vector_collection
    return SubjectContext(
        package=package,
        workspace_id=str(workspace["id"]),
        board_name=str(workspace["board_name"]),
        capability_profile_id=str(profile_id) if profile_id else None,
        corpus_dir=corpus_dir,
        vector_collection=collection,
        vector_alias=runtime.vector_alias,
        knowledge_base_version_ids=tuple(str(version["id"]) for version in active),
        vector_collections=collections,
        graph_version_id=workspace.get("active_graph_version_id"),
    )


def subject_context(settings: Settings, selector: str | None = None) -> SubjectContext:
    selected = selector or settings.subject_pack
    repository = WorkspaceRepository(create_session_factory(settings.database_url))
    try:
        workspace = repository.resolve_subject(selected)
    except SQLAlchemyError as error:
        raise ValueError("科目目录暂不可用") from error
    if workspace is None:
        raise ValueError(f"科目工作区不存在：{selected}")
    return _context_from_workspace(settings, workspace)


def all_subject_contexts(settings: Settings) -> tuple[SubjectContext, ...]:
    repository = WorkspaceRepository(create_session_factory(settings.database_url))
    try:
        workspaces = repository.list_subjects()
    except SQLAlchemyError:
        return ()
    return tuple(_context_from_workspace(settings, workspace) for workspace in workspaces)


__all__ = [
    "AnsweringManifest",
    "BoardPack",
    "CurriculumManifest",
    "DashboardRepository",
    "DocumentAssignment",
    "RuntimeManifest",
    "SubjectContext",
    "SubjectPackage",
    "SubjectPackageManifest",
    "SubjectPack",
    "SubjectSkill",
    "UnitRule",
    "UnitRuleManifest",
    "VISUAL_TOOL_POLICIES",
    "WorkspaceRepository",
    "all_subject_contexts",
    "get_subject_pack",
    "get_subject_package",
    "mathematics_source_plot_overlay_mode",
    "select_economics_answer_visual_tool",
    "resolve_document_assignment",
    "resolve_document_assignment_after_file_validation",
    "resolve_document_assignment_before_file_validation",
    "select_mathematics_answer_visual_tool",
    "subject_context",
    "validate_document_source_type",
    "subject_package_registry",
]
