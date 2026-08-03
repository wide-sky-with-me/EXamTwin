from __future__ import annotations

import math

from examtwin.schemas.knowledge import DifficultyFeatures, DifficultyResult

DIFFICULTY_ALGORITHM_VERSION = "weighted-available-features-v2"

WEIGHTS = {
    "syllabus_complexity": 0.20,
    "prerequisite_depth": 0.18,
    "cognitive_demand": 0.22,
    "historical_difficulty": 0.25,
    "solution_steps": 0.10,
    "examiner_severity": 0.05,
}

COGNITIVE_ACTIONS = {
    "state": 0.24,
    "identify": 0.28,
    "recall": 0.28,
    "recognise": 0.30,
    "use": 0.45,
    "calculate": 0.52,
    "find": 0.52,
    "solve": 0.60,
    "determine": 0.62,
    "apply": 0.64,
    "interpret": 0.68,
    "sketch": 0.66,
    "model": 0.74,
    "evaluate": 0.75,
    "justify": 0.80,
    "derive": 0.84,
    "prove": 0.88,
    "show that": 0.82,
    "hypothesis": 0.86,
}

COMPLEX_CONTENT = {
    "conditional": 0.04,
    "differential equation": 0.10,
    "hypothesis": 0.10,
    "implicit": 0.08,
    "integration by parts": 0.09,
    "iteration": 0.06,
    "modelling": 0.07,
    "parametric": 0.08,
    "proof": 0.09,
    "transformation": 0.05,
    "vector": 0.05,
}


def _normalized_sigmoid(value: float, steepness: float = 4.0) -> float:
    """Map a value in [0, 1] monotonically back onto the full [0, 1] interval."""
    sigmoid = lambda x: 1 / (1 + math.exp(-x))  # noqa: E731
    low = sigmoid(-0.5 * steepness)
    high = sigmoid(0.5 * steepness)
    current = sigmoid((value - 0.5) * steepness)
    return (current - low) / (high - low)


def derive_objective_features(
    *,
    parent_complexity: float,
    parent_depth: int,
    parent_cognitive: float,
    parent_steps: int,
    title: str,
    description: str,
    prerequisite_count: int,
    objective_index: int,
) -> DifficultyFeatures:
    """Build explainable cold-start features for one syllabus learning objective."""
    text = f"{title} {description}".lower()
    detected_actions = [demand for action, demand in COGNITIVE_ACTIONS.items() if action in text]
    action_demand = max(detected_actions, default=parent_cognitive)
    cognitive_demand = max(
        0.0,
        min(1.0, 0.42 * parent_cognitive + 0.58 * action_demand),
    )

    content_adjustment = sum(
        adjustment for term, adjustment in COMPLEX_CONTENT.items() if term in text
    )
    token_count = len(text.split())
    length_adjustment = min(0.06, max(0, token_count - 12) * 0.003)
    symbolic_adjustment = 0.03 if any(symbol in text for symbol in ("frac", "^", "=")) else 0
    syllabus_complexity = max(
        0.0,
        min(
            1.0,
            0.72 * parent_complexity
            + 0.28 * action_demand
            + content_adjustment
            + length_adjustment
            + symbolic_adjustment,
        ),
    )

    action_steps = 2 if action_demand >= 0.80 else 1 if action_demand >= 0.62 else 0
    content_steps = min(3, round((content_adjustment + length_adjustment) * 12))
    solution_steps = max(1, parent_steps - 2 + action_steps + content_steps)
    prerequisite_depth = max(
        0,
        parent_depth + min(2, prerequisite_count) + min(2, max(0, objective_index - 1) // 4),
    )
    return DifficultyFeatures(
        syllabus_complexity=round(syllabus_complexity, 4),
        prerequisite_depth=prerequisite_depth,
        cognitive_demand=round(cognitive_demand, 4),
        solution_steps=solution_steps,
        evidence_confidence=0.3,
    )


def calculate_difficulty(features: DifficultyFeatures) -> DifficultyResult:
    prerequisite_depth = min(features.prerequisite_depth / 6, 1)
    solution_steps = min(math.log1p(features.solution_steps) / math.log1p(12), 1)

    normalized: dict[str, float] = {
        "syllabus_complexity": features.syllabus_complexity,
        "prerequisite_depth": prerequisite_depth,
        "cognitive_demand": features.cognitive_demand,
        "solution_steps": solution_steps,
    }
    # Missing official observations are absent, not aliases for syllabus features.
    # Reusing cognitive demand as historical difficulty (and complexity as examiner
    # severity) double-counts cold-start estimates and produces falsely extreme scores.
    if features.facility_rate is not None:
        normalized["historical_difficulty"] = 1 - features.facility_rate
    if features.examiner_severity is not None:
        normalized["examiner_severity"] = features.examiner_severity
    available_weight = sum(WEIGHTS[name] for name in normalized)
    contributions = {
        name: value * WEIGHTS[name] / available_weight for name, value in normalized.items()
    }
    for name in WEIGHTS:
        contributions.setdefault(name, 0.0)
    raw_score = sum(contributions.values())
    score = max(0.0, min(1.0, _normalized_sigmoid(raw_score)))

    if score < 0.34:
        label = "easy"
    elif score < 0.67:
        label = "medium"
    else:
        label = "hard"

    observed = 4
    observed += features.facility_rate is not None
    observed += features.examiner_severity is not None
    coverage = observed / 6
    confidence = max(0.05, min(1.0, features.evidence_confidence * (0.65 + 0.35 * coverage)))

    return DifficultyResult(
        score=round(score, 4),
        label=label,
        confidence=round(confidence, 4),
        raw_score=round(raw_score, 4),
        contributions={key: round(value, 4) for key, value in contributions.items()},
    )
