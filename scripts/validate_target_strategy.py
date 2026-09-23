"""Opt-in live double-subject strategy experiment; preserves first attempts, never uses old answers.

Uses the production splitter/analyzer/optimizer with local verified QP/IN text. A standalone
structured answer call exercises the frozen approach without the deployed retrieval/tool worker;
this is an experiment, not a claim of full production end-to-end validation or student calibration.
The independent judge receives only blind answer bundles, not targets or strategy estimates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
from examtwin.assessment.answering_agent.contracts import QuestionImage
from examtwin.assessment.answering_agent.tools.question_vision import LiteLLMQuestionVisionProvider
from examtwin.assessment.paper_answering import PaperAnswerService
from examtwin.assessment.strategy import analyse_strategy, plan_strategy
from examtwin.contracts.strategy import StrategyAnalysis, StrategyRequest
from examtwin.platform.agent_runtime import StructuredTask, StructuredTaskRunner
from examtwin.platform.config import get_settings
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import subject_context
from pydantic import BaseModel


class Answer(BaseModel):
    question_number: str
    answer_markdown: str


class Answers(BaseModel):
    answers: list[Answer]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-inputs", type=Path)
    parser.add_argument("--reuse-visual-inputs", type=Path)
    parser.add_argument("--main-planner", action="store_true")
    parser.add_argument("--reuse-analysis", type=Path)
    parser.add_argument("--full-only", action="store_true")
    parser.add_argument("--plan-only", action="store_true", help="Freeze plans without answering")
    parser.add_argument(
        "--live", action="store_true", help="Authorize bounded configured-model calls"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Live model calls require --live")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    if settings.llm_api_key is None:
        raise RuntimeError("Configured model key is unavailable")
    root = Path(__file__).resolve().parents[1]
    model = LiteLLMStructuredModel(
        model=settings.paper_split_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        reasoning_effort=settings.paper_split_reasoning_effort,
        max_retries=0,
    )
    answer_model = LiteLLMStructuredModel(
        model=settings.llm_model,
        provider=settings.litellm_provider,
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key.get_secret_value(),
        reasoning_effort=settings.llm_reasoning_effort,
        max_retries=0,
    )
    if args.main_planner:
        model = answer_model
    for code, fixture_id, exam in [
        ("9660", "oxfordaqa-mathematics-9660-2019-jan-p1", 90),
        ("9640", "oxfordaqa-economics-9640-2024-jan-u1", 105),
    ]:
        destination = args.output / code
        destination.mkdir()

        def save(name, value, destination=destination):
            (destination / name).write_text(
                json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        fixture = json.loads(
            (root / "data/test-fixtures" / fixture_id / "fixture.json").read_text()
        )
        source = {}
        for kind in ("question_paper", "source_booklet", "mark_scheme"):
            if kind not in fixture:
                continue
            item = fixture[kind]
            content = (root / item["relative_path"]).read_bytes()
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                source[kind] = "\n\n".join(
                    f"<!-- examtwin:physical-page={i + 1} -->\n{p.get_text()}"
                    for i, p in enumerate(pdf)
                )
        save("provenance.json", {k: fixture[k] for k in source})
        stage = "splitting"
        print(f"{code}: verified sources; splitting", flush=True)
        try:
            if args.reviewed_inputs:
                reviewed = json.loads((args.reviewed_inputs / f"{code}.json").read_text())
                split = [{**q, "answer_requirements": q["subparts"]} for q in reviewed]
            else:
                service = PaperAnswerService(
                    settings,
                    subject_context(settings, code),
                    rag=object(),
                    catalog_loader=lambda _: [],
                    structured_model=model,
                )
                split = service.split_questions(
                    source["question_paper"], unit_code=fixture["unit_code"]
                )
            save("split.json", split)
            questions = [
                {
                    "number": q["number"],
                    "question_markdown": q["question_markdown"],
                    "subparts": q["answer_requirements"],
                }
                for q in split
            ]
            if args.reuse_visual_inputs:
                previous = args.reuse_visual_inputs / code
                provenance = json.loads((previous / "provenance.json").read_text())
                for kind in source:
                    assert provenance[kind]["sha256"] == fixture[kind]["sha256"]
                questions = json.loads((previous / "visual-inputs.json").read_text())
                save("visual-inputs.json", questions)
            elif args.reviewed_inputs:
                stage = "source_vision"
                visual_numbers = {"6"} if code == "9660" else {"10", "15"}
                vision = LiteLLMQuestionVisionProvider(
                    settings.paper_vision_model,
                    settings.llm_base_url,
                    settings.llm_api_key.get_secret_value(),
                    provider=settings.litellm_provider,
                    timeout=90,
                    question_max_chars=12000,
                    max_output_tokens=4000,
                )
                with pymupdf.open(root / fixture["question_paper"]["relative_path"]) as pdf:
                    for question, original in zip(questions, split, strict=True):
                        if question["number"] not in visual_numbers:
                            continue
                        images = [
                            QuestionImage(
                                page_number=p,
                                content=pdf[p - 1]
                                .get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
                                .tobytes("jpeg"),
                            )
                            for p in original["source_pages"]
                        ]
                        observation = vision.inspect(question["question_markdown"], images)
                        question["question_markdown"] += (
                            "\n\nVerified visual facts:\n" + observation.observation
                        )
                save("visual-inputs.json", questions)
            if "source_booklet" in source:
                questions[0]["paired_source_booklet"] = {
                    "checksum": fixture["source_booklet"]["sha256"],
                    "content_markdown": source["source_booklet"],
                }
            stage = "analysis"
            req = StrategyRequest(
                target_score=48, study_budget_minutes=720, exam_budget_minutes=exam
            )
            if args.reuse_analysis:
                previous = args.reuse_analysis / code
                provenance = json.loads((previous / "provenance.json").read_text())
                for kind in source:
                    assert provenance[kind]["sha256"] == fixture[kind]["sha256"]
                analysis = StrategyAnalysis.model_validate_json(
                    (previous / "analysis.json").read_text()
                )
                save(
                    "reused-analysis.json",
                    {
                        "source": str(previous),
                        "full_only": args.full_only,
                        "note": "Fixed pre-grading costs; no score feedback in planning.",
                    },
                )
            else:
                analysis = analyse_strategy(model, req, questions, [], 180)
            if args.full_only:
                analysis = analysis.model_copy(
                    update={"options": [o for o in analysis.options if o.mode == "full"]}
                )
            save("analysis.json", analysis.model_dump())
            plans = []
            for target in (32, 48, 64):
                for study in (360, 720):
                    case = req.model_copy(
                        update={"target_score": float(target), "study_budget_minutes": study}
                    )
                    plan = plan_strategy(case, questions, analysis)
                    plan.analysis_model = None if args.reuse_analysis else model.model_name
                    save(f"plan-{target}-{study}.json", plan.model_dump())
                    plans.append(plan)
            plan = next(
                p
                for p in plans
                if p.request.target_score == 48 and p.request.study_budget_minutes == 720
            )
            if args.plan_only:
                save("result.json", {"status": "plans_frozen", "production_worker": False})
                print(f"{code}: plans frozen without answering", flush=True)
                continue
            selected = {o.id: o for o in analysis.options}
            approaches = [
                {
                    "question_number": selected[i].question_number,
                    "subpart": selected[i].subpart,
                    "mode": selected[i].mode,
                    "approach": selected[i].approach,
                }
                for i in plan.selected.option_ids
            ]
            stage = "answering"
            print(f"{code}: plan frozen; generating first answer", flush=True)
            response = StructuredTaskRunner(answer_model).run(
                StructuredTask(
                    system_prompt=(
                        "Execute ONLY the frozen selected approaches. Answer in English. "
                        "Leave all other parts blank. For partial approaches stop at the boundary. "
                        "Do not invent mistakes or include strategy commentary. Use exact printed "
                        "subpart headings. No mark scheme is available. Return one answer per "
                        "selected question. This standalone experiment has no diagram tools: "
                        "record any required diagram limitation honestly."
                    ),
                    user_content=json.dumps(
                        {
                            "questions": questions,
                            "approaches": approaches,
                            "learning_scope": [
                                s.model_dump()
                                for s in analysis.skills
                                if s.code in plan.selected.skill_codes
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
                Answers,
                timeout=180,
            )
            save("first-answers.json", response.model_dump())
            save(
                "blind-judge-bundle.json",
                {
                    "subject_code": code,
                    "question_paper": source["question_paper"],
                    "source_booklet": source.get("source_booklet"),
                    "mark_scheme": source["mark_scheme"],
                    "answers": response.model_dump()["answers"],
                    "notes": (
                        "Standalone fresh AI answer; unlisted questions are blank. "
                        "Grade against MS without access to target."
                    ),
                },
            )
            save(
                "result.json", {"status": "awaiting_independent_judge", "production_worker": False}
            )
        except Exception as error:
            # Do not log provider exception bodies: they may contain credentials/request content.
            save(
                "result.json",
                {
                    "status": "blocked",
                    "stage": stage,
                    "error_type": type(error).__name__,
                    "detail": str(error).replace(
                        settings.llm_api_key.get_secret_value(), "[redacted]"
                    )[:1500],
                    "note": "First attempt retained; no retry or historical-job mutation.",
                },
            )
            print(f"{code}: {stage} blocked ({type(error).__name__}); no retry", flush=True)


if __name__ == "__main__":
    main()
