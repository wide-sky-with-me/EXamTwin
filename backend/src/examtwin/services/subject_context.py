from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from examtwin.config import Settings
from examtwin.subject_packages import SubjectPackage, subject_package_registry
from examtwin.subjects import SubjectPack


@dataclass(frozen=True)
class SubjectContext:
    """Complete request/job-scoped subject boundary inside the shared service."""

    package: SubjectPackage
    corpus_dir: Path
    vector_collection: str
    vector_alias: str

    @property
    def pack(self) -> SubjectPack:
        return self.package.pack

    @property
    def subject_code(self) -> str:
        return self.pack.subject_code

    def require(self, subject_code: str) -> None:
        if subject_code != self.subject_code:
            raise ValueError(
                f"科目 {subject_code} 不属于当前服务上下文；当前科目为 {self.subject_code}"
            )

    def runtime_settings(self, settings: Settings) -> Settings:
        """Bind legacy provider services to this subject without mutating global settings."""

        return settings.model_copy(
            update={
                "subject_pack": self.pack.id,
                "corpus_root": self.corpus_dir,
                "qdrant_collection": self.vector_collection,
                "qdrant_collection_alias": self.vector_alias,
            }
        )


def subject_context(settings: Settings, selector: str | None = None) -> SubjectContext:
    registry = subject_package_registry(settings.subject_packages_dir)
    package = registry.resolve(selector or settings.subject_pack)
    runtime = package.manifest.runtime
    return SubjectContext(
        package=package,
        corpus_dir=settings.resolved(Path(runtime.corpus_root)),
        vector_collection=runtime.vector_collection,
        vector_alias=runtime.vector_alias,
    )


def all_subject_contexts(settings: Settings) -> tuple[SubjectContext, ...]:
    registry = subject_package_registry(settings.subject_packages_dir)
    return tuple(subject_context(settings, package.pack.id) for package in registry.all())
