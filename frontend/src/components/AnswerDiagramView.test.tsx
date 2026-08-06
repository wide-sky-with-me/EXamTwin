import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import type { AnswerDiagram, DiagramElement } from "../types";
import { AnswerDiagramView } from "./AnswerDiagramView";

function element(overrides: Partial<DiagramElement>): DiagramElement {
  return {
    kind: "line",
    x1: null,
    y1: null,
    x2: null,
    y2: null,
    x: null,
    y: null,
    cx: null,
    cy: null,
    r: null,
    rx: null,
    ry: null,
    d: null,
    text: null,
    points: [],
    dashed: false,
    emphasis: false,
    arrow_start: false,
    arrow_end: false,
    fill: "none",
    tone: "default",
    ...overrides,
  };
}

const diagram: AnswerDiagram = {
  title: "Two quadratic curves",
  caption: "The labelled curves meet at the origin.",
  tool_name: "math_plot",
  view_box: [0, 0, 600, 360],
  source: null,
  legend: [
    { label: "\\(y=x^2\\)", tone: "primary" },
    { label: "$y=2x$", tone: "secondary" },
  ],
  elements: [
    element({
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
    }),
    element({
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
    }),
    element({
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
    }),
  ],
};

describe("AnswerDiagramView", () => {
  test("renders provenance, semantic legend, math labels and accessible SVG text", () => {
    const { container } = render(<AnswerDiagramView diagram={diagram} />);

    expect(
      (container.querySelector(".answer-diagram") as HTMLElement).style.getPropertyValue(
        "--diagram-inline-size",
      ),
    ).toBe("720px");
    expect(screen.getByText("函数与坐标绘图 · 安全矢量图")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Two quadratic curves/ })).toBeInTheDocument();
    expect(screen.getByLabelText("图例")).toBeInTheDocument();
    expect(container.querySelector("svg title")?.textContent).toBe(diagram.title);
    expect(container.querySelector("svg desc")?.textContent).toBe(diagram.caption);
    expect(container.querySelector("foreignObject .katex")).toBeInTheDocument();
    expect(container.querySelector(".answer-diagram-legend .katex")).toBeInTheDocument();
    expect(container.querySelector("polyline.tone-primary")).toBeInTheDocument();
  });

  test("supports bounded zoom below the default, fullscreen and Escape recovery", async () => {
    const user = userEvent.setup();
    const { container } = render(<AnswerDiagramView diagram={diagram} />);
    const stage = container.querySelector(".answer-diagram-stage") as HTMLElement;
    const viewport = container.querySelector(".answer-diagram-viewport") as HTMLElement;
    const canvas = container.querySelector(".answer-diagram-canvas") as HTMLElement;
    const toolbar = container.querySelector(".answer-diagram-toolbar") as HTMLElement;

    expect(stage).toContainElement(viewport);
    expect(stage).toContainElement(toolbar);
    expect(viewport.nextElementSibling).toBe(toolbar);
    await user.click(screen.getByRole("button", { name: "缩小图形" }));
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(canvas.style.inlineSize).toBe("75%");

    await user.click(screen.getByRole("button", { name: "重置图形缩放" }));
    await user.click(screen.getByRole("button", { name: "放大图形" }));
    expect(screen.getByText("125%")).toBeInTheDocument();
    expect(canvas.style.inlineSize).toBe("125%");
    await user.click(screen.getByRole("button", { name: "全屏查看图形" }));
    expect(container.querySelector(".answer-diagram")).toHaveClass("is-expanded");
    expect(screen.getByRole("dialog", { name: diagram.title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "退出全屏查看" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");

    (container.querySelector(".answer-diagram-viewport") as HTMLElement).focus();
    await user.tab();
    expect(screen.getByRole("button", { name: "缩小图形" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(container.querySelector(".answer-diagram")).not.toHaveClass("is-expanded");
    expect(screen.getByRole("button", { name: "全屏查看图形" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  test("renders trusted paper pixels beneath a calibrated vector overlay", () => {
    const sourceDiagram: AnswerDiagram = {
      ...diagram,
      view_box: [180, 340, 660, 560],
      elements: [
        ...diagram.elements,
        element({ kind: "point", x: 698, y: 692, tone: "secondary" }),
        element({ kind: "text", x: 577, y: 674, text: "(330°, 0)", tone: "secondary" }),
      ],
      source: {
        kind: "paper_page",
        page_number: 7,
        width: 1072,
        height: 1516,
        calibration: "blank_axes",
      },
    };
    const { container } = render(
      <AnswerDiagramView diagram={sourceDiagram} jobId="paper-job-1" />,
    );
    expect(
      (container.querySelector(".answer-diagram") as HTMLElement).style.getPropertyValue(
        "--diagram-inline-size",
      ),
    ).toBe("613px");

    expect(screen.getByText("原图校准矢量叠绘 · 原卷第 7 页")).toBeInTheDocument();
    const source = container.querySelector("image.paper-diagram-source");
    expect(source).toHaveAttribute(
      "href",
      "/api/v1/papers/jobs/paper-job-1/source/pages/7",
    );
    expect(source?.nextElementSibling?.tagName.toLowerCase()).toBe("line");
    const repairedLabel = [...container.querySelectorAll("text")].find(
      (node) => node.textContent === "(330°, 0)",
    );
    expect(Number(repairedLabel?.getAttribute("x"))).toBeCloseTo(659.75, 1);
  });
});
