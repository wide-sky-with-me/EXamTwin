import { describe, expect, it } from "vitest";
import { PDFDocument, degrees } from "pdf-lib";
import { answerSections, pdfImagePosition, validateRegions, type AnswerPdfLayout } from "./answer-pdf";
import type { PaperJobResult } from "../types";

const job = {
  questions: [{ position: 0, number: "1", status: "completed", error: null, source_pages: [1],
    answer_markdown: "Introduction\n\n### (a)\nFirst $x^2$.\n\n### (b)\nLast answer.\n",
    answer_requirements: [{ label: "(a)" }, { label: "(b)" }],
    diagrams: [{ answer_anchor: "(b)", title: "Graph" }], images: [],
  }, { position: 1, number: "2", status: "failed", answer_markdown: "", diagrams: [], images: [] }],
} as unknown as PaperJobResult;

describe("original-paper answer PDF", () => {
  it("preserves the complete answer and its subpart artifact, excluding failed answers", () => {
    const sections = answerSections(job);
    expect(sections).toHaveLength(2);
    expect(sections.map((s) => s.markdown).join("")).toBe(job.questions[0].answer_markdown);
    expect(sections[0].diagrams).toHaveLength(0);
    expect(sections[1].diagrams[0].title).toBe("Graph");
  });

  it("requires explicit placement and refuses overlap and wrong source pages", () => {
    const sections = answerSections(job);
    const layout = { pages: [{ page_number: 1, width: 600, height: 800 }], regions: [], warnings: [] } as unknown as AnswerPdfLayout;
    expect(() => validateRegions(sections, {}, layout)).toThrow("框选");
    const first = { question_position: 0, answer_anchor: "(a)", page_number: 1, x: 80, y: 100, width: 400, height: 100 };
    expect(() => validateRegions(sections, { "0:0": first, "0:1": { ...first, y: 150 } }, layout)).toThrow("重叠");
    expect(() => validateRegions(sections, { "0:0": first, "0:1": { ...first, page_number: 2 } }, layout)).toThrow("原卷页");
    expect(() => validateRegions(sections, { "0:0": first, "0:1": { ...first, y: 300 } }, layout)).not.toThrow();
  });

  it.each([
    [0, 60, 650], [90, 180, 70], [180, 560, 190], [270, 440, 770],
  ])("maps rotation %s and nonzero CropBox correctly", async (angle, x, y) => {
    const pdf = await PDFDocument.create();
    const page = pdf.addPage([640, 880]);
    page.setCropBox(10, 20, 600, 800);
    page.setRotation(degrees(angle));
    const result = pdfImagePosition(page, { page: 1, x: 50, y: 100, width: 80, height: 70 });
    expect(result).toMatchObject({ x, y, width: 80, height: 70 });
  });
});
