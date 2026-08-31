from __future__ import annotations

from typing import Literal

EASY_DIFFICULTY_UPPER_BOUND = 0.34
MEDIUM_DIFFICULTY_UPPER_BOUND = 0.67


def difficulty_label(score: float) -> Literal["easy", "medium", "hard"]:
    if not 0 <= score <= 1:
        raise ValueError("Difficulty score must be in [0, 1]")
    if score < EASY_DIFFICULTY_UPPER_BOUND:
        return "easy"
    if score < MEDIUM_DIFFICULTY_UPPER_BOUND:
        return "medium"
    return "hard"
