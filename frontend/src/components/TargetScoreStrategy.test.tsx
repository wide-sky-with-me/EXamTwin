import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { TargetScoreFields, type StrategyRequest } from "./TargetScoreStrategy";
import { uploadPaper } from "../lib/api";

afterEach(() => vi.unstubAllGlobals());

test.each([false, true])("collects both budgets and learner baseline (economics=%s)", async (economics) => {
  const submitted = vi.fn();
  function Form() {
    const [value, setValue] = useState<StrategyRequest | null>(null);
    return <form onSubmit={(event) => { event.preventDefault(); submitted(value); }}>
      <TargetScoreFields value={value} onChange={setValue} economics={economics} />
      <button type="submit">提交</button>
    </form>;
  }
  render(<Form />);
  expect(screen.queryByLabelText("目标分数")).toBeNull();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByLabelText("考试时长（分钟）")).toHaveValue(economics ? 105 : 90);
  fireEvent.change(screen.getByLabelText("目标分数"), { target: { value: "64" } });
  fireEvent.change(screen.getByLabelText("可备考时间（小时）"), { target: { value: "8" } });
  fireEvent.change(screen.getByLabelText("当前基础与薄弱项"), { target: { value: "熟悉计算，论证较弱" } });
  fireEvent.click(screen.getByText("提交"));
  expect(submitted).toHaveBeenCalledWith(expect.objectContaining({ target_score: 64, study_budget_minutes: 480, preparation: "熟悉计算，论证较弱" }));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByText("提交"));
  expect(submitted).toHaveBeenLastCalledWith(null);
});

test("upload preserves target settings as JSON alongside the original PDF", async () => {
  const request: StrategyRequest = { target_score: 48, score_tolerance: 5, study_budget_minutes: 480,
    exam_budget_minutes: 105, reserve_minutes: 10, preparation: "基本概念已掌握" };
  const fetch = vi.fn(async (_url, init: RequestInit) => {
    const form = init.body as FormData;
    expect(JSON.parse(String(form.get("strategy")))).toEqual(request);
    expect((form.get("file") as File).name).toBe("original.pdf");
    return new Response(JSON.stringify({ job_id: "new", status: "queued", stage: "queued" }));
  });
  vi.stubGlobal("fetch", fetch);
  await uploadPaper("economics", new File(["pdf"], "original.pdf"), "U1", null, request);
  expect(fetch).toHaveBeenCalledOnce();
});
