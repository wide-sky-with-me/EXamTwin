import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import type { ReviewItem } from "../types";
import { Reviews } from "./Reviews";

const item: ReviewItem = {
  id: "assessment-1",
  subject_code: "9660",
  subject_id: "oxfordaqa-mathematics-9660",
  paper_job_id: "paper-job-1",
  paper_unit_id: "paper-unit-1",
  paper_display_name: "June 2026 U1",
  paper_filename: "question-paper.pdf",
  question_position: 1,
  answer_mode: "uploaded",
  question_ref: "Q1",
  total_awarded: 1,
  total_available: 2,
  confidence: 0.72,
  status: "pending_review",
  created_at: "2026-08-03T00:00:00Z",
  result: {
    assessment_id: "assessment-1",
    subject_code: "9660",
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
};

describe("Reviews", () => {
  beforeEach(() => window.localStorage.clear());
  test("groups linked reviews by paper and isolates every unlinked assessment", () => {
    const secondQuestion: ReviewItem = {
      ...item,
      id: "assessment-2",
      question_ref: "Q2",
      question_position: 2,
      result: {
        ...item.result,
        assessment_id: "assessment-2",
        question_ref: "Q2",
      },
    };
    const standalone: ReviewItem = {
      ...item,
      id: "assessment-standalone",
      paper_job_id: null,
      paper_display_name: null,
      paper_filename: null,
      question_position: null,
      answer_mode: null,
      question_ref: "Q3",
      result: {
        ...item.result,
        assessment_id: "assessment-standalone",
        question_ref: "Q3",
      },
    };

    const { container } = render(
      <Reviews items={[secondQuestion, standalone, item]} refresh={vi.fn()} />,
    );

    const groups = container.querySelectorAll(".review-paper-group");
    const linkedGroupText = groups[0].textContent ?? "";
    expect(groups).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "June 2026 U1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "独立评估 · Q3" })).toBeInTheDocument();
    expect(screen.getAllByText("外部答卷")).toHaveLength(2);
    expect(screen.getByText("来源未记录")).toBeInTheDocument();
    expect(groups[0]).toHaveTextContent("2 项待复核");
    expect(linkedGroupText.indexOf("Q1")).toBeLessThan(linkedGroupText.indexOf("Q2"));
    expect(groups[1]).toHaveTextContent("未关联试卷 · 旧版或独立评估");
  });


  test("submits an explicit reviewer and override mark", async () => {
    const user = userEvent.setup();
    const refresh = vi.fn().mockResolvedValue(undefined);
    const fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ status: "overridden" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetch);
    render(<Reviews items={[item]} refresh={refresh} />);

    await user.clear(screen.getByRole("textbox", { name: "复核人" }));
    await user.type(screen.getByRole("textbox", { name: "复核人" }), "Ms Chen");
    expect(window.localStorage.getItem("examtwin.reviewerName")).toBe("Ms Chen");
    await user.type(screen.getByRole("spinbutton", { name: "Q1 最终得分" }), "1.5");
    await user.click(screen.getByRole("button", { name: "改分并确认" }));
    await user.click(screen.getByRole("button", { name: "确认改分" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const request = fetch.mock.calls[0][0] as Request;
    expect(await request.clone().json()).toMatchObject({
      reviewer: "Ms Chen",
      decision: "override",
      override_mark: 1.5,
    });
  }, 10_000);

  test("does not publish a final score when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<Reviews items={[item]} refresh={vi.fn()} />);

    await user.type(screen.getByRole("textbox", { name: "复核人" }), "Ms Chen");
    await user.click(screen.getByRole("button", { name: "确认评分" }));
    expect(screen.getByRole("alertdialog", { name: "确认评分？" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "取消" }));

    expect(fetch).not.toHaveBeenCalled();
  });

  test("opens evidence only for a deep-linked item and links back to grading", async () => {
    const user = userEvent.setup();
    const onOpenGrading = vi.fn();
    const { unmount } = render(<Reviews items={[item]} onOpenGrading={onOpenGrading} refresh={vi.fn()} />);
    expect(screen.queryByText("Q1 · 评分证据")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "打开评分" }));
    expect(onOpenGrading).toHaveBeenCalledWith(item);
    unmount();

    render(<Reviews focusId={item.id} items={[item]} refresh={vi.fn()} />);
    expect(await screen.findByText("Q1 · 评分证据")).toBeInTheDocument();
  });

  test("leaves a deep link once its review is submitted", async () => {
    const user = userEvent.setup();
    const onReviewed = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ assessment_id: item.id, status: "confirmed", final_mark: 1, reviewed_by: "Ms Chen" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )));
    render(<Reviews items={[item]} onReviewed={onReviewed} refresh={vi.fn().mockResolvedValue(undefined)} />);
    await user.type(screen.getByRole("textbox", { name: "复核人" }), "Ms Chen");
    await user.click(screen.getByRole("button", { name: "确认评分" }));
    await user.click(screen.getAllByRole("button", { name: "确认评分" }).at(-1)!);
    await waitFor(() => expect(onReviewed).toHaveBeenCalledOnce());
  });
});
