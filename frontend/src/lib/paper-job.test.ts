import { describe, expect, test } from "vitest";
import type { PaperJobQuestion, PaperJobResult } from "../types";
import {
  canRetryQuestion,
  PAPER_JOB_STAGE_LABELS,
  PAPER_JOB_STATUS_LABELS,
  paperProgress,
  paperQuestionStatusLabel,
} from "./paper-job";

function job(overrides: Partial<PaperJobResult>): PaperJobResult {
  return {
    job_id: "job-1",
    filename: "paper.pdf",
    display_name: null,
    answer_mode: "generated",
    pair_key: null,
    paper_unit_id: null,
    question_paper_document_id: null,
    source_booklet_document_id: null,
    source_booklet_checksum: null,
    source_booklet_filename: null,
    subject_pack_id: "oxfordaqa-mathematics-9660",
    subject_code: "9660",
    unit_code: "P2",
    knowledge_base_version_ids: [],
    graph_version_id: null,
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
    source_integrity_status: "verified",
    split_contract_version: "paper-question-split-v6",
    split_source_digest: "source-digest",
    replacement_for_job_id: null,
    replaced_by_job_id: null,
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
    source_kind: "primary",
    source_digest: "source-digest",
    answer_requirements: [],
    agent_steps: [],
    status: "completed",
    total_marks: null,
    error: null,
    ...overrides,
    requires_visual_context: overrides.requires_visual_context ?? false,
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

  test("uses concise job and stage labels that describe processing state", () => {
    expect(PAPER_JOB_STATUS_LABELS.completed).toBe("处理完成");
    expect(PAPER_JOB_STATUS_LABELS.partial_failed).toBe("部分题目失败");
    expect(PAPER_JOB_STATUS_LABELS.failed).toBe("处理失败");
    expect(PAPER_JOB_STAGE_LABELS.queued).toBe("等待处理");
    expect(PAPER_JOB_STAGE_LABELS.vision_review).toBe("核对题面");
  });

  test("distinguishes answer status from evidence sufficiency", () => {
    expect(paperQuestionStatusLabel(question({ grounded: true }))).toBe("已作答");
    expect(paperQuestionStatusLabel(question({ grounded: false }))).toBe("证据不足");
    expect(paperQuestionStatusLabel(question({ status: "pending", attempts: 0 })))
      .toBe("等待作答");
    expect(paperQuestionStatusLabel(question({ status: "pending", attempts: 2 })))
      .toBe("等待重试 · 已尝试 2 次");
    expect(paperQuestionStatusLabel(question({ status: "answering" }))).toBe("作答中");
    expect(paperQuestionStatusLabel(question({ status: "failed", attempts: 3 })))
      .toBe("作答失败 · 已尝试 3 次");
  });

  test("offers targeted retry only for failed or missing required artifacts", () => {
    expect(canRetryQuestion(question({ status: "failed" }))).toBe(true);
    expect(canRetryQuestion(question({
      answer_requirements: [{
        label: "graph",
        marks: null,
        answer_kind: "diagram",
        accuracy: null,
        units: [],
        required_tool: "math_plot",
      }],
    }))).toBe(true);
    expect(canRetryQuestion(question())).toBe(false);
  });
});
