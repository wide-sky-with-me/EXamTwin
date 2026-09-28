import importlib.util
from pathlib import Path


def test_evaluation_keeps_failures_in_denominator_and_separates_deferrals():
    path = Path(__file__).resolve().parents[2] / "scripts/evaluate_grading.py"
    spec = importlib.util.spec_from_file_location("evaluate_grading", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.metrics(
        [
            {"expected": 3, "awarded": 3},
            {"expected": 2, "awarded": 0},
            {"expected": 1, "error_type": "Timeout"},
            {"expected": None, "deferred": True, "awarded": 0},
        ]
    )
    assert result["cases"] == 4
    assert result["scored_cases"] == 3
    assert result["numeric_results"] == 2
    assert result["failures"] == 1
    assert result["exact"] == result["within_one"] == 1
    assert result["mae_on_numeric_results"] == 1
    assert result["deferred_correctly"] == result["review_cases"] == 1
