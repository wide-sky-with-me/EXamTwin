import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import type { AnswerDiagram } from "../types";
import { AnswerDiagramView } from "./AnswerDiagramView";

const diagram: AnswerDiagram = {
  title: "Two quadratic curves",
  caption: "The labelled curves meet at the origin.",
  tool_name: "math_plot",
  view_box: [0, 0, 600, 360],
  legend: [
    { label: "\\(y=x^2\\)", tone: "primary" },
    { label: "$y=2x$", tone: "secondary" },
  ],
  elements: [
    {
      kind: "line",
      x1: 40,
      y1: 300,
      x2: 570,
      y2: 300,
      points: [],
      dashed: false,
      emphasis: true,
      arrow_start: false,
      arrow_end: true,
      fill: "none",
      tone: "default",
    },
    {
      kind: "polyline",
      points: [
        [80, 270],
        [180, 220],
        [300, 100],
      ],
      dashed: false,
      emphasis: true,
      arrow_start: false,
      arrow_end: false,
      fill: "none",
      tone: "primary",
    },
    {
      kind: "text",
      x: 320,
      y: 90,
      text: "\\(y=x^2\\)",
      points: [],
      dashed: false,
      emphasis: false,
      arrow_start: false,
      arrow_end: false,
      fill: "none",
      tone: "primary",
    },
  ],
};

describe("AnswerDiagramView", () => {
  test("renders provenance, semantic legend, math labels and accessible SVG text", () => {
    const { container } = render(<AnswerDiagramView diagram={diagram} />);

    expect(screen.getByText("函数与坐标绘图 · 安全矢量图")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Two quadratic curves/ })).toBeInTheDocument();
    expect(screen.getByLabelText("图例")).toBeInTheDocument();
    expect(container.querySelector("svg title")?.textContent).toBe(diagram.title);
    expect(container.querySelector("svg desc")?.textContent).toBe(diagram.caption);
    expect(container.querySelector("foreignObject .katex")).toBeInTheDocument();
    expect(container.querySelector(".answer-diagram-legend .katex")).toBeInTheDocument();
    expect(container.querySelector("polyline.tone-primary")).toBeInTheDocument();
  });

  test("supports bounded zoom, fullscreen and Escape recovery", async () => {
    const user = userEvent.setup();
    const { container } = render(<AnswerDiagramView diagram={diagram} />);

    await user.click(screen.getByRole("button", { name: "放大图形" }));
    expect(screen.getByText("125%")).toBeInTheDocument();
    expect(
      (container.querySelector(".answer-diagram-canvas") as HTMLElement).style.width,
    ).toBe("125%");

    await user.click(screen.getByRole("button", { name: "全屏查看图形" }));
    expect(container.querySelector(".answer-diagram")).toHaveClass("is-expanded");
    expect(document.body.style.overflow).toBe("hidden");

    fireEvent.keyDown(window, { key: "Escape" });
    expect(container.querySelector(".answer-diagram")).not.toHaveClass("is-expanded");
    expect(document.body.style.overflow).toBe("");
  });
});
