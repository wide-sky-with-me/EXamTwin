import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { subscribeTaskSnapshots } from "../lib/task-events";
import type { PaperJobResult } from "../types";
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
  test("accepts a supported paper through drag and drop", () => {
    render(<PaperAnswering enabled={false} subject={null} />);
    const dropZone = screen.getByText("选择或拖入一份试卷").closest("label");
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
});
