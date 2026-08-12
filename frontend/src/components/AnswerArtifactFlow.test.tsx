import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { AnswerDiagram, AnswerImage } from "../types";
import { AnswerArtifactFlow } from "./AnswerArtifactFlow";

function diagram(
  id: string | null,
  anchor: string | null,
  order: number | null,
  title: string,
): AnswerDiagram {
  return {
    artifact_id: id,
    answer_anchor: anchor,
    answer_order: order,
    caption: "",
    elements: [{
      arrow_end: false,
      arrow_start: false,
      cx: null,
      cy: null,
      d: null,
      dashed: false,
      emphasis: false,
      fill: "none",
      kind: "point",
      points: [],
      r: null,
      rx: null,
      ry: null,
      text: null,
      tone: "default",
      x: 1,
      x1: null,
      x2: null,
      y: 1,
      y1: null,
      y2: null,
    }],
    legend: [],
    source: null,
    title,
    tool_name: "math_plot",
    view_box: [0, 0, 600, 360],
  };
}

function image(
  id: string | null,
  anchor: string | null,
  order: number | null,
  title: string,
): AnswerImage {
  return {
    artifact_id: id,
    answer_anchor: anchor,
    answer_order: order,
    caption: "",
    content_url: "/api/v1/answer-assets/0123456789abcdef0123456789abcdef.png",
    generated: true,
    height: 64,
    media_type: "image/png",
    title,
    tool_name: "image_generate",
    width: 64,
  };
}

function renderFlow({
  answerMarkdown,
  diagrams = [],
  images = [],
}: {
  answerMarkdown: string;
  diagrams?: AnswerDiagram[];
  images?: AnswerImage[];
}) {
  return render(
    <AnswerArtifactFlow
      answerMarkdown={answerMarkdown}
      diagrams={diagrams}
      images={images}
      renderMarkdown={(markdown, key) => <article key={key}>{markdown}</article>}
    />,
  );
}

describe("AnswerArtifactFlow", () => {
  test("places multiple cross-type artifacts after their exact subpart in production order", () => {
    const { container } = renderFlow({
      answerMarkdown: "### (a)\n\nPart A answer.\n\n### (b)\n\nPart B answer.",
      diagrams: [
        diagram("artifact-2", "(a)", 2, "A diagram"),
        diagram("artifact-3", "(b)", 3, "B diagram"),
      ],
      images: [image("artifact-1", "(a)", 1, "A image")],
    });

    const text = container.textContent ?? "";
    expect(text.indexOf("Part A answer.")).toBeLessThan(text.indexOf("A image"));
    expect(text.indexOf("A image")).toBeLessThan(text.indexOf("A diagram"));
    expect(text.indexOf("A diagram")).toBeLessThan(text.indexOf("Part B answer."));
    expect(text.indexOf("Part B answer.")).toBeLessThan(text.indexOf("B diagram"));
  });

  test("falls back after the answer for legacy or invalid anchors and suppresses duplicate ids", () => {
    const duplicate = diagram("artifact-1", "missing", 2, "Duplicate diagram");
    const { container } = renderFlow({
      answerMarkdown: "### (a)\n\nFirst answer.\n\n### (a)\n\nRepeated label.",
      diagrams: [
        diagram("artifact-1", "(a)", 1, "Ambiguous diagram"),
        duplicate,
        diagram(null, null, null, "Legacy diagram"),
      ],
    });

    const text = container.textContent ?? "";
    expect(text.indexOf("Repeated label.")).toBeLessThan(text.indexOf("Ambiguous diagram"));
    expect(text.indexOf("Ambiguous diagram")).toBeLessThan(text.indexOf("Legacy diagram"));
    expect(text).not.toContain("Duplicate diagram");
  });
});
