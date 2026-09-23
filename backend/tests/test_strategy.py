from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from examtwin.assessment.paper_worker import PaperWorker
from examtwin.assessment.strategy import analyse_strategy, plan_strategy, question_inputs
from examtwin.contracts.papers import PaperQuestionAnswer
from examtwin.contracts.strategy import (
    StrategyAnalysis,
    StrategyOption,
    StrategyRequest,
    StrategySkill,
)
from examtwin.platform.config import Settings
from examtwin.subjects.public import subject_context


def request(**changes):
    return StrategyRequest(
        target_score=6,
        study_budget_minutes=60,
        exam_budget_minutes=30,
        reserve_minutes=5,
        **changes,
    )


def option(id, number, *, skill="shared", exam=5, study=0, marks=3, **changes):
    return StrategyOption(
        id=id,
        question_number=number,
        subpart="whole",
        mode="full",
        expected_marks=marks,
        lower_marks=marks - 1,
        upper_marks=marks,
        exam_minutes=exam,
        practice_minutes=study,
        skills=[skill],
        approach="Apply the selected basic method.",
        rationale="Shared preparation.",
        **changes,
    )


def analysis(options, skills=None):
    return StrategyAnalysis(
        options=options,
        skills=skills
        or [
            StrategySkill(
                code="shared",
                title="Basic method",
                study_minutes=30,
                learning_goal="Independently apply the method.",
            )
        ],
        assumptions=["Uncalibrated learner self-report."],
    )


def questions(count=3, marks=3):
    return [
        {
            "number": str(i + 1),
            "question_markdown": f"Question {i + 1}",
            "subparts": [{"label": "whole", "marks": marks}],
        }
        for i in range(count)
    ]


def test_shared_learning_counted_once_and_both_budgets_bind():
    plan = plan_strategy(
        request(), questions(), analysis([option(str(i), str(i)) for i in (1, 2, 3)])
    )
    assert plan.selected.expected_marks == 6
    assert plan.selected.study_minutes == 30
    assert plan.selected.exam_minutes == 10
    assert len(plan.skipped_subparts) == 1


def test_full_answers_cannot_be_probability_discounted_to_overselect_questions():
    opts = [option(str(i), str(i), marks=1) for i in range(1, 11)]
    for o in opts:
        o.expected_marks = 0.6
        o.lower_marks = 0
    req = request().model_copy(
        update={"target_score": 5, "score_tolerance": 0, "exam_budget_minutes": 120}
    )
    plan = plan_strategy(req, questions(10, 1), analysis(opts))
    assert plan.selected.expected_marks == 5
    assert plan.selected.lower_marks == plan.selected.upper_marks == 5
    assert len(plan.selected.option_ids) == 5
    assert all(o.expected_marks == 1 for o in plan.analysis.options)
    assert opts[0].expected_marks == 0.6  # raw model experiment remains inspectable


def test_partial_upper_bound_cannot_hide_a_high_scoring_answer():
    opt = option("partial", "1", marks=10).model_copy(
        update={
            "mode": "partial",
            "expected_marks": 6,
            "lower_marks": 4,
            "stop_before": "Do not evaluate the final expression.",
        }
    )
    req = request().model_copy(update={"score_tolerance": 1})
    plan = plan_strategy(req, questions(1, 10), analysis([opt]))
    assert plan.status == "target_not_reached"
    assert not plan.selected.option_ids


def test_study_and_exam_tradeoffs_are_preserved():
    opts = [option("slow", "1", marks=6, exam=20), option("fast", "1", marks=6, exam=5, study=25)]
    plan = plan_strategy(request(), questions(1, 6), analysis(opts))
    routes = {r.name: r for r in plan.alternatives}
    assert routes["less_study"].option_ids == ["slow"]
    assert routes["faster_exam"].option_ids == ["fast"]
    assert plan.selected.option_ids == ["fast"]


def test_dependencies_cannot_be_cherry_picked():
    opts = [
        option("first", "1", marks=3, exam=20),
        option("second", "1", marks=3, requires_options=["first"]),
    ]
    opts[0].subpart = "(a)"
    opts[1].subpart = "(b)"
    req = request().model_copy(update={"exam_budget_minutes": 25, "target_score": 3})
    source = [
        {
            "number": "1",
            "question_markdown": "(a) Find x. (b) Hence find y.",
            "subparts": [{"label": "(a)", "marks": 3}, {"label": "(b)", "marks": 3}],
        }
    ]
    plan = plan_strategy(req, source, analysis(opts))
    assert plan.selected.option_ids == ["first"]


def test_prerequisites_cost_time_and_infeasibility_is_explicit():
    skills = [
        StrategySkill(
            code="shared",
            title="Topic",
            study_minutes=30,
            prerequisites=["foundation"],
            learning_goal="Use topic.",
        ),
        StrategySkill(
            code="foundation",
            title="Foundation",
            study_minutes=40,
            learning_goal="Learn prerequisites.",
        ),
    ]
    plan = plan_strategy(
        request(), questions(2), analysis([option("1", "1"), option("2", "2")], skills)
    )
    assert plan.status == "target_not_reached"
    assert plan.selected.expected_marks == 0
    assert plan.selected.option_ids == []


@pytest.mark.parametrize("invalid", ["marks", "missing", "cycle"])
def test_rejects_invalid_analysis(invalid):
    opts = [option("1", "1"), option("2", "2")]
    if invalid == "marks":
        opts[0].upper_marks = 4
    if invalid == "missing":
        opts.pop()
    if invalid == "cycle":
        opts[0].requires_options = ["2"]
        opts[1].requires_options = ["1"]
    with pytest.raises(ValueError):
        plan_strategy(request(), questions(2), analysis(opts))


def test_request_and_printed_marks_validated():
    with pytest.raises(ValueError):
        request().model_validate({**request().model_dump(), "target_score": float("nan")})
    with pytest.raises(ValueError):
        plan_strategy(request(), questions(1), analysis([option("1", "1")]))
    with pytest.raises(ValueError):
        question_inputs([{"number": "1", "requirements_json": "{}"}])
    with pytest.raises(ValueError):
        question_inputs(
            [
                {
                    "number": "1",
                    "requirements_json": json.dumps(
                        {"total_marks": 4, "subparts": [{"label": "whole", "marks": 3}]}
                    ),
                }
            ]
        )


def test_analyzer_never_receives_target_or_mark_scheme():
    class Model:
        def complete(self, messages, response_model, **kwargs):
            content = json.loads(messages[1].content)
            assert set(content) == {"learner_self_report", "questions", "knowledge_catalog"}
            assert "target_score" not in content
            return analysis([option("1", "1"), option("2", "2")])

    analyse_strategy(Model(), request(), questions(2), [], 30)


@pytest.mark.parametrize("subject_code", ["9660", "9640"])
def test_worker_freezes_then_executes_only_selected_questions_and_resume_reuses_plan(subject_code):
    rows = [
        {
            "number": str(i),
            "position": i - 1,
            "status": "pending",
            "question_markdown": f"Q{i}",
            "requirements_json": json.dumps(
                {"total_marks": 3, "subparts": [{"label": "whole", "marks": 3}]}
            ),
        }
        for i in (1, 2, 3)
    ]
    plan = plan_strategy(
        request(), question_inputs(rows), analysis([option(str(i), str(i)) for i in (1, 2, 3)])
    )
    events = []
    completed = {}
    runtime = SimpleNamespace(
        list_questions=lambda _: rows,
        set_stage=lambda *a: None,
        save_strategy=lambda *a: events.append("frozen"),
        complete_question=lambda job, token, pos, answer: completed.update({pos: answer}),
    )
    service = SimpleNamespace(create_strategy=lambda *args: plan)
    settings = Settings(paper_question_concurrency=1)
    worker = PaperWorker(
        settings, subject_context(settings, subject_code), jobs=runtime, answer_service=service
    )

    def answer(job, token, row, unit):
        assert events[0] == "frozen"
        assert "strategy_instruction" in row
        events.append(row["number"])
        return PaperQuestionAnswer(
            number=row["number"],
            question_markdown=row["question_markdown"],
            answer_markdown="Selected answer",
            confidence=0.7,
            grounded=True,
        )

    worker._answer_pending_question = answer
    job = {"id": "job", "unit_code": None, "strategy_request_json": request().model_dump_json()}
    worker._answer(job, "lease")
    assert len(completed) == 3
    assert sum(a.skipped_by_strategy for a in completed.values()) == 1
    assert all(not a.answer_markdown for a in completed.values() if a.skipped_by_strategy)
    service.create_strategy = lambda *args: pytest.fail("must reuse the frozen plan")
    worker._answer(job, "lease")
    assert events.count("frozen") == 1


def test_bounded_search_reports_approximation():
    plan = plan_strategy(
        request(), questions(3), analysis([option(str(i), str(i)) for i in (1, 2, 3)]), max_states=2
    )
    assert plan.search_truncated
    assert any("近似" in warning for warning in plan.warnings)


def test_strategy_visual_contract_does_not_restore_skipped_drawing():
    from examtwin.assessment.answering_agent.contracts import AnswerTask, QuestionSpec
    from examtwin.assessment.answering_agent.run_policy import required_artifact_tools
    from examtwin.contracts.evidence import SubpartRequirement

    settings = Settings()
    skill = subject_context(settings, "9660").package.require_skill()
    task = AnswerTask(
        question="(a) Calculate x. (b) Sketch the curve.",
        subject_code="9660",
        strategy_instruction="Only (a)",
        question_spec=QuestionSpec(subparts=(SubpartRequirement(label="(a)", marks=3),)),
    )
    assert required_artifact_tools(skill, task) == ()


def test_empty_answer_receives_zero_without_model_call_and_requires_review():
    from examtwin.assessment.grading import GradingService
    from examtwin.contracts.grading import GradeRequest

    class Model:
        model_name = "must-not-call"

        def complete(self, *args, **kwargs):
            pytest.fail("Blank answer must not call a model")

    saved = []
    settings = Settings()
    service = GradingService(
        documents=SimpleNamespace(),
        assessments=SimpleNamespace(create=lambda values: saved.append(values)),
        settings=settings,
        subject=subject_context(settings, "9660"),
        structured_model=Model(),
    )
    result = service.grade(
        GradeRequest(
            answer_markdown="",
            question_markdown="Find x.",
            mark_scheme_markdown=json.dumps(
                [{"criterion_id": "1.A1", "description": "Correct x", "max_marks": 2}]
            ),
            max_marks=2,
        )
    )
    assert result.total_awarded == 0
    assert result.total_available == 2
    assert result.manual_review_required
    assert saved[0]["answer_markdown"] == ""
