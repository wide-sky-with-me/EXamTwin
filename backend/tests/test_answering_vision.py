from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from examtwin.assessment.answering_agent import (
    AnsweringAgentRuntime,
    AnswerTask,
    CapabilityRegistry,
)
from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
    QuestionImage,
    ToolReplayPayload,
)
from examtwin.assessment.answering_agent.policies import select_answering_tool_names
from examtwin.assessment.answering_agent.tools import (
    KnowledgeSearchTool,
    LiteLLMQuestionVisionProvider,
    QuestionVisionTool,
)
from examtwin.platform.config import Settings
from examtwin.subjects.packages import get_subject_package
from llama_index.core.llms import (
    ImageBlock,
    MockLLM,
    TextBlock,
)
from llama_index.llms.openai.utils import to_openai_message_dicts

from backend.tests.answering_agent_support import (
    CapturingVisionLLM,
    FailingVisionLLM,
    MustNotRun,
    NoEvidenceRunner,
    ScriptedReActLLM,
    _citation,
    _nodes,
)

MATHEMATICS_9660 = get_subject_package("oxfordaqa-mathematics-9660").require_skill()


@pytest.mark.parametrize(
    ("question", "expected"),
    (
        (
            "### (c)\nSketch the graph of the curve $y=f(-x)$ on the axes in Figure 1.",
            "math_plot",
        ),
        ("7 (b) On Figure 3 sketch the graph of $y=x^2$.", "math_plot"),
        (
            "Complete their table in Figure 3, giving your values to four decimal "
            "places.\n\n### (b)\nDraw the five trapezia on Figure 4 and explain why.",
            "math_plot",
        ),
        (
            "8 (a) (iii) Sketch on Figure 3 the total region represented by "
            "$P((X-mu)^2>c^2)$ where $c$ is a\npositive constant by shading the "
            "appropriate area and labelling the "
            "$x$-axis.",
            "math_plot",
        ),
        ("9 (a) Complete the force diagram.", "math_diagram"),
        ("Figure 5 shows two curves. Find the area of the shaded region.", None),
    ),
)
def test_mathematics_skill_selects_only_the_required_answer_visual(
    question: str,
    expected: str | None,
) -> None:
    assert MATHEMATICS_9660.required_visual_tool(question) == expected


def test_answering_policy_exposes_only_task_relevant_conditional_tools() -> None:
    selected = select_answering_tool_names(
        MATHEMATICS_9660,
        AnswerTask(
            subject_code="9660",
            question="Sketch y=x^2 on the axes using Extract A.",
            pair_key="oxfordaqa:9660:2025:june:p1",
            question_images=(QuestionImage(page_number=1, content=b"\xff\xd8\xff\xd9"),),
        ),
    )

    assert "question_vision" in selected
    assert "paired_exam_lookup" in selected
    assert "math_plot" in selected
    assert "math_diagram" not in selected
    assert "image_generate" not in selected

    without_insert_reference = select_answering_tool_names(
        MATHEMATICS_9660,
        AnswerTask(
            subject_code="9660",
            question="Solve x^2 = 4.",
            pair_key="oxfordaqa:9660:2025:june:p1",
        ),
    )
    assert "paired_exam_lookup" not in without_insert_reference


def test_factory_uses_paper_vision_model_without_changing_main_model(
    monkeypatch,
) -> None:
    from examtwin.assessment.answering_agent import factory

    calls: list[dict[str, Any]] = []
    vision_settings: list[Settings] = []
    vision_provider = object()

    def fake_build_llm(_settings: Settings, **kwargs: Any) -> MockLLM:
        calls.append(kwargs)
        return MockLLM()

    monkeypatch.setattr(factory, "build_llm", fake_build_llm)
    monkeypatch.setattr(
        factory,
        "build_question_vision_provider",
        lambda candidate: vision_settings.append(candidate) or vision_provider,
    )
    settings = Settings(
        llm_model="main-math-model",
        paper_vision_model="verified-vision-model",
    )

    runtime = factory.build_answering_runtime(
        settings,
        retriever=_nodes,
        citation_factory=_citation,
        final_answer_provider=object(),
    )

    assert vision_settings == [settings]
    assert calls == [
        {
            "timeout": settings.answer_agent_timeout,
            "max_retries": 1,
        }
    ]
    assert runtime.llm is not None
    resolved = asyncio.run(
        runtime.registry.resolve(
            MATHEMATICS_9660,
            AgentRunContext(task=AnswerTask(subject_code="9660", question="Sketch y=x^2.")),
        )
    )
    assert "math_plot" in {tool.spec.name for tool in resolved}


def test_litellm_question_vision_uses_images_and_strict_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": "",
                                    "parsed": None,
                                    "reasoning_content": json.dumps(
                                        {
                                            "observation": (
                                                "The page shows a graph with a shaded region "
                                                "above the curve."
                                            )
                                        }
                                    ),
                                },
                            )()
                        },
                    )()
                ]
            },
        )()

    monkeypatch.setattr(
        "examtwin.assessment.answering_agent.tools.question_vision.completion",
        fake_completion,
    )
    provider = LiteLLMQuestionVisionProvider(
        "vision-model",
        "https://models.invalid/v1",
        "test-key",
        timeout=30,
    )

    payload = provider.inspect(
        "Read the graph.",
        (QuestionImage(page_number=2, content=b"\xff\xd8\xff\xd9"),),
    )

    assert payload.observation.startswith("The page shows a graph")
    assert captured["model"] == "openai/vision-model"
    assert captured["response_format"].__name__ == "QuestionVisionPayload"
    assert captured["extra_body"] == {"enable_thinking": False}
    parts = captured["messages"][0]["content"]
    assert any(
        part["type"] == "image_url"
        and part["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/")
        for part in parts
    )


def test_gpt56_question_vision_uses_reasoning_without_qwen_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_completion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return type(
            "Completion",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {
                                    "content": json.dumps(
                                        {
                                            "observation": (
                                                "The page shows a labelled triangle "
                                                "with a right-angle marker."
                                            )
                                        }
                                    ),
                                    "parsed": None,
                                    "reasoning_content": None,
                                },
                            )()
                        },
                    )()
                ]
            },
        )()

    monkeypatch.setattr(
        "examtwin.assessment.answering_agent.tools.question_vision.completion",
        fake_completion,
    )
    provider = LiteLLMQuestionVisionProvider(
        "gpt-5.6-terra",
        "https://models.invalid/v1",
        "test-key",
        timeout=30,
        reasoning_effort="low",
    )

    provider.inspect(
        "Read the triangle.",
        (QuestionImage(page_number=2, content=b"\xff\xd8\xff\xd9"),),
    )

    assert captured["reasoning_effort"] == "low"
    assert "temperature" not in captured
    assert "extra_body" not in captured


@pytest.mark.asyncio
async def test_question_vision_converts_trusted_jpeg_to_image_block_and_image_url() -> None:
    vision_llm = CapturingVisionLLM()
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="Read the graph.",
            question_images=(QuestionImage(page_number=2, content=b"\xff\xd8\xff\xd9"),),
        )
    )

    output = (
        await QuestionVisionTool(  # type: ignore[arg-type]
            vision_llm,
            timeout_seconds=2,
        )
        .bind(context)
        .acall()
    )

    assert output.is_error is False
    assert vision_llm.calls == 1
    blocks = vision_llm.messages[0].blocks
    assert any(isinstance(block, TextBlock) for block in blocks)
    assert any(
        isinstance(block, ImageBlock)
        and block.resolve_image(as_base64=False).read() == b"\xff\xd8\xff\xd9"
        for block in blocks
    )
    serialized = to_openai_message_dicts(vision_llm.messages)
    image_parts = [
        part
        for part in serialized[0]["content"]  # type: ignore[index, union-attr]
        if part["type"] == "image_url"
    ]
    assert image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/")


@pytest.mark.asyncio
async def test_question_vision_rejects_a_generic_placeholder() -> None:
    vision_llm = CapturingVisionLLM("bounded factual visual inspection")
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="Read the graph.",
            question_images=(QuestionImage(page_number=2, content=b"\xff\xd8\xff\xd9"),),
        )
    )

    with pytest.raises(ValueError, match="placeholder"):
        await (
            QuestionVisionTool(  # type: ignore[arg-type]
                vision_llm,
                timeout_seconds=2,
            )
            .bind(context)
            .acall()
        )


def test_runtime_forces_question_vision_and_injects_observation_into_main_llm() -> None:
    main_llm = ScriptedReActLLM()
    vision_llm = CapturingVisionLLM("The original page has a shaded region above y = x^2.")
    runtime = AnsweringAgentRuntime(
        llm=main_llm,
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                QuestionVisionTool(vision_llm, timeout_seconds=2),  # type: ignore[arg-type]
                KnowledgeSearchTool(_nodes, _citation),
            )
        ),
        max_iterations=4,
        max_tool_calls=2,
        timeout=15,
    )

    result = runtime.solve(
        AnswerTask(
            subject_code="9660",
            question="State the quadratic discriminant for the shown graph.",
            question_images=(QuestionImage(page_number=3, content=b"\xff\xd8\xff\xd9"),),
        )
    )

    assert result.grounded is True
    assert vision_llm.calls == 1
    assert "shaded region above y = x^2" in main_llm.prompts[0]
    assert any(
        step.tool_name == "question_vision" and step.status == "completed" for step in result.steps
    )


def test_runtime_reuses_persisted_question_vision_for_identical_pages() -> None:
    class ReplayLedger:
        calls: list[str] = []

        def start_run(self, **_kwargs: Any) -> None:
            self.calls.append("start_run")

        def find_replay(self, **_kwargs: Any) -> ToolReplayPayload:
            self.calls.append("find_replay")
            return ToolReplayPayload(
                observation="The original page shows a labelled quadratic graph."
            )

        def tool_started(self, **_kwargs: Any) -> None:
            raise AssertionError("a replayed vision call must not start another provider call")

        def tool_finished(self, **_kwargs: Any) -> None:
            raise AssertionError("a replayed vision call must not write another result")

        def finish_run(self, status: str) -> None:
            self.calls.append(f"finish_run:{status}")

    vision_llm = CapturingVisionLLM()
    ledger = ReplayLedger()
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                QuestionVisionTool(vision_llm, timeout_seconds=2),  # type: ignore[arg-type]
                KnowledgeSearchTool(_nodes, _citation),
            )
        ),
        runner=NoEvidenceRunner(),
        question_vision_replay_identity="test-vision-provider-v1",
    )

    result = runtime.solve(
        AnswerTask(
            subject_code="9660",
            question="Read the original graph.",
            question_images=(QuestionImage(page_number=1, content=b"\xff\xd8\xff\xd9"),),
        ),
        ledger=ledger,
    )

    assert vision_llm.calls == 0
    assert ledger.calls == ["find_replay", "finish_run:completed"]
    assert any("持久执行账本复用" in step.message for step in result.steps)


def test_runtime_does_not_call_question_vision_without_images() -> None:
    vision_llm = CapturingVisionLLM()
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                QuestionVisionTool(vision_llm, timeout_seconds=2),  # type: ignore[arg-type]
                KnowledgeSearchTool(_nodes, _citation),
            )
        ),
        runner=NoEvidenceRunner(),
    )

    runtime.solve(AnswerTask(subject_code="9660", question="A Markdown-only question."))

    assert vision_llm.calls == 0


def test_question_vision_failure_propagates_before_main_reasoning() -> None:
    vision_llm = FailingVisionLLM()
    runner = MustNotRun()
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                QuestionVisionTool(vision_llm, timeout_seconds=2),  # type: ignore[arg-type]
                KnowledgeSearchTool(_nodes, _citation),
            )
        ),
        runner=runner,
    )

    with pytest.raises(RuntimeError, match="vision provider unavailable"):
        runtime.solve(
            AnswerTask(
                subject_code="9660",
                question="Read the original graph.",
                question_images=(QuestionImage(page_number=1, content=b"\xff\xd8\xff\xd9"),),
            )
        )

    assert vision_llm.calls == 1
    assert runner.calls == 0


def test_runtime_uses_one_total_budget_across_vision_and_reasoning() -> None:
    class SlowRunner:
        timeout: float | None = None

        async def run(self, *, timeout: float, **_kwargs: Any) -> str:
            self.timeout = timeout
            await asyncio.sleep(0.4)
            raise AssertionError("the total runtime deadline should cancel this runner")

    vision_llm = CapturingVisionLLM(
        "The original page shows a labelled curve with two marked intercepts.",
        delay=0.1,
    )
    runner = SlowRunner()
    runtime = AnsweringAgentRuntime(
        llm=MockLLM(),
        skills=(MATHEMATICS_9660,),
        registry=CapabilityRegistry(
            tools=(
                QuestionVisionTool(vision_llm, timeout_seconds=1),  # type: ignore[arg-type]
                KnowledgeSearchTool(_nodes, _citation),
            )
        ),
        runner=runner,
        timeout=0.3,
    )
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        runtime.solve(
            AnswerTask(
                subject_code="9660",
                question="Read the original graph.",
                question_images=(QuestionImage(page_number=1, content=b"\xff\xd8\xff\xd9"),),
            )
        )

    assert time.monotonic() - started < 0.4
    assert runner.timeout is not None
    assert 0 < runner.timeout < 0.25
