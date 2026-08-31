from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from examtwin.subjects.contracts import (
    DEFAULT_CURRICULUM_NORMALIZER,
    BoardPack,
    CurriculumTextNormalizer,
)
from examtwin.subjects.mathematics_9660 import Mathematics9660TextNormalizer
from examtwin.subjects.oxfordaqa import OXFORDAQA
from examtwin.subjects.visual_policy import ANSWER_VISUAL_POLICIES, AnswerVisualPolicy


@dataclass(frozen=True)
class SubjectProviderRegistry:
    """Host-reviewed policies that declarative Subject Packages may reference by ID."""

    boards: Mapping[str, BoardPack]
    curriculum_normalizers: Mapping[str, CurriculumTextNormalizer]
    answer_visual_policies: Mapping[str, AnswerVisualPolicy]

    def __post_init__(self) -> None:
        object.__setattr__(self, "boards", MappingProxyType(dict(self.boards)))
        object.__setattr__(
            self,
            "curriculum_normalizers",
            MappingProxyType(dict(self.curriculum_normalizers)),
        )
        object.__setattr__(
            self,
            "answer_visual_policies",
            MappingProxyType(dict(self.answer_visual_policies)),
        )

    def require_board(self, key: str) -> BoardPack:
        try:
            return self.boards[key]
        except KeyError as error:
            raise ValueError(f"Unknown board policy: {key}") from error

    def require_curriculum_normalizer(self, key: str) -> CurriculumTextNormalizer:
        try:
            return self.curriculum_normalizers[key]
        except KeyError as error:
            raise ValueError(f"Unknown curriculum normalizer: {key}") from error

    def require_answer_visual_policy(self, key: str) -> AnswerVisualPolicy:
        try:
            return self.answer_visual_policies[key]
        except KeyError as error:
            raise ValueError(f"Unknown answering visual policy: {key}") from error


DEFAULT_SUBJECT_PROVIDERS = SubjectProviderRegistry(
    boards={"oxfordaqa": OXFORDAQA},
    curriculum_normalizers={
        DEFAULT_CURRICULUM_NORMALIZER.key: DEFAULT_CURRICULUM_NORMALIZER,
        Mathematics9660TextNormalizer.key: Mathematics9660TextNormalizer(),
    },
    answer_visual_policies=ANSWER_VISUAL_POLICIES,
)
