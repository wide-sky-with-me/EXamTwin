import type { ReactElement } from "react";
import { fireEvent, render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
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

function installServer(
  initialRows: PaperUnitSummary[] = [paper()],
  initialDocuments: SourceDocument[] = [source(), source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms" }), source({ id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, source_type: "insert", checksum: "insert" })],
) {
  let rows = [...initialRows];
  let documents = [...initialDocuments];
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    requests.push(request.clone());
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname.endsWith("/documents")) return json(documents);
    if (request.method === "GET" && url.pathname.endsWith("/papers/jobs")) return json({ items: [], total: 0, limit: 10, offset: 0 });
    if (request.method === "GET" && url.pathname.endsWith("/paper-units")) return json({ items: rows, total: rows.length, limit: 12, offset: 0, available_units: ["P1"], available_years: [2024], available_sessions: ["JUN"] });
    if (request.method === "GET" && url.pathname.includes("/paper-units/")) return json(paper());
    if (request.method === "POST" && url.pathname.endsWith("/corpus/convert")) {
      const body = await request.json() as { document_ids: string[] };
      documents = documents.map((item) => body.document_ids.includes(item.id) ? { ...item, status: "converting" } : item);
      await new Promise((resolve) => setTimeout(resolve, 80));
      documents = documents.map((item) => body.document_ids.includes(item.id) ? { ...item, status: "converted" } : item);
      return json({ processed: 1, succeeded: 1, skipped: 0, failed: 0, errors: [] });
    }
    if (request.method === "POST" && url.pathname.endsWith("/paper-units")) {
      const body = await request.json() as { display_name: string | null };
      const created = paper({ id: "unit-2", display_name: body.display_name });
      rows = [...rows, created];
      return json(created, 201);
    }
    if (request.method === "POST" && url.pathname.endsWith("/import-answer")) {
      return json({ job_id: "job-uploaded", status: "queued", stage: "queued", paper_unit_id: "unit-1", question_paper_document_id: "qp-1" }, 202);
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
    expect(screen.queryByRole("heading", { name: "试卷库" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "选择科目" }).closest(".paper-management-toolbar")).not.toBeNull();
    const title = await screen.findByText("June paper");
    const card = title.closest<HTMLElement>(".ant-card");
    expect(within(card!).getByText("使用中")).toBeVisible();
    expect(within(card!).getByText("Mark Scheme")).toBeVisible();
    expect(within(card!).getByText("含支撑材料")).toBeVisible();
    expect(screen.getByLabelText("试卷分页")).toHaveTextContent("1–1/ 1 份");
    await user.click(title.closest("button")!);
    expect(onOpenPaper).toHaveBeenCalledWith(subject.id, "unit-1");
    rerender(<DesignSystemProvider><PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} /></DesignSystemProvider>);
    expect(await screen.findByRole("heading", { name: "June paper", level: 2 })).toBeVisible();
    expect(screen.getByRole("button", { name: /Mark Scheme/ })).toBeVisible();
    const summary = document.querySelector<HTMLElement>(".paper-detail-summary");
    expect(summary).toBeInTheDocument();
    expect(within(summary!).getByText("作答记录")).toBeVisible();
    expect(within(summary!).getByText("试卷状态")).toBeVisible();
    expect(within(summary!).getByText("最近更新")).toBeVisible();
  });

  test("loads an URL-addressed paper outside the current list page", async () => {
    const { requests } = installServer([]);
    render(<PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} />);
    expect(await screen.findByRole("heading", { name: "June paper", level: 2 })).toBeVisible();
    expect(requests.some((request) => request.method === "GET" && request.url.endsWith("/paper-units/unit-1"))).toBe(true);
  });

  test("shows a styled document detail with original preview and download actions", async () => {
    installServer();
    render(<PaperManagement detail={{ kind: "document", id: "ms-1" }} subjectId={subject.id} subjects={[subject]} />);
    expect(await screen.findByRole("heading", { name: "MS-202406-P1.pdf", level: 2 })).toBeVisible();
    const detail = document.querySelector<HTMLElement>(".paper-document-detail");
    expect(detail).toBeInTheDocument();
    expect(within(detail!).getAllByText("Mark Scheme")).toHaveLength(2);
    expect(within(detail!).getByText("已识别")).toBeVisible();
    expect(within(detail!).getByText("已解析")).toBeVisible();
    expect(screen.getByRole("link", { name: "预览原文件" })).toHaveAttribute(
      "href",
      expect.stringContaining("/documents/ms-1/content?subject=oxfordaqa-mathematics-9660"),
    );
    expect(screen.getByRole("link", { name: "下载原文件" })).toHaveAttribute(
      "href",
      expect.stringContaining("download=true"),
    );
  });

  test("returns to the parent paper and refreshes conversion state while parsing", async () => {
    const pendingScheme = source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms", status: "discovered" });
    const { requests } = installServer([paper()], [source(), pendingScheme]);
    const onBackDocument = vi.fn();
    const user = userEvent.setup();
    render(<PaperManagement
      detail={{ kind: "document", id: "ms-1", parentPaperId: "unit-1" }}
      onBackDocument={onBackDocument}
      subjectId={subject.id}
      subjects={[subject]}
    />);
    await user.click(await screen.findByRole("button", { name: "返回试卷详情" }));
    expect(onBackDocument).toHaveBeenCalledWith(subject.id, "unit-1");
    await user.click(screen.getByRole("button", { name: "解析内容" }));
    expect(screen.getByText("解析中")).toBeVisible();
    await waitFor(() => expect(screen.getByText("已解析")).toBeVisible(), { timeout: 3000 });
    expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/corpus/convert"))).toBe(true);
    expect(screen.queryByRole("button", { name: "解析内容" })).not.toBeInTheDocument();
  });

  test("updates and deletes the paper aggregate without deleting source documents", async () => {
    const { requests } = installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getByRole("button", { name: "编辑 June paper" }));
    expect(screen.queryByRole("combobox", { name: "Question Paper" })).not.toBeInTheDocument();
    expect(document.querySelectorAll(".paper-editor-current-file")).toHaveLength(3);
    expect(screen.getAllByText("已解析")).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "更新文件" })).toHaveLength(3);
    const name = screen.getByLabelText("试卷名称");
    await user.clear(name);
    await user.type(name, "Mock exam A");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    expect(await screen.findByText("Mock exam A")).toBeVisible();
    const updateRequest = requests.find((request) => request.method === "PATCH" && request.url.includes("/paper-units/"));
    expect(updateRequest).toBeDefined();
    await expect(updateRequest!.clone().json()).resolves.toEqual({ document_ids: null, display_name: "Mock exam A" });
    await user.click(screen.getByRole("button", { name: "删除 Mock exam A" }));
    await user.click(screen.getByRole("button", { name: "删除试卷" }));
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
    const dragger = screen.getByLabelText("上传 Mark Scheme（可选）");
    expect(dragger.closest(".ant-upload-drag")).not.toBeNull();
    await user.selectOptions(screen.getByRole("combobox", { name: "Question Paper" }), "qp-1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Mark Scheme（可选）" }), "ms-1");
    await user.selectOptions(screen.getByRole("combobox", { name: "Source Booklet（可选）" }), "insert-1");
    expect(screen.getByRole("button", { name: "保存试卷" })).toBeEnabled();
    await user.type(screen.getByLabelText("试卷名称"), "June mock");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    await waitFor(() => {
      expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/paper-units"))).toBe(true);
    });
    const createRequest = requests.find((request) => request.method === "POST" && request.url.endsWith("/paper-units"));
    expect(createRequest).toBeDefined();
    await expect(createRequest!.clone().json()).resolves.toMatchObject({ document_ids: ["qp-1", "ms-1", "insert-1"], display_name: "June mock" });
    expect(await screen.findByText("June mock", {}, { timeout: 3000 })).toBeVisible();
  });

  test("parses an existing material in the editor and only reveals upload when updating", async () => {
    const pendingScheme = source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms", status: "discovered" });
    const pendingPaper = paper({
      documents: paper().documents.map((item) => item.id === "ms-1" ? { ...item, status: "discovered" } : item),
    });
    const { requests } = installServer([pendingPaper], [source(), pendingScheme, source({ id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, source_type: "insert", checksum: "insert" })]);
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getByRole("button", { name: "编辑 June paper" }));
    expect(screen.queryByLabelText("上传 Mark Scheme（可选）")).not.toBeInTheDocument();
    const schemeCard = screen.getByText("MS-202406-P1.pdf").closest<HTMLElement>(".paper-editor-material");
    expect(schemeCard).not.toBeNull();
    await user.click(within(schemeCard!).getByRole("button", { name: "解析" }));
    expect(within(schemeCard!).getAllByText("解析中")).toHaveLength(2);
    await waitFor(() => expect(screen.getAllByText("已解析").length).toBeGreaterThanOrEqual(3), { timeout: 3000 });
    const refreshedSchemeCard = screen.getByText("MS-202406-P1.pdf").closest<HTMLElement>(".paper-editor-material");
    await user.click(within(refreshedSchemeCard!).getByRole("button", { name: "更新文件" }));
    expect(within(refreshedSchemeCard!).getByLabelText("上传 Mark Scheme（可选）")).toBeInTheDocument();
    expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/corpus/convert"))).toBe(true);
  });

  test("imports an external answer into the current paper and opens its managed result", async () => {
    const { requests } = installServer();
    const onStartAnswering = vi.fn();
    const user = userEvent.setup();
    render(<PaperManagement
      detail={{ kind: "paper", id: "unit-1" }}
      onStartAnswering={onStartAnswering}
      subjectId={subject.id}
      subjects={[subject]}
    />);
    await user.click(await screen.findByRole("button", { name: "导入外部答卷" }));
    const dialog = screen.getAllByRole("dialog").find((candidate) =>
      within(candidate).queryByRole("button", { name: "导入并解析" }),
    );
    expect(dialog).toBeDefined();
    expect(within(dialog!).getByText(/统一管理/)).toBeInTheDocument();
    const input = dialog!.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [new File(["answer"], "student-answer.pdf", { type: "application/pdf" })] } });
    fireEvent.click(within(dialog!).getByRole("button", { name: "导入并解析" }));
    await waitFor(() => expect(onStartAnswering).toHaveBeenCalledWith(subject.id, "unit-1", "job-uploaded"));
    expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/paper-units/unit-1/import-answer"))).toBe(true);
  });
});
