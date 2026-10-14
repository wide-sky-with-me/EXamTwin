import { describe, expect, test } from "vitest";

import type { ReviewItem } from "../types";
import { groupPendingReviews, reviewItemLabel } from "./review-groups";

function review(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "review-1",
    subject_code: "subject-a",
    subject_id: "subject-a",
    paper_job_id: "job-1",
    paper_unit_id: "unit-1",
    paper_display_name: "试卷1",
    paper_filename: "paper.pdf",
    question_position: 0,
    answer_mode: "uploaded",
    question_ref: "Q1",
    total_awarded: 1,
    total_available: 2,
    confidence: 0.72,
    status: "pending_review",
    created_at: "2026-08-03T00:00:00Z",
    result: {
      assessment_id: "review-1",
      subject_code: "subject-a",
      question_ref: "Q1",
      total_awarded: 1,
      total_available: 2,
      confidence: 0.72,
      status: "pending_review",
      rubric_awards: [],
      symbolic_checks: [],
      citations: [],
      warnings: [],
      improvement_suggestions: [],
      manual_review_required: true,
    },
    ...overrides,
  };
}

describe("review item labels", () => {
  test.each([
    { question_ref: " Q2 ", question_position: 4, expected: "Q2" },
    { question_ref: " \t ", question_position: 0, expected: "Q1" },
    { question_ref: null, question_position: 9, expected: "Q10" },
    { question_ref: null, question_position: null, expected: "abcdefgh" },
  ])("derives $expected from the reference, position, or short ID", ({ expected, ...overrides }) => {
    expect(reviewItemLabel(review({ id: "abcdefgh-extra", ...overrides }))).toBe(expected);
  });
});

describe("pending review groups", () => {
  test("uses only the paper job ID even when subjects differ", () => {
    const first = review({ id: "review-1", question_position: 1, question_ref: "Q2" });
    const second = review({ id: "review-2", subject_id: "subject-b", subject_code: "subject-b" });

    const groups = groupPendingReviews([first, second]);

    expect(groups).toEqual([{
      key: "paper:job-1",
      kind: "paper",
      label: "试卷1",
      paperFilename: "paper.pdf",
      paperJobId: "job-1",
      items: [second, first],
    }]);
  });

  test("isolates every null or empty job ID and places standalone items after paper groups", () => {
    const first = review({ id: "review-2", paper_job_id: null });
    const second = review({ id: "review-10", paper_job_id: "" });
    const linked = review({ id: "review-linked", question_position: 9 });

    const groups = groupPendingReviews([second, first, linked]);

    expect(groups.map((group) => group.key)).toEqual([
      "paper:job-1", "legacy:review-2", "legacy:review-10",
    ]);
    expect(groups.slice(1)).toEqual([first, second].map((item) => ({
      key: `legacy:${item.id}`,
      kind: "standalone",
      label: "独立评估 · Q1",
      paperFilename: null,
      paperJobId: null,
      items: [item],
    })));
  });

  test("orders paper groups by natural job ID rather than arrival or display name", () => {
    const laterId = review({ paper_job_id: "job-10", paper_display_name: "试卷1" });
    const earlierId = review({ paper_job_id: "job-2", paper_display_name: "试卷10" });

    expect(groupPendingReviews([laterId, earlierId]).map((group) => group.paperJobId))
      .toEqual(["job-2", "job-10"]);
  });

  test("orders known positions before missing positions and before question labels", () => {
    const items = [
      review({ id: "missing", question_position: null, question_ref: "Q0" }),
      review({ id: "second", question_position: 1, question_ref: "Q1" }),
      review({ id: "first", question_position: 0, question_ref: "Q10" }),
    ];

    expect(groupPendingReviews(items)[0].items.map((item) => item.id))
      .toEqual(["first", "second", "missing"]);
  });

  test("uses Chinese natural question order for both linked and standalone items", () => {
    const items = ["第10题", "第2题", "第1题"].map((question_ref, index) => review({
      id: `review-${index}`,
      question_ref,
      question_position: null,
    }));
    const expected = ["第1题", "第2题", "第10题"];

    expect(groupPendingReviews(items)[0].items.map(reviewItemLabel)).toEqual(expected);
    expect(groupPendingReviews(items.map((item) => ({ ...item, paper_job_id: null })))
      .map((group) => reviewItemLabel(group.items[0]))).toEqual(expected);
  });

  test("breaks equal positions and case-insensitive labels by created time, then natural ID", () => {
    const items = [
      review({ id: "review-10", question_ref: "q1" }),
      review({ id: "review-2" }),
      review({ id: "review-99", created_at: "2026-08-02T00:00:00Z" }),
    ];

    expect(groupPendingReviews(items)[0].items.map((item) => item.id))
      .toEqual(["review-99", "review-2", "review-10"]);
  });

  test("trims and naturally selects display names and filenames independently", () => {
    const items = [
      review({ paper_display_name: " 试卷10 ", paper_filename: " file2.pdf " }),
      review({ paper_display_name: " 试卷2 ", paper_filename: " file10.pdf " }),
      review({ paper_display_name: " \t ", paper_filename: null }),
    ];

    expect(groupPendingReviews(items)[0]).toMatchObject({
      label: "试卷2",
      paperFilename: "file2.pdf",
    });
  });

  test.each([
    { paper_display_name: null, paper_filename: " paper.pdf ", label: "paper.pdf", filename: "paper.pdf" },
    { paper_display_name: " \t ", paper_filename: " ", label: "未命名试卷", filename: null },
  ])("falls back to $label when display names are absent", ({ label, filename, ...overrides }) => {
    expect(groupPendingReviews([review(overrides)])[0]).toMatchObject({
      label,
      paperFilename: filename,
    });
  });

  test("returns an empty group list for an empty queue", () => {
    expect(groupPendingReviews([])).toEqual([]);
  });

  test("does not mutate input and repeats the same ordering while retaining item identity", () => {
    const first = review({ id: "review-10", question_position: 1, question_ref: "Q2" });
    const second = review({ id: "review-2" });
    const standalone = review({ id: "review-3", paper_job_id: null });
    const items = [first, standalone, second];
    const original = structuredClone(items);
    items.forEach(Object.freeze);
    Object.freeze(items);

    const groups = groupPendingReviews(items);

    expect(items).toEqual(original);
    expect(groups[0].items[0]).toBe(second);
    expect(groups[0].items[1]).toBe(first);
    expect(groups[1].items[0]).toBe(standalone);
    expect(groupPendingReviews(items)).toEqual(groups);
    expect(groupPendingReviews([...items].reverse())).toEqual(groups);
  });

  test("preserves input order when all comparison fields collate equally", () => {
    const first = review({ id: "REVIEW-1", question_ref: "Q1", answer_mode: "uploaded" });
    const second = review({ id: "review-1", question_ref: "q1", answer_mode: "generated" });

    expect(groupPendingReviews([second, first])[0].items).toEqual([second, first]);
    expect(groupPendingReviews([first, second])[0].items).toEqual([first, second]);
  });
});
