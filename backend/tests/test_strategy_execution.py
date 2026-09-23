from __future__ import annotations

import json

import pytest
from examtwin.assessment.answering_agent import (
    AnsweringAgentRuntime,
    AnswerTask,
    CapabilityRegistry,
)
from examtwin.assessment.answering_agent.contracts import QuestionSpec
from examtwin.assessment.answering_agent.finalization import AgentFinalPayload
from examtwin.assessment.answering_agent.strategy_review import (
    ModelStrategyScopeReviewer,
    StrategyScopeReview,
)
from examtwin.assessment.answering_agent.tools import KnowledgeSearchTool
from examtwin.assessment.answering_agent.verification import verify_answer_contract
from examtwin.assessment.strategy import plan_strategy
from examtwin.assessment.strategy_execution import apply_question_strategy
from examtwin.contracts.evidence import AnswerImage, SubpartRequirement
from examtwin.subjects.public import get_subject_package
from llama_index.core.llms import MockLLM

from backend.tests.answering_agent_support import _citation, _nodes
from backend.tests.test_strategy import analysis, option, questions, request


def test_wide_partial_interval_does_not_displace_a_feasible_full_answer():
    cheap = option("partial", "1", marks=6, exam=1).model_copy(
        update={"mode": "partial", "lower_marks": 0, "stop_before": "Omit evaluation."}
    )
    full = option("full", "1", marks=6, exam=5)
    plan = plan_strategy(
        request().model_copy(update={"score_tolerance": 1}),
        questions(1, 6),
        analysis([cheap, full]),
    )
    assert plan.selected.option_ids == ["full"]
    assert plan.status == "feasible_estimate"


def test_partial_without_explicit_boundary_is_not_plannable():
    partial = option("partial", "1").model_copy(update={"mode": "partial"})
    with pytest.raises(ValueError, match="停止边界"):
        plan_strategy(request(), questions(2), analysis([partial, option("2", "2")]))


def test_one_policy_essay_cannot_claim_a_narrow_scoring_ceiling():
    partial = option("one-policy", "1", marks=20).model_copy(
        update={
            "mode": "partial",
            "expected_marks": 8,
            "lower_marks": 5,
            "upper_marks": 11,
            "stop_before": "Do not introduce a second policy.",
        }
    )
    source = questions(1, 20)
    source[0]["subparts"][0]["answer_kind"] = "text"
    req = request().model_copy(update={"target_score": 8, "score_tolerance": 5})
    plan = plan_strategy(req, source, analysis([partial]))
    assert plan.analysis.options[0].lower_marks == 0
    assert plan.analysis.options[0].upper_marks == 20
    assert plan.status == "target_not_reached"
    assert not plan.selected.option_ids
    assert partial.upper_marks == 11


def test_execution_contains_time_boundary_and_only_local_skill_prerequisites():
    from examtwin.contracts.strategy import StrategySkill

    skills = [
        StrategySkill(
            code=code,
            title=code,
            study_minutes=1,
            learning_goal=code,
            prerequisites=["base"] if code == "local" else [],
        )
        for code in ("local", "other", "base")
    ]
    first = option("1", "1", skill="local").model_copy(
        update={
            "mode": "partial",
            "stop_before": "Do not draw.",
            "includes_required_artifact": False,
        }
    )
    plan = plan_strategy(
        request(), questions(2), analysis([first, option("2", "2", skill="other")], skills)
    )
    parts = [{"label": "whole", "marks": 3, "required_tool": "math_plot"}]
    result = apply_question_strategy(plan, {"number": "1"}, parts)
    assert result is not None
    scope = json.loads(result["strategy_instruction"])
    assert scope["approaches"][0]["exam_minutes"] == 5
    assert scope["approaches"][0]["stop_before"] == "Do not draw."
    assert {s["code"] for s in scope["learning_scope"]} == {"local", "base"}
    assert json.loads(result["requirements_json"])["subparts"][0]["required_tool"] is None
    assert parts[0]["required_tool"] == "math_plot"
    assert "target_score" not in scope


def test_skipped_label_reference_is_allowed_but_extra_heading_is_rejected():
    task = AnswerTask(
        subject_code="9660",
        question="(a) Differentiate. (b) Integrate.",
        question_spec=QuestionSpec(subparts=(SubpartRequirement(label="(a)"),)),
        strategy_instruction=json.dumps({"skipped_subparts": ["(b)"]}),
    )
    verify_answer_contract(task, "### (a)\ny'=2x, which could be used in (b) later.", [], [])
    with pytest.raises(RuntimeError, match="skipped"):
        verify_answer_contract(task, "### (a)\ny'=2x\n### Q1(b)\ny=x^3/3", [], [])


def test_scope_reviewer_receives_neither_target_estimates_nor_private_trace():
    class Model:
        def complete(self, messages, response_model, **kwargs):
            content = json.loads(messages[1].content)
            assert "target_score" not in json.dumps(content)
            assert "expected_marks" not in json.dumps(content)
            assert "exam_minutes" not in json.dumps(content)
            assert content["selected_approaches"][0]["stop_before"] == "Do not solve."
            return response_model(status="violation", explanation="已越过停止点", evidence=["x=2"])

    task = AnswerTask(
        subject_code="9660",
        question="Solve the quadratic.",
        strategy_instruction=json.dumps(
            {
                "target_score": 6,
                "approaches": [
                    {
                        "subpart": "whole",
                        "mode": "partial",
                        "approach": "Write the formula.",
                        "stop_before": "Do not solve.",
                        "expected_marks": 2,
                        "exam_minutes": 1,
                    }
                ],
            }
        ),
    )
    result = ModelStrategyScopeReviewer(Model()).review(task, "x=2", [], [], 1)
    assert result.status == "violation"


def test_uninspectable_raster_is_uncertain_without_guessing_from_metadata():
    class Model:
        def complete(self, *args, **kwargs):
            raise AssertionError("Cannot certify an image from its metadata")

    task = AnswerTask(subject_code="9660", question="Draw", strategy_instruction="{}")
    image = AnswerImage(
        title="Candidate image", content_url="/api/v1/answer-assets/" + "a" * 32 + ".png"
    )
    result = ModelStrategyScopeReviewer(Model()).review(task, "See image", [], [image], 1)
    assert result.status == "uncertain"


def test_old_partial_plan_fails_explicitly_without_silent_replanning():
    plan = plan_strategy(request(), questions(2), analysis([option("1", "1"), option("2", "2")]))
    plan.analysis.options[0].mode = "partial"
    with pytest.raises(ValueError, match="旧版部分作答策略"):
        apply_question_strategy(plan, {"number": "1"}, [{"label": "whole", "marks": 3}])


@pytest.mark.parametrize(
    "status", ["compliant", "violation", "uncertain", "unavailable", "no_evidence"]
)
def test_runtime_requires_independent_scope_acceptance_before_completion(status):
    calls = []

    class Runner:
        async def run(self, *, context, timeout, **kwargs):
            assert timeout < 30  # scope review has a reserved budget
            if status != "no_evidence":
                context.add_citation(_citation(_nodes("")[0]))
            return AgentFinalPayload(
                answer_markdown="The formula is b²−4ac. [S1]",
                citation_ids=["S1"],
                confidence=0.8,
                grounded=True,
                warnings=[],
            )

    class Reviewer:
        def review(self, task, answer, diagrams, images, timeout):
            calls.append(answer)
            assert 0 < timeout <= 60
            return StrategyScopeReview(
                status=status, explanation="独立范围检查", evidence=["The formula is b²−4ac."]
            )

    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(get_subject_package("oxfordaqa-mathematics-9660").require_skill(),),
        registry=CapabilityRegistry(tools=(KnowledgeSearchTool(_nodes, _citation),)),
        runner=Runner(),
        timeout=30,
        strategy_reviewer=None if status == "unavailable" else Reviewer(),
    )
    task = AnswerTask(subject_code="9660", question="State a formula.", strategy_instruction="{}")
    if status == "compliant":
        result = runtime.solve(task)
        assert result.grounded
        assert calls == [result.answer_markdown]
        assert any("compliant" in step.message for step in result.steps)
        assert any("范围复核依据：" in step.message for step in result.steps)
    else:
        with pytest.raises(RuntimeError, match="strategy"):
            runtime.solve(task)
    assert len(calls) == (0 if status in {"unavailable", "no_evidence"} else 1)
