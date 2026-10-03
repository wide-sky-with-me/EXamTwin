import type { ReactElement } from "react";
import { render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { SourceDocument, SubjectStatus } from "../types";
import { SubjectWorkspace } from "./SubjectWorkspace";
import { DesignSystemProvider } from "./ui/DesignSystemProvider";

const subject = {
  id: "oxfordaqa-mathematics-9660",
  subject_code: "9660",
  title: "OxfordAQA Mathematics",
  board_name: "OxfordAQA",
  knowledge_bases: [],
  units: [],
} as unknown as SubjectStatus;

function source(overrides: Partial<SourceDocument>): SourceDocument {
  return {
    id: "qp-1", filename: "QP-202406-P1.pdf", display_name: null, source_type: "question_paper",
    source_role: "assessment_only", authority_tier: "official", knowledge_base_id: null,
    license_confirmed: true, status: "failed", checksum: "qp", object_key: "corpus/qp.pdf",
    page_count: 24, error: null, pair_key: "9660:2024:JUN:P1", unit_code: "P1", exam_year: 2024,
    exam_session: "JUN", identity_status: "complete", identity_error: null, ...overrides,
  } as SourceDocument;
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

afterEach(() => vi.unstubAllGlobals());

describe("SubjectWorkspace", () => {
  test("retries parsing a failed document and keeps a blocked delete inside its dialog", async () => {
    let documents = [source({})];
    const conversions: string[][] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname.endsWith("/documents")) return json(documents);
      if (request.method === "POST" && url.pathname.endsWith("/corpus/convert")) {
        const body = await request.json() as { document_ids: string[] };
        conversions.push(body.document_ids);
        documents = documents.map((item) => ({ ...item, status: "converted" }));
        return json({ processed: 1, succeeded: 1, skipped: 0, failed: 0, errors: [] });
      }
      if (request.method === "DELETE") {
        return json({ detail: "该资料已绑定试卷「June paper」，请先在试卷中替换该文件或永久删除试卷后再删除资料。" }, 409);
      }
      return json({ detail: "unhandled" }, 500);
    }));
    const user = userEvent.setup();
    render(<SubjectWorkspace onChanged={vi.fn().mockResolvedValue(undefined)} subject={subject} view="documents" />);

    expect(await screen.findByText("解析失败")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "解析 QP-202406-P1.pdf" }));
    await waitFor(() => expect(screen.getByText("已解析")).toBeInTheDocument());
    expect(conversions).toEqual([["qp-1"]]);

    await user.click(screen.getByRole("button", { name: "删除 QP-202406-P1.pdf" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "删除资料" }));
    expect(await within(dialog).findByText(/已绑定试卷「June paper」/)).toBeInTheDocument();
    expect(screen.getByText("QP-202406-P1.pdf")).toBeInTheDocument();
  });
});
