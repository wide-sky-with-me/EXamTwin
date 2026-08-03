from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from examtwin.answering_agent import (
    AnswerTask,
)
from examtwin.answering_agent.blocking import run_blocking_bounded
from examtwin.answering_agent.budget import budget_for_task
from examtwin.answering_agent.contracts import (
    AgentRunContext,
    QuestionSpec,
    SubpartRequirement,
)
from examtwin.answering_agent.tools import (
    PairedExamLookupTool,
    ProbabilityCalculateTool,
)
from examtwin.answering_agent.verification import verify_answer_contract
from examtwin.config import Settings
from examtwin.schemas import AnswerDiagram, AnswerImage, DiagramElement


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
    markdown = tmp_path / "corpus" / "md" / "ms-1.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Question 4\nAward 2 marks for the correct binomial value.")

    class PairDocumentReader:
        def exact_pair_documents(
            self,
            pair_key: str,
            limit: int = 3,
        ) -> list[dict[str, Any]]:
            assert pair_key == "9660:2026:JUN:PSM1"
            return [
                {
                    "id": "ms-1",
                    "path": "/corpus/2026-jun-psm1-ms.pdf",
                    "source_type": "mark_scheme",
                    "authority_tier": "official",
                    "pair_key": "9660:2026:JUN:PSM1",
                }
            ][:limit]

        def get_converted(self, document_id: str) -> dict[str, Any]:
            assert document_id == "ms-1"
            return {
                "id": "ms-1",
                "path": "/corpus/2026-jun-psm1-ms.pdf",
                "markdown_path": str(markdown),
            }

    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="Find the probability.",
            question_number="4",
            pair_key="9660:2026:JUN:PSM1",
        )
    )
    tool = PairedExamLookupTool(
        PairDocumentReader(),
        Settings(object_store_local_root=tmp_path),
    ).bind(context)

    result = await tool.acall()

    assert result.is_error is False
    assert "Award 2 marks" in result.content
    assert len(context.citations) == 1
    assert context.citations[0].pair_key == "9660:2026:JUN:PSM1"
