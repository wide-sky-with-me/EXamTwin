from examtwin.knowledge.difficulty import difficulty_label


def test_direct_model_scores_use_fixed_label_boundaries() -> None:
    assert difficulty_label(0.0) == "easy"
    assert difficulty_label(0.3399) == "easy"
    assert difficulty_label(0.34) == "medium"
    assert difficulty_label(0.6699) == "medium"
    assert difficulty_label(0.67) == "hard"
    assert difficulty_label(1.0) == "hard"
