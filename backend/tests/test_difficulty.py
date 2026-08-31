from examtwin.knowledge.difficulty import difficulty_label
from examtwin.knowledge.difficulty_assessment import difficulty_system_prompt


def test_direct_model_scores_use_fixed_label_boundaries() -> None:
    assert difficulty_label(0.0) == "easy"
    assert difficulty_label(0.3399) == "easy"
    assert difficulty_label(0.34) == "medium"
    assert difficulty_label(0.6699) == "medium"
    assert difficulty_label(0.67) == "hard"
    assert difficulty_label(1.0) == "hard"


def test_model_prompt_uses_the_same_label_boundaries() -> None:
    prompt = difficulty_system_prompt()

    assert "easy [0,0.34)" in prompt
    assert "medium [0.34,0.67)" in prompt
    assert "hard [0.67,1]" in prompt
