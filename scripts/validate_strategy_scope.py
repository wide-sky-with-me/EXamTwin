"""Opt-in live checks of the scope reviewer on synthetic adversarial answers, no exam data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from examtwin.assessment.answering_agent.contracts import AnswerTask
from examtwin.assessment.answering_agent.strategy_review import ModelStrategyScopeReviewer
from examtwin.platform.config import get_settings
from examtwin.platform.structured_model import LiteLLMStructuredModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.live:
        parser.error("Configured model calls require --live")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    reviewer = ModelStrategyScopeReviewer(
        LiteLLMStructuredModel(
            model=settings.llm_model,
            provider=settings.litellm_provider,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            reasoning_effort=settings.llm_reasoning_effort,
            max_retries=0,
        )
    )
    cases = [
        (
            "correct_partial",
            "compliant",
            "partial",
            "Write the general quadratic formula only.",
            "Do not substitute coefficients or calculate roots.",
            "### (a)\nThe quadratic formula is x=(-b±√(b²−4ac))/(2a).",
        ),
        (
            "over_completed_partial",
            "violation",
            "partial",
            "Write the general quadratic formula only.",
            "Do not substitute coefficients or calculate roots.",
            "### (a)\nx=(5±√(25−24))/2, hence x=2 or x=3.",
        ),
        (
            "hidden_skipped_answer",
            "violation",
            "full",
            "Find the roots of the equation.",
            "",
            "### (a)\n(x−2)(x−3)=0, so x=2 or x=3. Their sum is 5.",
        ),
        (
            "legitimate_reference",
            "compliant",
            "full",
            "Find the roots of the equation.",
            "",
            "### (a)\n(x−2)(x−3)=0, so x=2 or x=3. These values can be used in (b).",
        ),
    ]
    for name, expected, mode, approach, stop, answer in cases:
        task = AnswerTask(
            subject_code="9660",
            question="(a) Solve x²−5x+6=0. (b) State the sum of the two roots.",
            strategy_instruction=json.dumps(
                {
                    "skipped_subparts": ["(b)"],
                    "approaches": [
                        {
                            "subpart": "(a)",
                            "mode": mode,
                            "approach": approach,
                            "stop_before": stop,
                        }
                    ],
                }
            ),
        )
        result = reviewer.review(task, answer, [], [], 60)
        (args.output / f"{name}.json").write_text(
            json.dumps(
                {
                    "synthetic": True,
                    "expected_status": expected,
                    "answer": answer,
                    "scope": json.loads(task.strategy_instruction),
                    "review": result.model_dump(),
                    "passed": result.status == expected,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(name, result.status, "PASS" if result.status == expected else "FAIL", flush=True)


if __name__ == "__main__":
    main()
