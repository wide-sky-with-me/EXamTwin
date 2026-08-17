from __future__ import annotations

import io
from typing import Any

import numpy as np
import pytest
from examtwin.assessment.answering_agent import (
    AnswerTask,
)
from examtwin.assessment.answering_agent.contracts import (
    AgentRunContext,
    QuestionImage,
    QuestionSpec,
)
from examtwin.assessment.answering_agent.tools import (
    EconomicsCalculateTool,
    EconomicsDiagramTool,
    KnowledgeSearchTool,
    MathCalculateTool,
    MathDiagramTool,
    MathPlotTool,
    ProbabilityCalculateTool,
)
from examtwin.assessment.answering_agent.tools.economics_calculate import (
    EconomicsCalculateInput,
    calculate_economics,
)
from examtwin.contracts import SubpartRequirement
from PIL import Image, ImageDraw

from backend.tests.answering_agent_support import (
    ToolUsingRunner,
    _citation,
    _nodes,
    _runtime,
)


def test_runtime_executes_tools_and_uses_observations_in_final_answer() -> None:
    events = []
    result = _runtime(ToolUsingRunner()).solve(
        AnswerTask(
            subject_code="9660",
            question="Solve x^2 - 5x + 6 = 0 and draw a root diagram.",
            question_spec=QuestionSpec(
                subparts=(
                    SubpartRequirement(
                        answer_kind="math_diagram",
                        required_tool="math_diagram",
                    ),
                )
            ),
        ),
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


def test_economics_calculator_preserves_exam_working_and_rounding() -> None:
    percentage = calculate_economics(
        EconomicsCalculateInput(
            operation="percentage_change",
            values={"old": 111.3, "new": 126.78},
            precision=1,
        )
    )
    concentration = calculate_economics(
        EconomicsCalculateInput(
            operation="concentration_ratio",
            values={"share_1": 23, "share_2": 18, "share_3": 12, "share_4": 8, "firms": 3},
            precision=0,
        )
    )
    mean_growth = calculate_economics(
        EconomicsCalculateInput(
            operation="mean",
            values={"value_1": 5.2, "value_2": 4.8, "value_3": 6.1, "value_4": 3.9},
            precision=2,
        )
    )
    share = calculate_economics(
        EconomicsCalculateInput(
            operation="percentage_of_total",
            values={"part": -18, "total": 240},
            precision=1,
        )
    )
    median = calculate_economics(
        EconomicsCalculateInput(
            operation="median",
            values={"value_1": 4_000, "value_2": 11_000, "value_3": 8_000, "value_4": 2_000},
            precision=0,
        )
    )
    index_value = calculate_economics(
        EconomicsCalculateInput(
            operation="index_value",
            values={"base": 72.5, "current": 74.4},
            precision=2,
        )
    )
    option_1_interest = calculate_economics(
        EconomicsCalculateInput(
            operation="simple_interest",
            values={"principal": 275_000, "rate": 6.7, "years": 3},
            precision=0,
        )
    )
    option_2_interest = calculate_economics(
        EconomicsCalculateInput(
            operation="simple_interest",
            values={"principal": 275_000, "rate": 5.8, "years": 4},
            precision=0,
        )
    )
    interest_difference = calculate_economics(
        EconomicsCalculateInput(
            operation="difference",
            values={
                "minuend": float(option_2_interest["result"]),
                "subtrahend": float(option_1_interest["result"]),
            },
            precision=0,
        )
    )

    assert percentage["result"] == 13.9
    assert "111.3" in str(percentage["working"])
    assert concentration["result"] == 53
    assert mean_growth["result"] == 5.0
    assert share["result"] == -7.5
    assert median["result"] == 6_000
    assert index_value["result"] == 102.62
    assert option_1_interest["result"] == 55_275
    assert option_2_interest["result"] == 63_800
    assert interest_difference["result"] == 8_525


@pytest.mark.asyncio
async def test_economics_diagram_uses_a_stable_domain_template() -> None:
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9640",
            question="With the help of a diagram, explain long-run economic growth.",
        )
    )
    tool = EconomicsDiagramTool().bind(context)

    result = await tool.acall(
        template="ad_as",
        title="Long-run economic growth",
        curve="lras",
        change="increase",
        caption="An outward shift of LRAS increases productive capacity.",
    )

    assert result.is_error is False
    assert len(context.diagrams) == 1
    diagram = context.diagrams[0]
    assert diagram.tool_name == "economics_diagram"
    assert any(element.text == "LRAS2" for element in diagram.elements)
    assert all(element.kind != "polygon" for element in diagram.elements)


@pytest.mark.asyncio
async def test_economics_diagram_can_answer_a_monopsony_labour_question() -> None:
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9640",
            question=(
                "Explain, using a diagram, why the wage rate in a monopsony labour market "
                "is likely to be lower than under perfect competition."
            ),
        )
    )
    tool = EconomicsDiagramTool().bind(context)

    result = await tool.acall(
        template="monopsony_labour",
        title="Wage and employment under labour-market monopsony",
        caption=(
            "The monopsonist employs Qm where MCL = MRP and pays Wm on the labour supply curve."
        ),
    )

    assert result.is_error is False
    labels = {element.text for element in context.diagrams[0].elements if element.text}
    assert {"MCL", "MRP / DL", "ACL / SL", "Wm", "Wc", "Qm", "Qc"} <= labels


@pytest.mark.asyncio
async def test_economics_diagram_matches_perfect_competition_exit_mark_scheme() -> None:
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9640",
            question=(
                "Draw a diagram showing average revenue, average cost and marginal cost for "
                "a firm that would leave a perfectly competitive market in the long run."
            ),
        )
    )
    result = (
        await EconomicsDiagramTool()
        .bind(context)
        .acall(
            template="perfect_competition_exit",
            title="A perfectly competitive firm leaving in the long run",
        )
    )

    assert result.is_error is False
    diagram = context.diagrams[0]
    labels = {element.text for element in diagram.elements if element.text}
    assert {"AR = P", "AC", "MC"} <= labels
    average_revenue = next(
        element
        for element in diagram.elements
        if element.kind == "line" and element.tone == "primary"
    )
    assert average_revenue.y1 == average_revenue.y2 == 305


def test_all_economics_tool_schemas_are_serializable_for_react_prompt() -> None:
    context = AgentRunContext(task=AnswerTask(subject_code="9640", question="Calculate and draw."))
    tools = (
        EconomicsCalculateTool().bind(context),
        EconomicsDiagramTool().bind(context),
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


@pytest.mark.asyncio
async def test_math_plot_supports_inverse_trigonometric_curves() -> None:
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question=r"Sketch y=\frac{1}{2}\sin^{-1}(x+1).",
        )
    )

    result = (
        await MathPlotTool()
        .bind(context)
        .acall(
            title="Sketch of y = 1/2 arcsin(x + 1)",
            answer_anchor="whole",
            x_range=[-2, 0],
            y_range=[-1, 1],
            curves=[
                {
                    "expression": "asin(x + 1) / 2",
                    "domain": [-2, 0],
                    "emphasis": True,
                }
            ],
        )
    )

    assert result.is_error is False
    assert len(context.diagrams) == 1
    assert any(element.kind == "polyline" for element in context.diagrams[0].elements)


@pytest.mark.asyncio
async def test_math_plot_snaps_trapezia_to_trusted_curve_grid() -> None:
    page = Image.new("RGB", (800, 1000), "white")
    draw = ImageDraw.Draw(page)
    verticals = list(range(200, 641, 40))
    horizontals = list(range(200, 721, 40))
    for x in verticals:
        draw.line((x, 200, x, 720), fill=(190, 190, 190), width=2)
    for y in horizontals:
        draw.line((200, y, 640, y), fill=(190, 190, 190), width=2)
    draw.line((200, 200, 200, 720), fill="black", width=2)
    draw.line((200, 720, 680, 720), fill="black", width=2)
    curve = []
    for x in range(200, 641):
        normalized = (x - 200) / 400
        y = 430 + 210 * np.sin(normalized * np.pi) - 70 * normalized
        curve.append((x, round(y)))
    draw.line(curve, fill="black", width=3)
    # The detector only needs trustworthy ink under the two numeric grid labels;
    # it does not perform OCR or infer the mathematical answer from text pixels.
    draw.rectangle((397, 728, 403, 734), fill="black")
    draw.rectangle((597, 728, 603, 734), fill="black")
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=95)

    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="Draw the five trapezia on Figure 4.",
            question_images=(QuestionImage(page_number=15, content=buffer.getvalue()),),
        )
    )
    tool = MathPlotTool().bind(context)
    result = await tool.acall(
        title="Five trapezia",
        x_range=[0, 2],
        y_range=[0, 3],
        show_grid=False,
        segments=[{"points": [[0, 0], [2, 0]]}],
    )

    assert result.is_error is False
    diagram = context.diagrams[0]
    assert diagram.source is not None
    assert diagram.source.page_number == 15
    assert diagram.source.calibration == "existing_curve_grid"
    assert len(diagram.elements) == 11
    assert [round(element.x1 or 0) for element in diagram.elements[:6]] == [
        200,
        280,
        360,
        440,
        520,
        600,
    ]


@pytest.mark.asyncio
async def test_math_plot_calibrates_curve_to_trusted_blank_axes() -> None:
    page = Image.new("RGB", (800, 1000), "white")
    draw = ImageDraw.Draw(page)
    draw.line((180, 600, 680, 600), fill="black", width=3)
    draw.line((680, 600, 668, 594), fill="black", width=2)
    draw.line((680, 600, 668, 606), fill="black", width=2)
    draw.line((400, 250, 400, 800), fill="black", width=3)
    # The printed 360-degree tick ends before the arrow. Calibration must use the
    # regular 180/360 ticks, not the horizontal axis endpoint.
    draw.line((520, 596, 520, 608), fill="black", width=2)
    draw.line((640, 596, 640, 608), fill="black", width=2)
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=95)

    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question=(
                "On **Figure 1** sketch the graph of y=3cos(x-60 degrees) "
                "for 0 <= x <= 360 degrees."
            ),
            question_images=(QuestionImage(page_number=7, content=buffer.getvalue()),),
        )
    )
    tool = MathPlotTool().bind(context)
    result = await tool.acall(
        title="Sketch of y=3cos(x-60°)",
        x_range=[0, 360],
        y_range=[-4, 4],
        show_grid=False,
        curves=[{"expression": "3*cos(pi*(x-60)/180)", "emphasis": True}],
        points=[
            {"x": 0, "y": 1.5, "label": "(0°, 1.5)"},
            {"x": 150, "y": 0, "label": "(150°, 0)"},
            {"x": 330, "y": 0, "label": "(330°, 0)"},
            {"x": 360, "y": 1.5, "label": "(360°, 1.5)"},
        ],
    )

    assert result.is_error is False
    diagram = context.diagrams[0]
    assert diagram.source is not None
    assert diagram.source.page_number == 7
    assert diagram.source.calibration == "blank_axes"
    assert diagram.view_box[0] < 180 < sum((diagram.view_box[0], diagram.view_box[2]))
    points = [element for element in diagram.elements if element.kind == "point"]
    assert points[0].x == pytest.approx(400, abs=1)
    assert points[1].y == pytest.approx(600, abs=1)
    assert points[-1].x == pytest.approx(640, abs=1)

    # Text keeps a fixed browser font size after the mathematical coordinates are
    # mapped onto paper pixels. Its visual centre must therefore be re-anchored to
    # the point instead of scaling the old standalone-canvas offset.
    point_label_pairs = [
        (element, diagram.elements[index + 1])
        for index, element in enumerate(diagram.elements[:-1])
        if element.kind == "point" and diagram.elements[index + 1].kind == "text"
    ]
    assert len(point_label_pairs) == 4
    for point, label in point_label_pairs:
        assert point.x is not None
        assert label.x is not None
        assert label.text is not None
        label_width = max(
            12.0,
            sum(4.5 if character.isspace() else 9.0 for character in label.text),
        )
        assert label.x + label_width / 2 == pytest.approx(point.x, abs=1)


@pytest.mark.asyncio
async def test_math_plot_falls_back_when_blank_axes_cannot_be_calibrated() -> None:
    page = Image.new("RGB", (800, 1000), "white")
    buffer = io.BytesIO()
    page.save(buffer, format="JPEG", quality=95)
    context = AgentRunContext(
        task=AnswerTask(
            subject_code="9660",
            question="On Figure 1 sketch the graph of y=x^2.",
            question_images=(QuestionImage(page_number=7, content=buffer.getvalue()),),
        )
    )

    result = (
        await MathPlotTool()
        .bind(context)
        .acall(
            title="Sketch of y=x²",
            x_range=[-2, 2],
            y_range=[-1, 4],
            show_grid=False,
            curves=[{"expression": "x^2", "emphasis": True}],
        )
    )

    assert result.is_error is False
    assert "standalone vector plot" in str(result)
    assert context.diagrams[0].source is None
    assert "独立精确矢量图" in context.diagrams[0].caption
