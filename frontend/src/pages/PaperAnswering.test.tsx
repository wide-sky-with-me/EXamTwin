import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { subscribeTaskSnapshots } from "../lib/task-events";
import type { PaperJobResult, SubjectPack } from "../types";
import { PaperAnswering } from "./PaperAnswering";

vi.mock("../lib/task-events", () => ({
  subscribeTaskSnapshots: vi.fn(),
}));

const subscribeMock = vi.mocked(subscribeTaskSnapshots);

beforeEach(() => {
  window.localStorage.clear();
  subscribeMock.mockReset();
});

describe("PaperAnswering", () => {
  test("accepts a supported paper through drag and drop", async () => {
    const subject = {
      id: "math",
      subject_code: "9660",
      title: "Mathematics",
      board_name: "OxfordAQA",
      answering_enabled: true,
      version: "1",
      digest: "digest",
      capability_profile_id: "math",
      generic_qa_enabled: true,
      answering_disabled_reason: null,
      active_graph_version_id: null,
      units: [],
      knowledge_bases: [],
    } as SubjectPack;
    render(<PaperAnswering enabled subjects={[subject]} />);
    fireEvent.click(screen.getByRole("button", { name: "新建作答" }));
    fireEvent.click(screen.getByRole("button", { name: /Mathematics/ }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    const dropZone = screen.getByText(/选择或拖入一份.*试卷/).closest("label");
    const paper = new File(["# Question 1"], "paper.md", { type: "text/markdown" });

    fireEvent.drop(dropZone!, { dataTransfer: { files: [paper] } });

    expect(screen.getByText("paper.md")).toBeInTheDocument();
  });

  test("presents completion as answer status instead of evidence status", async () => {
    const imageUrl = (
      "/api/v1/papers/jobs/job-1/question-images/"
      + `p0001-${"a".repeat(64)}.png`
    );
    const completedJob: PaperJobResult = {
      job_id: "job-1",
      filename: "paper.pdf",
      subject_pack_id: "oxfordaqa-mathematics-9660",
      subject_code: "9660",
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "completed",
      stage: "completed",
      total_pages: 1,
      parsed_pages: 1,
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      chunks: [],
      source_integrity_status: "verified",
      split_contract_version: "paper-question-split-v6",
      split_source_digest: "source-digest",
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      questions: [{
        position: 0,
        number: "1",
        question_markdown: `Solve x + 1 = 2.\n\n![Equation diagram](${imageUrl})`,
        answer_markdown: "x = 1",
        diagrams: [],
        images: [],
        citations: [],
        knowledge_points: [],
        confidence: 0.9,
        grounded: true,
        warnings: [],
        attempts: 1,
        source_pages: [1],
        source_warnings: [],
        source_kind: "primary",
        source_digest: "source-digest",
        requires_visual_context: false,
        answer_requirements: [],
        agent_steps: [],
        status: "completed",
        total_marks: 1,
        error: null,
      }],
      error: null,
    };
    subscribeMock.mockImplementation((options) => {
      options.onSnapshot(completedJob);
      options.onState("live");
      return () => undefined;
    });
    window.localStorage.setItem("examtwin.paperJobId.unselected", completedJob.job_id);

    render(<PaperAnswering enabled subject={null} />);

    expect(await screen.findByText("已作答")).toBeInTheDocument();
    expect(screen.getByText("Q1 · 已作答")).toBeInTheDocument();
    expect(screen.queryByText("证据充分")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Equation diagram" })).toHaveAttribute(
      "src",
      imageUrl,
    );
  });

  test("presents a recoverable parsing failure without an indefinite waiting workspace", async () => {
    const failedJob: PaperJobResult = {
      job_id: "job-failed",
      filename: "paper.pdf",
      subject_pack_id: "oxfordaqa-mathematics-9660",
      subject_code: "9660",
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "failed",
      stage: "parsing",
      total_pages: 32,
      parsed_pages: 10,
      total_questions: 0,
      completed_questions: 0,
      failed_questions: 0,
      created_at: "2026-08-11T01:44:16Z",
      updated_at: "2026-08-11T01:45:45Z",
      chunks: [{
        chunk_index: 2,
        page_start: 11,
        page_end: 15,
        status: "failed",
        attempts: 1,
        error: "ValueError: MinerU 题目图片缺少物理页位置",
      }],
      source_integrity_status: "verified",
      split_contract_version: null,
      split_source_digest: null,
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      questions: [],
      error: "ValueError: MinerU 题目图片缺少物理页位置",
    };
    subscribeMock.mockImplementation((options) => {
      options.onSnapshot(failedJob);
      options.onState("idle");
      return () => undefined;
    });
    window.localStorage.setItem("examtwin.paperJobId.unselected", failedJob.job_id);

    render(<PaperAnswering enabled subject={null} />);

    expect(await screen.findByText("解析中断 · 已完成 10 / 32 页")).toBeInTheDocument();
    expect(screen.getByText("任务在题目识别前中断")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "从失败步骤继续" })).toBeInTheDocument();
    expect(screen.queryByText("等待题目识别结果")).not.toBeInTheDocument();
  });
});
