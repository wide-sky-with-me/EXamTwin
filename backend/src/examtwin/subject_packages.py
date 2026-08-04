from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from examtwin.answering_agent.contracts import SubjectSkill
from examtwin.answering_agent.skills import VISUAL_TOOL_POLICIES
from examtwin.subjects.contracts import (
    DEFAULT_CURRICULUM_NORMALIZER,
    CurriculumTextNormalizer,
    SubjectPack,
    UnitRule,
)
from examtwin.subjects.mathematics_9660 import Mathematics9660TextNormalizer
from examtwin.subjects.oxfordaqa import OXFORDAQA

DEFAULT_SUBJECT_PACKS_ROOT = Path(__file__).resolve().parents[3] / "subject-packs"
MAX_SKILL_CHARS = 32_000


class UnitRuleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    strand: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    topic_prefixes: tuple[str, ...] = Field(min_length=1)


class CurriculumManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_rules: tuple[UnitRuleManifest, ...] = Field(min_length=1)
    topic_code_pattern: str = Field(min_length=1)
    unit_patterns: tuple[tuple[str, str], ...] = Field(min_length=1)
    paper_unit_map: dict[str, str] = Field(min_length=1)
    minimum_topics: int = Field(ge=1)
    minimum_objectives: int = Field(ge=1)
    extractor_key: str = "structured-markdown-v1"
    normalizer_key: str = "default-v1"


class AnsweringManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    disabled_reason: str | None = None
    instructions_file: str = "SKILL.md"
    tool_names: tuple[str, ...] = ()
    required_tool_names: tuple[str, ...] = ()
    mandatory_tool_names: tuple[str, ...] = ()
    visual_policy: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> AnsweringManifest:
        if len(set(self.tool_names)) != len(self.tool_names):
            raise ValueError("answering tool allowlist contains duplicates")
        allowed = set(self.tool_names)
        missing_required = set(self.required_tool_names) - allowed
        missing_mandatory = set(self.mandatory_tool_names) - allowed
        if missing_required or missing_mandatory:
            missing = sorted(missing_required | missing_mandatory)
            raise ValueError(
                "answering tool requirements are outside the allowlist: " + ", ".join(missing)
            )
        if self.enabled and not self.tool_names:
            raise ValueError("enabled answering policy requires at least one tool")
        if not self.enabled and not (self.disabled_reason or "").strip():
            raise ValueError("disabled answering policy requires disabled_reason")
        return self


class SubjectPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    version: str = Field(min_length=1)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    subject_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    board_id: str = Field(min_length=1)
    specification_ref: str = Field(min_length=1)
    curriculum: CurriculumManifest
    answering: AnsweringManifest


@dataclass(frozen=True)
class SubjectPackage:
    manifest: SubjectPackageManifest
    pack: SubjectPack
    skill: SubjectSkill | None
    digest: str
    skill_digest: str | None
    source_dir: Path

    @property
    def answering_enabled(self) -> bool:
        return self.skill is not None

    @property
    def answering_disabled_reason(self) -> str | None:
        return self.manifest.answering.disabled_reason

    def require_skill(self) -> SubjectSkill:
        if self.skill is None:
            reason = self.answering_disabled_reason or "answering policy is not installed"
            raise LookupError(f"Subject package {self.pack.id!r} cannot answer papers: {reason}")
        return self.skill


class SubjectPackageRegistry:
    """Load trusted declarative subject packages behind one validated interface."""

    def __init__(self, packages: dict[str, SubjectPackage]) -> None:
        self._packages = MappingProxyType(dict(packages))

    @classmethod
    def from_directory(cls, root: Path) -> SubjectPackageRegistry:
        resolved_root = root.resolve(strict=True)
        packages: dict[str, SubjectPackage] = {}
        subject_codes: dict[str, str] = {}
        manifest_paths = sorted(resolved_root.glob("*/manifest.json"))
        if not manifest_paths:
            raise ValueError(f"No subject package manifests found under {resolved_root}")
        for manifest_path in manifest_paths:
            package = _load_package(resolved_root, manifest_path)
            package_id = package.pack.id
            if package_id in packages:
                raise ValueError(f"Duplicate subject package id: {package_id}")
            existing = subject_codes.get(package.pack.subject_code)
            if existing is not None:
                raise ValueError(
                    f"Subject code {package.pack.subject_code} is declared by both "
                    f"{existing} and {package_id}"
                )
            packages[package_id] = package
            subject_codes[package.pack.subject_code] = package_id
        return cls(packages)

    def require(self, package_id: str) -> SubjectPackage:
        try:
            return self._packages[package_id]
        except KeyError as error:
            available = ", ".join(sorted(self._packages))
            raise ValueError(
                f"Unknown subject package {package_id!r}; available: {available}"
            ) from error

    def all(self) -> tuple[SubjectPackage, ...]:
        return tuple(self._packages[key] for key in sorted(self._packages))


def _safe_file(package_dir: Path, relative_name: str) -> Path:
    if not relative_name.strip():
        raise ValueError("subject package file name cannot be empty")
    candidate = (package_dir / relative_name).resolve(strict=True)
    if not candidate.is_relative_to(package_dir):
        raise ValueError(f"Subject package file escapes its package directory: {relative_name}")
    if not candidate.is_file():
        raise ValueError(f"Subject package path is not a file: {relative_name}")
    return candidate


def _load_package(root: Path, manifest_path: Path) -> SubjectPackage:
    resolved_manifest = manifest_path.resolve(strict=True)
    if not resolved_manifest.is_relative_to(root):
        raise ValueError(f"Subject package manifest escapes root: {manifest_path}")
    manifest = SubjectPackageManifest.model_validate_json(resolved_manifest.read_text("utf-8"))
    package_dir = resolved_manifest.parent
    if package_dir.name != manifest.id:
        raise ValueError(
            f"Subject package directory {package_dir.name!r} does not match id {manifest.id!r}"
        )
    try:
        board = {"oxfordaqa": OXFORDAQA}[manifest.board_id]
    except KeyError as error:
        raise ValueError(f"Unknown board policy: {manifest.board_id}") from error
    normalizers: dict[str, CurriculumTextNormalizer] = {
        DEFAULT_CURRICULUM_NORMALIZER.key: DEFAULT_CURRICULUM_NORMALIZER,
        "mathematics-9660-v1": Mathematics9660TextNormalizer(),
    }
    try:
        normalizer = normalizers[manifest.curriculum.normalizer_key]
    except KeyError as error:
        raise ValueError(
            f"Unknown curriculum normalizer: {manifest.curriculum.normalizer_key}"
        ) from error

    curriculum = manifest.curriculum
    unit_codes = {rule.code for rule in curriculum.unit_rules}
    if len(unit_codes) != len(curriculum.unit_rules):
        raise ValueError(f"Subject package {manifest.id} contains duplicate unit codes")
    referenced_units = {unit for _pattern, unit in curriculum.unit_patterns} | set(
        curriculum.paper_unit_map.values()
    )
    unknown_units = referenced_units - unit_codes
    if unknown_units:
        raise ValueError(
            f"Subject package {manifest.id} references unknown units: "
            + ", ".join(sorted(unknown_units))
        )
    try:
        re.compile(curriculum.topic_code_pattern)
        for pattern, _unit in curriculum.unit_patterns:
            re.compile(pattern)
    except re.error as error:
        raise ValueError(f"Subject package {manifest.id} contains an invalid regex") from error
    pack = SubjectPack(
        id=manifest.id,
        subject_code=manifest.subject_code,
        title=manifest.title,
        board=board,
        specification_ref=manifest.specification_ref,
        unit_rules=tuple(
            UnitRule(
                code=rule.code,
                title=rule.title,
                strand=rule.strand,
                source_page=rule.source_page,
                topic_prefixes=rule.topic_prefixes,
            )
            for rule in curriculum.unit_rules
        ),
        topic_code_pattern=curriculum.topic_code_pattern,
        unit_patterns=curriculum.unit_patterns,
        paper_unit_map=curriculum.paper_unit_map,
        minimum_topics=curriculum.minimum_topics,
        minimum_objectives=curriculum.minimum_objectives,
        extractor_key=curriculum.extractor_key,
        curriculum_normalizer=normalizer,
    )

    skill: SubjectSkill | None = None
    skill_digest: str | None = None
    skill_text = ""
    answering = manifest.answering
    if answering.enabled:
        skill_path = _safe_file(package_dir, answering.instructions_file)
        skill_text = skill_path.read_text("utf-8").strip()
        if not skill_text:
            raise ValueError(f"Subject package {manifest.id} has an empty SKILL.md")
        if len(skill_text) > MAX_SKILL_CHARS:
            raise ValueError(
                f"Subject package {manifest.id} SKILL.md exceeds {MAX_SKILL_CHARS} characters"
            )
        skill_digest = hashlib.sha256(skill_text.encode()).hexdigest()
        visual_selector = None
        if answering.visual_policy is not None:
            try:
                visual_selector = VISUAL_TOOL_POLICIES[answering.visual_policy]
            except KeyError as error:
                raise ValueError(
                    f"Unknown answering visual policy: {answering.visual_policy}"
                ) from error
        skill = SubjectSkill(
            name=manifest.id,
            subject_codes=(manifest.subject_code,),
            instructions=skill_text,
            tool_names=answering.tool_names,
            required_tool_names=answering.required_tool_names,
            mandatory_tool_names=answering.mandatory_tool_names,
            visual_tool_selector=visual_selector,
            version=manifest.version,
            digest=skill_digest,
        )

    canonical_manifest = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(f"{canonical_manifest}\n{skill_text}".encode()).hexdigest()
    if skill is not None:
        skill = replace(skill, package_digest=digest)
    return SubjectPackage(
        manifest=manifest,
        pack=pack,
        skill=skill,
        digest=digest,
        skill_digest=skill_digest,
        source_dir=package_dir,
    )


@lru_cache(maxsize=8)
def _registry_for_root(resolved_root: str) -> SubjectPackageRegistry:
    return SubjectPackageRegistry.from_directory(Path(resolved_root))


def subject_package_registry(root: Path = DEFAULT_SUBJECT_PACKS_ROOT) -> SubjectPackageRegistry:
    return _registry_for_root(str(root.resolve(strict=True)))


def get_subject_package(
    package_id: str,
    root: Path = DEFAULT_SUBJECT_PACKS_ROOT,
) -> SubjectPackage:
    return subject_package_registry(root).require(package_id)
