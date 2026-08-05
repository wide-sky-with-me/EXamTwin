import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { Grading } from "./Grading";

describe("Grading", () => {
  test("blocks an empty maximum mark before sending a request", async () => {
    const user = userEvent.setup();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    render(<Grading onCreated={vi.fn()} />);

    await user.type(screen.getByRole("spinbutton", { name: "满分" }), "0");

    expect(screen.getByText("请输入大于 0 的满分。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成逐项评分" })).toBeDisabled();
    expect(fetch).not.toHaveBeenCalled();
  });

  test("shows warnings, symbolic checks, confidence and citations from grading", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      assessment_id: "assessment-1",
      total_awarded: 1,
      total_available: 2,
      confidence: 0.58,
      status: "pending_review",
      rubric_awards: [],
      symbolic_checks: [{
        student: "x=2",
        expected: "x=3",
        equivalent: false,
        detail: "The expressions are not equivalent.",
      }],
      citations: [{
        source: "mark-scheme.md",
        source_type: "mark_scheme",
        excerpt: "Award A1 for x=3.",
      }],
      warnings: ["低置信度，需要人工核对。"],
      manual_review_required: true,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    render(<Grading onCreated={vi.fn().mockResolvedValue(undefined)} />);

    const [question, scheme, answer] = screen.getAllByRole("textbox");
    await user.type(question, "Solve x=3.");
    await user.type(scheme, "A1 Award one mark for x=3.");
    await user.type(answer, "x=2");
    await user.type(screen.getByRole("spinbutton", { name: "满分" }), "2");
    await user.click(screen.getByRole("button", { name: "生成逐项评分" }));

    await waitFor(() => expect(screen.getByText("低置信度，需要人工核对。")).toBeInTheDocument());
    expect(screen.getByText("The expressions are not equivalent.")).toBeInTheDocument();
    expect(screen.getByText("[S1] · Mark scheme")).toBeInTheDocument();
    expect(screen.getByLabelText("模型置信度 58%")).toBeInTheDocument();
  });
});
