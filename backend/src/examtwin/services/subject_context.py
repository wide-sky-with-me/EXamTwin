from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from examtwin.config import Settings
from examtwin.subjects import SubjectPack, get_subject_pack


@dataclass(frozen=True)
class SubjectContext:
    """Complete, non-optional subject boundary for one service deployment."""

    pack: SubjectPack
    corpus_dir: Path
    vector_alias: str

    @property
    def subject_code(self) -> str:
        return self.pack.subject_code

    def require(self, subject_code: str) -> None:
        if subject_code != self.subject_code:
            raise ValueError(
                f"科目 {subject_code} 不属于当前服务上下文；当前科目为 {self.subject_code}"
            )


def subject_context(settings: Settings) -> SubjectContext:
    return SubjectContext(
        pack=get_subject_pack(settings.subject_pack),
        corpus_dir=settings.corpus_dir,
        vector_alias=settings.qdrant_collection_alias,
    )
