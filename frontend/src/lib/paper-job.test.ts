import { describe, expect, test } from "vitest";
import type { PaperJobQuestion, PaperJobResult } from "../types";
import { canRetryQuestion, paperProgress } from "./paper-job";

function job(overrides: Partial<PaperJobResult>): PaperJobResult {
  return {
    job_id: "job-1",
    filename: "paper.pdf",
    subject_pack_id: "oxfordaqa-mathematics-9660",
    subject_code: "9660",
    unit_code: "P2",
    status: "answering",
    stage: "answering",
    total_pages: 10,
    parsed_pages: 10,
    total_questions: 10,
    completed_questions: 0,
    failed_questions: 0,
    created_at: "2026-08-03T00:00:00Z",
    updated_at: "2026-08-03T00:00:00Z",
    chunks: [],
    questions: [],
    error: null,
    ...overrides,
  };
}

function question(overrides: Partial<PaperJobQuestion> = {}): PaperJobQuestion {
  return {
    position: 1,
    number: "1",
    question_markdown: "Draw the curve.",
    answer_markdown: "",
    diagrams: [],
    images: [],
    citations: [],
    knowledge_points: [],
    confidence: 0,
    grounded: false,
    warnings: [],
    attempts: 1,
    source_pages: [1],
    source_warnings: [],
    answer_requirements: [],
    agent_steps: [],
    status: "completed",
    total_marks: null,
    error: null,
    ...overrides,
  };
}

describe("paper job presentation", () => {
  test("shows visual review as a distinct progress phase", () => {
    expect(paperProgress(job({
      status: "vision_review",
      stage: "vision_review",
    }))).toBe(52);
  });

  test("does not present a partially failed paper as 100 percent complete", () => {
    expect(paperProgress(job({
      status: "partial_failed",
      stage: "completed",
      completed_questions: 9,
      failed_questions: 1,
    }))).toBe(96);
    expect(paperProgress(job({ status: "completed", stage: "completed" }))).toBe(100);
  });

  test("offers targeted retry only for failed or missing required artifacts", () => {
    expect(canRetryQuestion(question({ status: "failed" }))).toBe(true);
    expect(canRetryQuestion(question({
      answer_requirements: [{
        label: "graph",
        marks: null,
        answer_kind: "math_plot",
        accuracy: null,
        units: [],
        required_tool: "math_plot",
      }],
    }))).toBe(true);
    expect(canRetryQuestion(question())).toBe(false);
  });
});
