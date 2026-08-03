from examtwin.schemas import DifficultyFeatures
from examtwin.services.difficulty import calculate_difficulty, derive_objective_features


def test_difficulty_is_normalized_and_monotonic() -> None:
    easy = calculate_difficulty(
        DifficultyFeatures(
            syllabus_complexity=0.2,
            prerequisite_depth=0,
            cognitive_demand=0.2,
            facility_rate=0.9,
            solution_steps=1,
            examiner_severity=0.1,
            evidence_confidence=0.9,
        )
    )
    hard = calculate_difficulty(
        DifficultyFeatures(
            syllabus_complexity=0.9,
            prerequisite_depth=6,
            cognitive_demand=0.9,
            facility_rate=0.1,
            solution_steps=12,
            examiner_severity=0.9,
            evidence_confidence=0.9,
        )
    )
    assert 0 <= easy.score < hard.score <= 1
    assert easy.label == "easy"
    assert hard.label == "hard"


def test_missing_official_evidence_lowers_confidence() -> None:
    inferred = calculate_difficulty(DifficultyFeatures(evidence_confidence=0.5))
    official = calculate_difficulty(
        DifficultyFeatures(
            facility_rate=0.5,
            examiner_severity=0.5,
            evidence_confidence=0.5,
        )
    )
    assert inferred.confidence < official.confidence
    assert inferred.contributions["historical_difficulty"] == 0
    assert inferred.contributions["examiner_severity"] == 0


def test_objectives_in_same_topic_receive_distinct_explainable_scores() -> None:
    recall = derive_objective_features(
        parent_complexity=0.7,
        parent_depth=3,
        parent_cognitive=0.65,
        parent_steps=6,
        title="State the definition of an integral.",
        description="Recall the notation used.",
        prerequisite_count=2,
        objective_index=1,
    )
    proof = derive_objective_features(
        parent_complexity=0.7,
        parent_depth=3,
        parent_cognitive=0.65,
        parent_steps=6,
        title="Derive an integration by parts result.",
        description="Prove the identity and apply it to a parametric model.",
        prerequisite_count=2,
        objective_index=2,
    )

    recall_result = calculate_difficulty(recall)
    proof_result = calculate_difficulty(proof)

    assert recall.evidence_confidence == proof.evidence_confidence == 0.3
    assert recall_result.score < proof_result.score
    assert recall.model_dump() != proof.model_dump()
