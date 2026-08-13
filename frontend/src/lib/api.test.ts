import { afterEach, describe, expect, it, vi } from "vitest";

import {
  backendResourceUrl,
  unwrapApi,
  uploadPaper,
  websocketUrl,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("subject-scoped transport", () => {
  it("accepts successful no-content API responses", async () => {
    await expect(unwrapApi(Promise.resolve({
      response: new Response(null, { status: 204 }),
    }))).resolves.toBeUndefined();
  });

  it("carries the selected package across uploads, assets, and WebSocket handshakes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job-1", status: "queued", stage: "queued" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await uploadPaper(
      "oxfordaqa-economics-9640",
      new File(["# Paper"], "paper.md"),
      "U1",
    );

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("X-ExamTwin-Subject")).toBe(
      "oxfordaqa-economics-9640",
    );
    expect(backendResourceUrl(
      "/papers/jobs/job-1/source",
      "oxfordaqa-economics-9640",
    )).toContain("subject=oxfordaqa-economics-9640");
    expect(websocketUrl(
      "/papers/jobs/job-1/events",
      "oxfordaqa-economics-9640",
    )).toContain(
      "subject=oxfordaqa-economics-9640",
    );
  });
});
