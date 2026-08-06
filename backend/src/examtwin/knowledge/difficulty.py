from __future__ import annotations

from typing import Literal


def difficulty_label(score: float) -> Literal["easy", "medium", "hard"]:
    if not 0 <= score <= 1:
        raise ValueError("Difficulty score must be in [0, 1]")
    if score < 0.34:
        return "easy"
    if score < 0.67:
        return "medium"
    return "hard"
