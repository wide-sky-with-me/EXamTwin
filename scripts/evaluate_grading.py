"""Opt-in paired-model evaluation through the production GradingService.

Gold labels never enter requests. Cases are frozen before calling models. All failures
remain in the denominator; this small author-labelled benchmark is not student validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from examtwin.assessment.grading import GradingService
from examtwin.contracts.evidence import AnswerImage
from examtwin.contracts.grading import GradeRequest
from examtwin.platform.config import get_settings
from examtwin.platform.structured_model import LiteLLMStructuredModel


class MemoryStore:
    def create(self, values):
        pass


def metrics(rows):
    scored = [r for r in rows if r["expected"] is not None]
    errors = [abs(r["awarded"] - r["expected"]) for r in scored if "awarded" in r]
    review = [r for r in rows if r["expected"] is None]
    return {
        "cases": len(rows),
        "failures": sum("error_type" in r for r in rows),
        "scored_cases": len(scored),
        "numeric_results": len(errors),
        "exact": sum(error == 0 for error in errors),
        "within_one": sum(error <= 1 for error in errors),
        "mae_on_numeric_results": sum(errors) / len(errors) if errors else None,
        "deferred_correctly": sum(r.get("deferred", False) for r in review),
        "review_cases": len(review),
        "execution_paths": {
            path: sum(r.get("execution_path") == path for r in rows)
            for path in ("model", "blank_answer", "deferred_image")
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--models", nargs="+", default=["gpt-5.6-sol", "gpt-6-sol"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    if not args.live:
        parser.error("Configured API calls require --live")
    source = Path(__file__).resolve().parents[1] / "backend/evals/grading_cases.json"
    raw = source.read_bytes()
    cases = json.loads(raw)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "cases.json").write_bytes(raw)
    settings = get_settings()
    credential = settings.llm_api_key.get_secret_value()

    def evaluate(job):
        name, case = job
        model = LiteLLMStructuredModel(
            model=name,
            provider=settings.litellm_provider,
            api_base=settings.llm_base_url,
            api_key=credential,
            reasoning_effort=settings.grading_reasoning_effort,
            max_retries=0,
        )
        grader = GradingService(
            SimpleNamespace(),
            MemoryStore(),
            settings,
            SimpleNamespace(subject_code=case["subject_code"]),
            structured_model=model,
        )
        row = {
            "id": case["id"],
            "model": name,
            "subject_code": case["subject_code"],
            "expected": case["expected"],
            "label_kind": case["label_kind"],
            "execution_path": (
                "deferred_image"
                if case["uninspectable"]
                else "model"
                if case["answer"].strip()
                else "blank_answer"
            ),
        }
        start = time.monotonic()
        try:
            result = grader.grade(
                GradeRequest(
                    question_markdown=case["question"],
                    answer_markdown=case["answer"],
                    mark_scheme_markdown=json.dumps(case["criteria"]),
                    max_marks=sum(c["max_marks"] for c in case["criteria"]),
                ),
                confirmed_criteria=case["criteria"],
                answer_images=[
                    AnswerImage(
                        title="Unavailable scan",
                        content_url="/api/v1/answer-assets/" + "a" * 32 + ".png",
                    )
                ]
                if case["uninspectable"]
                else (),
            )
            row.update(
                awarded=result.total_awarded,
                result=result.model_dump(mode="json"),
                deferred=any("暂缓授分" in w for w in result.warnings),
            )
        except Exception as error:
            # Provider exception bodies can contain secrets. Retain type, never body.
            row["error_type"] = type(error).__name__
        row["seconds"] = round(time.monotonic() - start, 3)
        (args.output / f"{name}-{case['id']}.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n"
        )
        print(name, case["id"], row.get("awarded", row.get("error_type")), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(evaluate, [(name, case) for case in cases for name in args.models]))
    summary = {
        "cases_sha256": hashlib.sha256(raw).hexdigest(),
        "reasoning_effort": settings.grading_reasoning_effort,
        "limitations": "Author-labelled short answers; no teacher labels, essays or student data.",
        "models": {
            name: {
                code: metrics([r for r in rows if r["model"] == name and r["subject_code"] == code])
                for code in ("9660", "9640")
            }
            for name in args.models
        },
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
