import type { ReactElement } from "react";
import { render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { DesignSystemProvider } from "../components/ui/DesignSystemProvider";
import type { PaperUnitSummary, SourceDocument, SubjectStatus } from "../types";
import { PaperManagement } from "./PaperManagement";

const subject: SubjectStatus = {
  id: "oxfordaqa-mathematics-9660",
  subject_code: "9660",
  title: "OxfordAQA Mathematics",
  board_name: "OxfordAQA",
  version: "1",
  digest: "test",
  capability_profile_id: "oxfordaqa-mathematics-9660",
  generic_qa_enabled: true,
  answering_enabled: true,
  answering_disabled_reason: null,
  active_graph_version_id: null,
  knowledge_bases: [],
  units: [{ code: "P1", title: "Pure Mathematics 1", strand: "Pure" }],
  source_booklet_required: false,
  vector_alias: "test",
  vector_index_ready: true,
  vector_points: 10,
  stats: null,
  icon: "calculator",
  color: "#2F6FED",
};

function source(overrides: Partial<SourceDocument> = {}): SourceDocument {
  return {
    id: "qp-1", filename: "QP-202406-P1.pdf", display_name: "June paper", source_type: "question_paper",
    source_role: "assessment_only", authority_tier: "official", knowledge_base_id: null, license_confirmed: true,
    status: "converted", checksum: "qp", object_key: "corpus/qp.pdf", page_count: 24, error: null,
    pair_key: "9660:2024:JUN:P1", unit_code: "P1", exam_year: 2024, exam_session: "JUN",
    identity_status: "complete", identity_error: null, ...overrides,
  };
}

function paper(overrides: Partial<PaperUnitSummary> = {}): PaperUnitSummary {
  return {
    id: "unit-1", subject_id: subject.id, subject_code: "9660", pair_key: "9660:2024:JUN:P1",
    display_name: "June paper", unit_code: "P1", exam_year: 2024, exam_session: "JUN", status: "active",
    documents: [
      { id: "qp-1", filename: "QP-202406-P1.pdf", display_name: "June paper", role: "question_paper", source_type: "question_paper", status: "converted", checksum: "qp", page_count: 24 },
      { id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, role: "mark_scheme", source_type: "mark_scheme", status: "converted", checksum: "ms", page_count: 18 },
      { id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, role: "source_booklet", source_type: "insert", status: "converted", checksum: "insert", page_count: 8 },
    ],
    paper_job_count: 3, created_at: "2026-08-12T00:00:00Z", updated_at: "2026-08-12T00:00:00Z", ...overrides,
  };
}

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function installServer(initialRows: PaperUnitSummary[] = [paper()]) {
  let rows = [...initialRows];
  const documents = [source(), source({ id: "ms-1", filename: "MS-202406-P1.pdf", source_type: "mark_scheme", checksum: "ms" }), source({ id: "insert-1", filename: "Insert-202406-P1.pdf", source_type: "insert", checksum: "insert" })];
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    requests.push(request.clone());
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname.endsWith("/documents")) return json(documents);
    if (request.method === "GET" && url.pathname.endsWith("/paper-units")) return json({ items: rows, total: rows.length, limit: 12, offset: 0, available_units: ["P1"], available_years: [2024], available_sessions: ["JUN"] });
    if (request.method === "GET" && url.pathname.includes("/paper-units/")) return json(paper());
    if (request.method === "POST" && url.pathname.endsWith("/paper-units")) {
      const body = await request.json() as { display_name: string | null };
      const created = paper({ id: "unit-2", display_name: body.display_name });
      rows = [...rows, created];
      return json(created, 201);
    }
    if (request.method === "PATCH" && url.pathname.includes("/paper-units/")) {
      const body = await request.json() as { display_name: string | null };
      rows = rows.map((item) => item.id === "unit-1" ? { ...item, display_name: body.display_name } : item);
      return json(rows[0]);
    }
    if (request.method === "DELETE" && url.pathname.includes("/paper-units/")) {
      rows = [];
      return new Response(null, { status: 204 });
    }
    return json({ detail: `Unhandled ${request.method} ${url.pathname}` }, 500);
  }));
  return { requests };
}


afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); });

describe("PaperManagement", () => {
  test("shows canonical bindings, filters, and opens the URL-owned detail", async () => {
    installServer();
    const onOpenPaper = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<PaperManagement onOpenPaper={onOpenPaper} subjectId={subject.id} subjects={[subject]} />);
    const title = await screen.findByText("June paper");
    const card = title.closest<HTMLElement>(".ant-card");
    expect(within(card!).getByText("评分标准已绑定")).toBeVisible();
    expect(within(card!).getByText("支撑材料已绑定")).toBeVisible();
    expect(screen.getByLabelText("试卷分页")).toHaveTextContent("1–1/ 1 份");
    await user.click(title.closest("button")!);
    expect(onOpenPaper).toHaveBeenCalledWith(subject.id, "unit-1");
    rerender(<DesignSystemProvider><PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} /></DesignSystemProvider>);
    expect(await screen.findByRole("heading", { name: "June paper", level: 2 })).toBeVisible();
    expect(screen.getByRole("button", { name: /Mark Scheme/ })).toBeVisible();
  });

  test("loads an URL-addressed paper outside the current list page", async () => {
    const { requests } = installServer([]);
    render(<PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} />);
    expect(await screen.findByRole("heading", { name: "June paper", level: 2 })).toBeVisible();
    expect(requests.some((request) => request.method === "GET" && request.url.endsWith("/paper-units/unit-1"))).toBe(true);
  });

  test("updates and archives the paper aggregate without deleting source documents", async () => {
    const { requests } = installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getByRole("button", { name: "编辑 June paper" }));
    const name = screen.getByLabelText("显示名称（可选）");
    await user.clear(name);
    await user.type(name, "Mock exam A");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    expect(await screen.findByText("Mock exam A")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "归档 Mock exam A" }));
    await user.click(screen.getByRole("button", { name: "归档试卷" }));
    await waitFor(() => expect(screen.queryByText("Mock exam A")).not.toBeInTheDocument());
    expect(requests.some((request) => request.method === "PATCH" && request.url.includes("/paper-units/"))).toBe(true);
    expect(requests.some((request) => request.method === "DELETE" && request.url.includes("/paper-units/"))).toBe(true);
    expect(requests.some((request) => request.method === "DELETE" && request.url.includes("/documents/"))).toBe(false);
  });

  test("creates a paper with explicit Mark Scheme and Source Booklet membership", async () => {
    const { requests } = installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getAllByRole("button", { name: "添加试卷" })[0]);
    await user.selectOptions(screen.getByRole("combobox", { name: "Question Paper" }), "qp-1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Mark Scheme（可选）" }), "ms-1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Source Booklet（可选）" }), "insert-1");
    expect(screen.getByRole("button", { name: "保存试卷" })).toBeEnabled();
    await user.type(screen.getByLabelText("显示名称（可选）"), "June mock");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    await waitFor(() => {
      expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/paper-units"))).toBe(true);
    });
    const createRequest = requests.find((request) => request.method === "POST" && request.url.endsWith("/paper-units"));
    expect(createRequest).toBeDefined();
    await expect(createRequest!.clone().json()).resolves.toMatchObject({ document_ids: ["qp-1", "ms-1", "insert-1"], display_name: "June mock" });
    expect(await screen.findByText("June mock", {}, { timeout: 3000 })).toBeVisible();
  });
});
