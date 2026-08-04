import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import type { ReviewItem } from "../types";
import { Reviews } from "./Reviews";

const item: ReviewItem = {
  id: "assessment-1",
  question_ref: "Q1",
  total_awarded: 1,
  total_available: 2,
  confidence: 0.72,
  status: "pending_review",
  created_at: "2026-08-03T00:00:00Z",
  result: {
    assessment_id: "assessment-1",
    question_ref: "Q1",
    total_awarded: 1,
    total_available: 2,
    confidence: 0.72,
    status: "pending_review",
    rubric_awards: [],
    symbolic_checks: [],
    citations: [],
    warnings: [],
    manual_review_required: true,
  },
};

describe("Reviews", () => {
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
    await user.type(screen.getByRole("spinbutton", { name: "Q1 最终得分" }), "1.5");
    await user.click(screen.getByRole("button", { name: "改分并确认" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const request = fetch.mock.calls[0][0] as Request;
    expect(await request.clone().json()).toMatchObject({
      reviewer: "Ms Chen",
      decision: "override",
      override_mark: 1.5,
    });
  });
});
