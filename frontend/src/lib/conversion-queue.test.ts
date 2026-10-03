import { afterEach, describe, expect, test, vi } from "vitest";

import type { SourceDocument } from "../types";
import { createConversionQueue } from "./conversion-queue";

function document(id: string, status = "discovered"): SourceDocument {
  return {
    id, filename: `${id}.pdf`, display_name: null, source_type: "question_paper",
    source_role: "assessment_only", authority_tier: "official", knowledge_base_id: null,
    license_confirmed: true, status, checksum: id, object_key: `corpus/${id}.pdf`, page_count: 1,
    error: null, pair_key: null, unit_code: null, exam_year: null, exam_session: null,
    identity_status: "complete", identity_error: null,
  } as SourceDocument;
}

function conversionResponse(failed = 0) {
  return new Response(JSON.stringify({
    processed: 1, succeeded: failed ? 0 : 1, skipped: 0, failed, errors: failed ? ["PDF 无法转换"] : [],
  }), { status: 200, headers: { "Content-Type": "application/json" } });
}

afterEach(() => vi.unstubAllGlobals());

describe("conversion queue", () => {
  test("converts serially, skips duplicates and converted rows, and reports each outcome", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(conversionResponse())
      .mockResolvedValueOnce(conversionResponse(1));
    vi.stubGlobal("fetch", fetch);
    const queue = createConversionQueue();
    const events: string[] = [];
    queue.onEvent((event) => events.push(`${event.tone}:${event.message}`));

    expect(queue.enqueue([document("a"), document("a"), document("b"), document("done", "converted")], "s")).toBe(2);
    expect(queue.getSnapshot().states).toEqual({ a: "converting", b: "queued" });
    expect(queue.enqueue([document("a")], "s")).toBe(0);

    await vi.waitFor(() => expect(queue.getSnapshot().finished).toBe(2));
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(queue.getSnapshot().states).toEqual({ b: "failed" });
    expect(events).toEqual(["success:a.pdf 解析完成。", "error:PDF 无法转换"]);

    fetch.mockResolvedValueOnce(conversionResponse());
    expect(queue.enqueue([document("b")], "s")).toBe(1);
    await vi.waitFor(() => expect(queue.getSnapshot().states).toEqual({}));
  });
});
