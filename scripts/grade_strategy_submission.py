"""Blind model assessment of frozen submissions, without targets or chosen strategies.

Uses the production grader with one fixed criterion per printed subpart. This is an
experimental model judgment, not a teacher gold label or the database rubric-review flow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from examtwin.assessment.grading import GradingService
from examtwin.contracts.evidence import AnswerDiagram
from examtwin.contracts.grading import GradeRequest
from examtwin.platform.config import get_settings
from examtwin.platform.structured_model import LiteLLMStructuredModel


class MemoryStore:
    def create(self, values):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="medium")
    args = parser.parse_args()
    if not args.live:
        parser.error("Configured model calls require --live")
    bundle = json.loads(args.bundle.read_text())
    questions = json.loads(args.questions.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    settings = get_settings().model_copy(
        update={
            "grading_mark_scheme_max_chars": 200000,
            "grading_question_max_chars": 100000,
        }
    )
    model = LiteLLMStructuredModel(
        model=args.model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        reasoning_effort=args.reasoning_effort,
        max_retries=0,
    )
    answers = {a["question_number"]: a for a in bundle["answers"]}

    def grade(question):
        number = question["number"]
        answer = answers[number]
        maximum = sum(part["marks"] for part in question["answer_requirements"])
        row = {"number": number, "available": maximum, "submission_status": answer["status"]}
        if answer["status"] in {"skipped", "failed"}:
            row.update(awarded=0, blank=True)
        else:
            try:
                criteria = [
                    {
                        "criterion_id": f"{number}:{part['label']}",
                        "max_marks": part["marks"],
                        "description": (
                            f"Assess ONLY question {number} part {part['label']}. "
                            "Apply method/accuracy/follow-through or best-fit levels rules "
                            "within this subpart, without inventing missing work. Other marks "
                            "belong to their own criteria. Official MS shared by all criteria:\n"
                            + (bundle["mark_scheme"] if index == 0 else "See first criterion.")
                        ),
                    }
                    for index, part in enumerate(question["answer_requirements"])
                ]
                context = question["question_markdown"]
                if bundle.get("source_booklet"):
                    context += "\nPaired source booklet:\n" + bundle["source_booklet"]
                grader = GradingService(
                    SimpleNamespace(),
                    MemoryStore(),
                    settings,
                    SimpleNamespace(subject_code=bundle["subject_code"]),
                    structured_model=model,
                )
                result = grader.grade(
                    GradeRequest(
                        question_markdown=context,
                        answer_markdown=answer["answer_markdown"],
                        mark_scheme_markdown=bundle["mark_scheme"],
                        max_marks=maximum,
                    ),
                    confirmed_criteria=criteria,
                    answer_diagrams=[AnswerDiagram.model_validate(d) for d in answer["diagrams"]],
                )
                row.update(
                    awarded=result.total_awarded,
                    result=result.model_dump(mode="json"),
                    deferred=any("暂缓授分" in w for w in result.warnings),
                )
            except Exception as error:
                row["error_type"] = type(error).__name__
        (args.output / f"q-{number}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2))
        print(number, row.get("awarded", row.get("error_type")), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(grade, questions))
    incomplete = any("error_type" in row or row.get("deferred") for row in rows)
    summary = {
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "subject_code": bundle["subject_code"],
        "bundle_sha256": hashlib.sha256(args.bundle.read_bytes()).hexdigest(),
        "questions_sha256": hashlib.sha256(args.questions.read_bytes()).hexdigest(),
        "status": "incomplete" if incomplete else "model_judgment_needs_teacher_review",
        "awarded_subtotal": sum(row.get("awarded", 0) for row in rows),
        "available": sum(row["available"] for row in rows),
        "failures": sum("error_type" in row for row in rows),
        "deferred": sum(bool(row.get("deferred")) for row in rows),
        "notes": "No target, plan, prior score or gold supplied to grader. No teacher review.",
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
