from __future__ import annotations

from typing import Any

import pytest
from examtwin.answering_agent import (
    AnswerTask,
)
from examtwin.answering_agent.contracts import (
    AgentRunContext,
)
from examtwin.answering_agent.tools import (
    KnowledgeSearchTool,
    MathCalculateTool,
    MathDiagramTool,
    MathPlotTool,
    ProbabilityCalculateTool,
)

from backend.tests.answering_agent_support import (
    ToolUsingRunner,
    _citation,
    _nodes,
    _runtime,
)


def test_runtime_executes_tools_and_uses_observations_in_final_answer() -> None:
    events = []
    result = _runtime(ToolUsingRunner()).solve(
        AnswerTask(subject_code="9660", question="Solve x^2 - 5x + 6 = 0."),
        event_sink=events.append,
    )

    assert result.answer_markdown == "The roots are 2 and 3. [S1]"
    assert result.grounded is True
    assert result.citations[0].document_id == "doc-1"
    assert result.diagrams[0].title == "Two roots on an axis"
    assert any(step.tool_name == "knowledge_search" for step in events)
    assert events[-1].phase == "finalizing"
    assert events[-1].status == "completed"


def test_all_math_tool_schemas_are_serializable_for_react_prompt() -> None:
    context = AgentRunContext(task=AnswerTask(subject_code="9660", question="Solve and draw it."))
    tools = (
        KnowledgeSearchTool(_nodes, _citation).bind(context),
        MathCalculateTool().bind(context),
        ProbabilityCalculateTool().bind(context),
        MathPlotTool().bind(context),
        MathDiagramTool().bind(context),
    )

    for tool in tools:
        assert tool.metadata.get_parameters_dict()["type"] == "object"


@pytest.mark.asyncio
async def test_math_plot_tool_creates_validated_coordinate_artifact() -> None:
    context = AgentRunContext(task=AnswerTask(subject_code="9660", question="Sketch y=x^2-4."))
    tool = MathPlotTool().bind(context)

    result = await tool.acall(
        title="Sketch of y = x² - 4",
        caption="The curve crosses the x-axis at (-2, 0) and (2, 0).",
        x_range=[-4, 4],
        y_range=[-5, 12],
        curves=[
            {
                "expression": "x^2 - 4",
                "label": "y = x² - 4",
                "emphasis": True,
            }
        ],
        points=[
            {"x": -2, "y": 0, "label": "(-2, 0)"},
            {"x": 2, "y": 0, "label": "(2, 0)"},
            {"x": 0, "y": -4, "label": "(0, -4)"},
        ],
        labels=[{"x": 2, "y": 0, "text": "crosses"}],
    )

    assert result.is_error is False
    assert len(context.diagrams) == 1
    diagram = context.diagrams[0]
    assert diagram.title == "Sketch of y = x² - 4"
    assert diagram.tool_name == "math_plot"
    assert diagram.legend[0].label == "y = x² - 4"
    assert diagram.legend[0].tone == "primary"
    assert any(element.kind == "polyline" for element in diagram.elements)
    assert sum(element.kind == "point" for element in diagram.elements) == 3
    assert all(len(element.points) <= 120 for element in diagram.elements)
    assert any(
        element.kind == "line" and element.dashed and element.tone == "muted"
        for element in diagram.elements
    )
    point_labels = [
        element
        for element in diagram.elements
        if element.kind == "text" and element.text in {"(-2, 0)", "(2, 0)", "(0, -4)"}
    ]
    assert len({(element.x, element.y) for element in point_labels}) == 3
    crosses = next(
        element
        for element in diagram.elements
        if element.kind == "text" and element.text == "crosses"
    )
    crossing_point = max(
        (element for element in diagram.elements if element.kind == "point"),
        key=lambda element: element.x or 0,
    )
    assert crosses.x == crossing_point.x
    assert crosses.y == crossing_point.y

    def plain_text_box(element: Any) -> tuple[float, float, float, float]:
        assert element.x is not None and element.y is not None and element.text is not None
        width = max(
            10.0,
            sum(5.0 if character.isspace() else 16.0 for character in element.text),
        )
        return (element.x, element.y - 15, element.x + width, element.y + 5)

    def overlaps(first: Any, second: Any) -> bool:
        a = plain_text_box(first)
        b = plain_text_box(second)
        return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]

    labelled_point = next(element for element in point_labels if element.text == "(2, 0)")
    assert not overlaps(labelled_point, crosses)

    tick_labels = {
        element.text: element
        for element in diagram.elements
        if element.kind == "text"
        and element.text in {"-4", "-2", "0", "2", "4", "-5", "-0.75", "3.5", "7.75", "12"}
    }
    assert set(tick_labels) == {"-4", "-2", "0", "2", "4", "-5", "-0.75", "3.5", "7.75", "12"}
    assert not overlaps(tick_labels["0"], tick_labels["-0.75"])
