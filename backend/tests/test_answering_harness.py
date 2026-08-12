from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from examtwin.assessment.answering_agent import (
    AnswerTask,
)
from examtwin.assessment.answering_agent.blocking import run_blocking_bounded
from examtwin.assessment.answering_agent.budget import budget_for_task
from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
    QuestionSpec,
    SubpartRequirement,
)
from examtwin.assessment.answering_agent.tools import (
    PairedExamLookupTool,
    ProbabilityCalculateTool,
)
from examtwin.assessment.answering_agent.tools.question_vision import QuestionVisionPayload
from examtwin.assessment.answering_agent.verification import verify_answer_contract
from examtwin.contracts import AnswerDiagram, AnswerImage, DiagramElement
from examtwin.platform.config import Settings


@pytest.mark.asyncio
async def test_blocking_answer_tool_has_an_enforced_timeout() -> None:
    with pytest.raises(TimeoutError, match="exceeded"):
        await run_blocking_bounded(time.sleep, 0.2, timeout=0.02)


@pytest.mark.asyncio
async def test_probability_tool_uses_explicit_binomial_tail_contract() -> None:
    tool = ProbabilityCalculateTool().bind(
        AgentRunContext(
            task=AnswerTask(subject_code="9660", question="Find a binomial probability.")
        )
    )

    result = await tool.acall(
        operation="binomial_pmf",
        n=20,
        p=0.015,
        k=2,
    )

    assert result.is_error is False
    assert "0.032567" in result.content
    assert "cdf uses P(X <= k); sf uses P(X > k)" in result.content


@pytest.mark.asyncio
async def test_probability_tool_computes_normal_upper_tail_directly() -> None:
    tool = ProbabilityCalculateTool().bind(
        AgentRunContext(task=AnswerTask(subject_code="9660", question="Find P(X > 115)."))
    )

    result = await tool.acall(
        operation="normal_sf",
        mean=120,
        standard_deviation=20 / 30**0.5,
        value=115,
    )

    assert result.is_error is False
    assert "event=P(X > 115.0)" in result.content
    assert "result=0.914548239884601" in result.content


def test_answer_contract_requires_every_subpart_and_visual_artifact() -> None:
    task = AnswerTask(
        subject_code="9660",
        question="Complete both parts.",
        question_spec=QuestionSpec(
            subparts=(
                SubpartRequirement(label="(a)", answer_kind="math_plot", required_tool="math_plot"),
                SubpartRequirement(
                    label="(b)", answer_kind="image", required_tool="image_generate"
                ),
            )
        ),
    )
    diagram = AnswerDiagram(
        title="Plot",
        tool_name="math_plot",
        elements=[DiagramElement(kind="point", x=1, y=1)],
    )
    image = AnswerImage(
        title="Illustration",
        content_url="/api/v1/answer-assets/0123456789abcdef0123456789abcdef.png",
    )

    with pytest.raises(RuntimeError, match="image_generate"):
        verify_answer_contract(task, "(a) plotted. (b) illustrated.", [diagram], [])
    with pytest.raises(RuntimeError, match=r"\(b\)"):
        verify_answer_contract(task, "(a) plotted.", [diagram], [image])

    verify_answer_contract(task, "(a) plotted. (b) illustrated.", [diagram], [image])


def test_answer_contract_accepts_question_prefixed_decimal_subpart_headings() -> None:
    task = AnswerTask(
        subject_code="9640",
        question="Complete both parts.",
        question_spec=QuestionSpec(
            subparts=(
                SubpartRequirement(label=".1"),
                SubpartRequirement(label=".2"),
            )
        ),
    )

    verify_answer_contract(
        task,
        "### 18.1\n\nFirst response.\n\n### Q18.2\n\nSecond response.",
        [],
        [],
    )

    with pytest.raises(RuntimeError, match=r"\.2"):
        verify_answer_contract(task, "### 18.1\n\nOnly the first response.", [], [])


def test_agent_context_assigns_exact_subpart_anchors_and_cross_type_order() -> None:
    task = AnswerTask(
        subject_code="9660",
        question="Complete both parts.",
        question_spec=QuestionSpec(
            subparts=(
                SubpartRequirement(label="(a)", required_tool="math_plot"),
                SubpartRequirement(label="(b)", required_tool="image_generate"),
            )
        ),
    )
    context = AgentRunContext(task=task)

    diagram = context.add_diagram(
        AnswerDiagram(
            title="Plot",
            tool_name="math_plot",
            elements=[DiagramElement(kind="point", x=1, y=1)],
        )
    )
    image = context.add_image(
        AnswerImage(
            title="Illustration",
            content_url="/api/v1/answer-assets/0123456789abcdef0123456789abcdef.png",
        )
    )

    assert (diagram.artifact_id, diagram.answer_anchor, diagram.answer_order) == (
        "artifact-1",
        "(a)",
        1,
    )
    assert (image.artifact_id, image.answer_anchor, image.answer_order) == (
        "artifact-2",
        "(b)",
        2,
    )
    verify_answer_contract(task, "### (a)\n\nPlot.\n\n### (b)\n\nIllustrate.", [diagram], [image])


def test_agent_context_requires_explicit_anchor_when_same_tool_serves_multiple_subparts() -> None:
    task = AnswerTask(
        subject_code="9660",
        question="Sketch both parts.",
        question_spec=QuestionSpec(
            subparts=(
                SubpartRequirement(label="(a)", required_tool="math_plot"),
                SubpartRequirement(label="(b)", required_tool="math_plot"),
            )
        ),
    )
    context = AgentRunContext(task=task)
    unplaced = AnswerDiagram(
        title="Plot",
        tool_name="math_plot",
        elements=[DiagramElement(kind="point", x=1, y=1)],
    )

    with pytest.raises(ValueError, match="answer_anchor is required"):
        context.add_diagram(unplaced)
    with pytest.raises(ValueError, match="must be one of"):
        context.add_diagram(unplaced.model_copy(update={"answer_anchor": "(c)"}))

    first = context.add_diagram(unplaced.model_copy(update={"answer_anchor": "(a)"}))
    second = context.add_diagram(unplaced.model_copy(update={"answer_anchor": "(b)"}))
    verify_answer_contract(
        task,
        "### (a)\n\nFirst plot.\n\n### (b)\n\nSecond plot.",
        [first, second],
        [],
    )


def test_answer_contract_rejects_duplicate_artifact_identity() -> None:
    task = AnswerTask(subject_code="9660", question="Sketch the graph.")
    diagrams = [
        AnswerDiagram(
            artifact_id="artifact-1",
            answer_anchor="whole",
            answer_order=1,
            title=f"Plot {index}",
            tool_name="math_plot",
            elements=[DiagramElement(kind="point", x=index, y=index)],
        )
        for index in (1, 2)
    ]

    with pytest.raises(RuntimeError, match="duplicate artifact ids"):
        verify_answer_contract(task, "Two plots.", diagrams, [])


def test_answer_contract_allows_blank_axes_fallback_but_not_existing_curve_fallback() -> None:
    diagram = AnswerDiagram(
        title="Plot",
        tool_name="math_plot",
        elements=[DiagramElement(kind="point", x=1, y=1)],
    )
    blank_axes = AnswerTask(
        subject_code="9660",
        question="On Figure 1 sketch the graph of y=x^2.",
        question_spec=QuestionSpec(
            subparts=(SubpartRequirement(answer_kind="math_plot", required_tool="math_plot"),)
        ),
    )
    existing_curve = AnswerTask(
        subject_code="9660",
        question="On Figure 4 draw the five trapezia under the existing curve.",
        question_spec=blank_axes.question_spec,
    )

    verify_answer_contract(blank_axes, "A mathematically equivalent plot is shown.", [diagram], [])
    with pytest.raises(RuntimeError, match="existing curve/grid"):
        verify_answer_contract(existing_curve, "The trapezia are shown.", [diagram], [])


def test_agent_budget_scales_with_subparts_but_respects_hard_caps() -> None:
    simple = budget_for_task(
        AnswerTask(subject_code="9660", question="State one fact."),
        iteration_cap=16,
        tool_call_cap=12,
        mandatory_tool_count=1,
    )
    complex_task = AnswerTask(
        subject_code="9660",
        question="Answer all parts.",
        question_spec=QuestionSpec(
            subparts=tuple(
                SubpartRequirement(label=f"({label})", answer_kind="numeric") for label in "abcdef"
            )
        ),
    )
    complex_budget = budget_for_task(
        complex_task,
        iteration_cap=9,
        tool_call_cap=7,
        mandatory_tool_count=2,
    )

    assert complex_budget.max_tool_calls > simple.max_tool_calls
    assert complex_budget.max_tool_calls == 7
    assert complex_budget.max_iterations == 9


@pytest.mark.asyncio
async def test_paired_exam_lookup_uses_only_the_exact_pair(tmp_path: Path) -> None:
    insert_markdown = tmp_path / "corpus" / "md" / "insert-1.md"
    insert_markdown.parent.mkdir(parents=True)
    insert_markdown.write_text("# Extract A: Supplied probability table")
    insert_pdf = tmp_path / "2026-jun-psm1-insert.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Extract A: supplied probability table")
    pdf.save(insert_pdf)
    pdf.close()

    class VisionProvider:
        def inspect(self, question: str, images: tuple[Any, ...]) -> QuestionVisionPayload:
            assert "Extract A" in question
            assert len(images) == 1
            assert images[0].page_number == 1
            assert images[0].media_type == "image/jpeg"
            assert images[0].content.startswith(b"\xff\xd8")
            return QuestionVisionPayload(
                observation="Extract A visibly shows P(X = 1) = 0.42 in the probability table."
            )

    class PairDocumentReader:
        def exact_pair_documents(
            self,
            pair_key: str,
            limit: int = 3,
        ) -> list[dict[str, Any]]:
            assert pair_key == "9660:2026:JUN:PSM1"
            return [
                {
                    "id": "mark-scheme-1",
                    "path": "/corpus/2026-jun-psm1-mark-scheme.pdf",
                    "source_type": "mark_scheme",
                    "authority_tier": "official",
                    "pair_key": "9660:2026:JUN:PSM1",
                },
                {
                    "id": "insert-1",
                    "path": str(insert_pdf),
                    "source_type": "insert",
                    "authority_tier": "official",
                    "pair_key": "9660:2026:JUN:PSM1",
                },
            ][:limit]

        def get_converted(self, document_id: str) -> dict[str, Any]:
            assert document_id == "insert-1"
            return {
                "id": document_id,
                "path": str(insert_pdf),
                "markdown_path": str(insert_markdown),
            }

    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="Using Extract A, find the probability.",
            question_number="4",
            pair_key="9660:2026:JUN:PSM1",
        )
    )
    tool = PairedExamLookupTool(
        PairDocumentReader(),
        Settings(object_store_local_root=tmp_path),
        vision_provider=VisionProvider(),
    ).bind(context)

    result = await tool.acall()

    assert result.is_error is False
    assert "supplied probability table" in result.content.casefold()
    assert "P(X = 1) = 0.42" in result.content
    assert "Correct answer: 0.42." not in result.content
    assert len(context.citations) == 1
    assert context.citations[0].source_type == "insert"
    assert context.citations[0].pair_key == "9660:2026:JUN:PSM1"


@pytest.mark.asyncio
async def test_paired_exam_lookup_falls_back_to_exact_pdf_text_on_context_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_pdf = tmp_path / "2024-jan-u1-insert.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Extract A: Spain 34 kg; Australia 59 kg")
    pdf.save(insert_pdf)
    pdf.close()

    class PairDocumentReader:
        def exact_pair_documents(
            self,
            pair_key: str,
            limit: int = 4,
        ) -> list[dict[str, Any]]:
            assert pair_key == "9640:2024:JAN:U1"
            return [
                {
                    "id": "insert-1",
                    "path": str(insert_pdf),
                    "source_type": "insert",
                    "authority_tier": "official",
                    "pair_key": pair_key,
                }
            ][:limit]

    def timed_out_context(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("context lookup exceeded 45 seconds")

    monkeypatch.setattr(
        "examtwin.assessment.answering_agent.tools.paired_exam.source_context",
        timed_out_context,
    )
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9640",
            question="Use Extract A to compare Australia with Spain.",
            question_number="17",
            pair_key="9640:2024:JAN:U1",
        )
    )
    tool = PairedExamLookupTool(
        PairDocumentReader(),
        Settings(object_store_local_root=tmp_path),
        timeout_seconds=1,
    ).bind(context)

    result = await tool.acall()

    assert result.is_error is False
    assert "Spain 34 kg; Australia 59 kg" in result.content
    assert "exact_pair=9640:2024:JAN:U1" in result.content
    assert len(context.citations) == 1
    assert context.citations[0].pair_key == "9640:2024:JAN:U1"
