from __future__ import annotations

from typing import Any

from llama_index.core.tools import BaseTool, FunctionTool
from pydantic import BaseModel, Field

from examtwin.answering_agent.contracts import AgentRunContext
from examtwin.schemas.evidence import AnswerDiagram, DiagramElement, DiagramLegendItem


class MathDiagramInput(BaseModel):
    """Strict scene contract exposed to the model and revalidated by the runtime."""

    title: str = Field(
        min_length=1,
        max_length=160,
        description="Short reader-facing title for the completed diagram.",
    )
    elements: list[DiagramElement] = Field(
        min_length=1,
        max_length=160,
        description=(
            "Complete safe vector scene. Each item must use a supported `kind` and its "
            "required numeric geometry: line(x1,y1,x2,y2), point(x,y), "
            "text(x,y,text), circle(cx,cy,r), ellipse(cx,cy,rx,ry), "
            "polyline/polygon(points=[[x,y],...]), or path(d with SVG path commands only)."
        ),
    )
    caption: str = Field(
        default="",
        max_length=500,
        description="Optional explanation of what the drawing demonstrates.",
    )
    view_box: tuple[float, float, float, float] = Field(
        default=(0, 0, 600, 360),
        description=(
            "[min_x, min_y, width, height] for the SVG canvas; width and height must be positive."
        ),
    )
    legend: list[DiagramLegendItem] = Field(
        default_factory=list,
        max_length=12,
        description=(
            "Optional semantic legend. Reuse the same tone on matching elements. "
            "Prefer labels in the figure itself for simple geometry."
        ),
    )


class MathDiagramTool:
    name = "math_diagram"

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def create_math_diagram(
            title: str,
            elements: list[dict[str, Any]],
            caption: str = "",
            view_box: list[float] | None = None,
            legend: list[dict[str, Any]] | None = None,
        ) -> str:
            """Create a safe vector diagram for a construction, locus or geometry answer.

            Elements must use only line, polyline, polygon, circle, ellipse, path, point,
            or text with numeric geometry. Never return SVG, HTML, JavaScript or base64.
            """
            diagram = AnswerDiagram.model_validate(
                {
                    "title": title,
                    "caption": caption,
                    "tool_name": self.name,
                    "view_box": view_box or [0, 0, 600, 360],
                    "elements": elements,
                    "legend": legend or [],
                }
            )
            context.add_diagram(diagram)
            return (
                f"Diagram '{diagram.title}' accepted with "
                f"{len(diagram.elements)} validated elements."
            )

        return FunctionTool.from_defaults(
            async_fn=create_math_diagram,
            name=self.name,
            fn_schema=MathDiagramInput,
            description=(
                "Create and attach a validated vector diagram when the complete answer "
                "requires a construction, geometry figure, number line, locus, vector, "
                "force diagram, or non-coordinate shaded region. Pass the complete drawing "
                "in one call. Never use this tool for a function graph, statistical plot, "
                "or anything on mathematical coordinate axes; use math_plot for those. "
                "Use `kind`, never `type`; use [[x,y], ...] pairs for polyline/polygon. "
                "Do not call this tool unless the exam question explicitly asks the candidate "
                "to draw, "
                "sketch, plot, shade, construct, or complete a figure."
            ),
        )
