import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DifficultyEvidenceWorkspace } from "./DifficultyEvidenceWorkspace";
import type { DifficultyRunDetail } from "../lib/api";

const api = vi.hoisted(() => ({
  createRun: vi.fn(),
  getRun: vi.fn(),
  listRuns: vi.fn(),
  publish: vi.fn(),
  review: vi.fn(),
}));

vi.mock("../lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/api")>();
  return {
    ...original,
    createDifficultyEvidenceRun: api.createRun,
    getDifficultyEvidenceRun: api.getRun,
    listDifficultyEvidenceRuns: api.listRuns,
    publishDifficultyEvidenceRun: api.publish,
    reviewDifficultyEvidenceCandidate: api.review,
  };
});

const run: DifficultyRunDetail = {
  id: "run-1",
  subject_id: "subject-a",
  subject_code: "SYNTH",
  source_document_id: "report-1",
  source_checksum: "report-sha",
  question_paper_document_id: "qp-1",
  question_paper_checksum: "qp-sha",
  question_catalog_hash: "catalog-sha",
  package_digest: "package-sha",
  prompt_digest: "prompt-sha",
  pair_key: "SYNTH:2026:JUN:U1",
  input_hash: "input-1",
  extractor_version: "extractor-v1",
  model_name: "model-a",
  status: "review_ready",
  candidate_count: 2,
  error: null,
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
  completed_at: "2026-08-20T00:00:00Z",
  published_at: null,
  run_fingerprint: "r".repeat(64),
  candidates: [
    {
      id: "candidate-a",
      run_id: "run-1",
      candidate_fingerprint: "a".repeat(64),
      question_number: "1",
      page_number: 2,
      evidence_level: "A",
      evidence_type: "quantitative",
      metric_name: "facility",
      metric_text: "80%",
      metric_value: 80,
      metric_scale: "percent",
      metric_direction: "success",
      metric_comparator: "eq",
      difficulty_score: 0.2,
      quote: "80% answered this question correctly.",
      quote_hash: "quote-hash-a",
      block_hash: "block-hash-a",
      source_ref: "document:report-1:page:2",
      validation_status: "valid",
      validation_errors: [],
      review_decision: null,
      review_replacement: {},
    },
    {
      id: "candidate-b",
      run_id: "run-1",
      candidate_fingerprint: "b".repeat(64),
      question_number: "2",
      page_number: 3,
      evidence_level: "B",
      evidence_type: "qualitative",
      metric_name: null,
      metric_text: null,
      metric_value: null,
      metric_scale: null,
      metric_direction: null,
      metric_comparator: null,
      difficulty_score: null,
      quote: "Students found this question challenging.",
      quote_hash: "quote-hash-b",
      block_hash: "block-hash-b",
      source_ref: "document:report-1:page:3",
      validation_status: "valid",
      validation_errors: [],
      review_decision: null,
      review_replacement: {},
    },
  ],
};

describe("DifficultyEvidenceWorkspace", () => {
  beforeEach(() => {
    api.createRun.mockReset().mockResolvedValue(run);
    api.getRun.mockReset().mockResolvedValue(run);
    api.listRuns.mockReset().mockResolvedValue([run]);
    api.publish.mockReset().mockResolvedValue(run);
    api.review.mockReset().mockResolvedValue(run);
  });

  it("shows exact A evidence and keeps B evidence explicitly non-numeric", async () => {
    render(<DifficultyEvidenceWorkspace subjectId="subject-a" />);

    expect(await screen.findByText("80% answered this question correctly.")).toBeInTheDocument();
    expect(screen.getByText("Students found this question challenging.")).toBeInTheDocument();
    expect(screen.getByText("定性证据：不生成数值难度分数")).toBeInTheDocument();
    expect(screen.getByText(/难度投影 0.200/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发布已接受证据" })).toBeDisabled();
  });

  it("submits the candidate fingerprint without a spoofable reviewer", async () => {
    const user = userEvent.setup();
    render(<DifficultyEvidenceWorkspace subjectId="subject-a" />);
    await screen.findByText("Students found this question challenging.");

    const accept = screen.getAllByRole("button", { name: "接受" })[0];
    await waitFor(() => expect(accept).toBeEnabled());
    await user.click(accept);

    await waitFor(() => expect(api.review).toHaveBeenCalledWith(
      "subject-a",
      "run-1",
      "candidate-a",
      expect.objectContaining({
        decision: "accepted",
        expected_candidate_fingerprint: "a".repeat(64),
      }),
    ));
  });
});
