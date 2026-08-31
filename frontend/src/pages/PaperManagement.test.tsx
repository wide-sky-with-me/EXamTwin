import type { ReactElement } from "react";
import { fireEvent, render as testingLibraryRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { DesignSystemProvider } from "../components/ui/DesignSystemProvider";
import { subscribeTaskSnapshots } from "../lib/task-events";
import type { PaperJobResult, PaperJobSummary, PaperUnitSummary, SourceDocument, SubjectStatus } from "../types";
import { PaperManagement } from "./PaperManagement";

vi.mock("../lib/task-events", () => ({
  subscribeTaskSnapshots: vi.fn(() => () => undefined),
}));

const subscribeMock = vi.mocked(subscribeTaskSnapshots);

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

const economicsSubject: SubjectStatus = {
  ...subject,
  id: "oxfordaqa-economics-9640",
  subject_code: "9640",
  title: "OxfordAQA Economics",
  capability_profile_id: "oxfordaqa-economics-9640",
  units: [{ code: "U1", title: "Markets", strand: "Economics" }],
  source_booklet_required: true,
  vector_alias: "test-economics",
  color: "#0F766E",
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

async function visibleModal(title: string) {
  let modal: HTMLElement | undefined;
  await waitFor(() => {
    modal = screen.queryAllByText(title, { exact: true })
      .map((element) => element.closest<HTMLElement>("[role='dialog'], .ant-modal"))
      .find((candidate): candidate is HTMLElement => candidate !== null);
    expect(modal).toBeInTheDocument();
  });
  return modal!;
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function installServer(
  initialRows: PaperUnitSummary[] = [paper()],
  initialDocuments: SourceDocument[] = [source(), source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms" }), source({ id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, source_type: "insert", checksum: "insert" })],
  conversionDelay = 80,
  paperJobs: PaperJobSummary[] = [],
  paperDetail: PaperUnitSummary | null = paper(),
) {
  let rows = [...initialRows];
  let trashedRows: PaperUnitSummary[] = [];
  let documents = [...initialDocuments];
  const requests: Request[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    requests.push(request.clone());
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname.endsWith("/documents")) return json(documents);
    if (request.method === "GET" && url.pathname.endsWith("/papers/jobs")) {
      return json({ items: paperJobs, total: paperJobs.length, limit: 10, offset: 0 });
    }
    if (request.method === "GET" && url.pathname.endsWith("/paper-units/trash")) return json({ items: trashedRows, total: trashedRows.length, limit: 100, offset: 0, available_units: [], available_years: [], available_sessions: [] });
    if (request.method === "GET" && url.pathname.endsWith("/paper-units")) return json({ items: rows, total: rows.length, limit: 12, offset: 0, available_units: ["P1"], available_years: [2024], available_sessions: ["JUN"] });
    if (request.method === "GET" && url.pathname.includes("/paper-units/")) {
      return paperDetail ? json(paperDetail) : json({ detail: "Paper unit not found" }, 404);
    }
    if (request.method === "POST" && url.pathname.endsWith("/corpus/convert")) {
      const body = await request.json() as { document_ids: string[] };
      documents = documents.map((item) => body.document_ids.includes(item.id) ? { ...item, status: "converting" } : item);
      await new Promise((resolve) => setTimeout(resolve, conversionDelay));
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
    if (request.method === "POST" && url.pathname.endsWith("/restore")) {
      const restored = { ...trashedRows[0], status: "active" as const };
      trashedRows = trashedRows.filter((item) => item.id !== restored.id);
      rows = [...rows, restored];
      return json(restored);
    }
    if (request.method === "PATCH" && url.pathname.includes("/paper-units/")) {
      const body = await request.json() as { display_name: string | null };
      rows = rows.map((item) => item.id === "unit-1" ? { ...item, display_name: body.display_name } : item);
      return json(rows[0]);
    }
    if (request.method === "DELETE" && url.pathname.endsWith("/permanent")) {
      const paperUnitId = url.pathname.split("/").at(-2);
      trashedRows = trashedRows.filter((item) => item.id !== paperUnitId);
      return new Response(null, { status: 204 });
    }
    if (request.method === "DELETE" && url.pathname.includes("/paper-units/")) {
      trashedRows = [...trashedRows, ...rows.map((item) => ({ ...item, status: "archived" as const }))];
      rows = [];
      return new Response(null, { status: 204 });
    }
    return json({ detail: `Unhandled ${request.method} ${url.pathname}` }, 500);
  }));
  return { requests };
}


afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); });

describe("PaperManagement", () => {
  test("keeps the result geometry stable and ignores stale responses while switching subjects", async () => {
    let releaseEconomics!: () => void;
    const economicsReady = new Promise<void>((resolve) => { releaseEconomics = resolve; });
    const requestedSubjects: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      const url = new URL(request.url);
      if (request.method === "GET" && url.pathname.endsWith("/documents")) return json([]);
      if (request.method === "GET" && url.pathname.endsWith("/paper-units")) {
        const requestedSubject = request.headers.get("X-ExamTwin-Subject") ?? "";
        requestedSubjects.push(requestedSubject);
        if (requestedSubject === economicsSubject.id) {
          await economicsReady;
          return json({ items: [], total: 0, limit: 12, offset: 0, available_units: [], available_years: [], available_sessions: [] });
        }
        return json({ items: [paper()], total: 1, limit: 12, offset: 0, available_units: ["P1"], available_years: [2024], available_sessions: ["JUN"] });
      }
      return json({ detail: `Unhandled ${request.method} ${url.pathname}` }, 500);
    }));

    const { rerender } = render(<PaperManagement subjectId={subject.id} subjects={[subject, economicsSubject]} />);
    expect(await screen.findByText("June paper")).toBeVisible();

    rerender(<PaperManagement subjectId={economicsSubject.id} subjects={[subject, economicsSubject]} />);

    const results = document.querySelector<HTMLElement>(".paper-management-results");
    const resultContent = document.querySelector<HTMLElement>(".paper-management-results-content");
    await waitFor(() => expect(results).toHaveClass("is-loading"));
    expect(resultContent).toHaveAttribute("aria-hidden", "true");
    expect(document.querySelectorAll(".ant-skeleton")).toHaveLength(0);
    expect(screen.getByText("正在加载试卷…")).toBeVisible();

    rerender(<PaperManagement subjectId={subject.id} subjects={[subject, economicsSubject]} />);
    await waitFor(() => expect(results).not.toHaveClass("is-loading"));
    expect(screen.getByText("June paper")).toBeVisible();

    releaseEconomics();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("June paper")).toBeVisible();
    expect(screen.queryByText("当前条件下没有试卷")).not.toBeInTheDocument();
    expect(requestedSubjects).toEqual([subject.id, economicsSubject.id, subject.id]);
  });

  test("shows material parse states and queues all pending bindings from the card", async () => {
    const pendingDocuments = [
      source({ status: "discovered" }),
      source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms", status: "discovered" }),
      source({ id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, source_type: "insert", checksum: "insert", status: "discovered" }),
    ];
    const pendingPaper = paper({
      documents: paper().documents.map((document) => ({ ...document, status: "discovered" })),
    });
    const { requests } = installServer([pendingPaper], pendingDocuments);
    const onOpenPaper = vi.fn();
    const user = userEvent.setup();
    render(<PaperManagement onOpenPaper={onOpenPaper} subjectId={subject.id} subjects={[subject]} />);

    const title = await screen.findByText("June paper");
    const card = title.closest<HTMLElement>(".paper-unit-card");
    expect(card).toBeInTheDocument();
    expect(within(card!).getAllByText("待解析")).toHaveLength(3);
    const quickParse = within(card!).getByRole("button", { name: "一键解析 June paper" });
    await waitFor(() => expect(quickParse).toBeEnabled());
    await user.click(quickParse);
    expect(onOpenPaper).not.toHaveBeenCalled();
    expect(within(card!).getByText("解析中")).toBeInTheDocument();
    expect(within(card!).getAllByText("排队中")).toHaveLength(2);

    await waitFor(() => {
      const conversionRequests = requests.filter((request) => request.method === "POST" && request.url.endsWith("/corpus/convert"));
      expect(conversionRequests).toHaveLength(3);
    }, { timeout: 4000 });
    await waitFor(() => expect(within(card!).getAllByText("已解析")).toHaveLength(3), { timeout: 4000 });
  });

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
    expect(within(card!).getByText("Source Booklet")).toBeVisible();
    expect(screen.getByLabelText("试卷分页")).toHaveTextContent("1–1/ 1 份");
    await user.click(title.closest("button")!);
    expect(onOpenPaper).toHaveBeenCalledWith(subject.id, "unit-1");
    rerender(<DesignSystemProvider><PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} /></DesignSystemProvider>);
    const detailDialog = await visibleModal("试卷详情");
    expect(within(detailDialog).getByRole("heading", { name: "June paper", level: 2 })).toBeInTheDocument();
    const bindingList = detailDialog.querySelector<HTMLElement>(".paper-binding-list");
    expect(bindingList).toBeInTheDocument();
    const bindingRows = within(bindingList!).getAllByRole("button");
    expect(bindingRows).toHaveLength(3);
    expect(bindingRows.every((row) => row.querySelector(".paper-binding-icon svg"))).toBe(true);
    expect(bindingRows.every((row) => row.querySelector(".paper-binding-copy"))).toBe(true);
    expect(bindingRows.every((row) => row.querySelector(".paper-binding-meta"))).toBe(true);
    expect(within(detailDialog).getByRole("button", { name: /Mark Scheme/ })).toBeInTheDocument();
    const summary = detailDialog.querySelector<HTMLElement>(".paper-detail-summary");
    expect(summary).toBeInTheDocument();
    expect(within(summary!).getByText("作答记录")).toBeInTheDocument();
    expect(within(summary!).getByText("资料")).toBeInTheDocument();
    expect(within(summary!).getByText("最近更新")).toBeInTheDocument();
  });

  test("loads an URL-addressed paper outside the current list page", async () => {
    const { requests } = installServer([]);
    render(<PaperManagement detail={{ kind: "paper", id: "unit-1" }} subjectId={subject.id} subjects={[subject]} />);
    const detailDialog = await visibleModal("试卷详情");
    expect(within(detailDialog).getByRole("heading", { name: "June paper", level: 2 })).toBeInTheDocument();
    expect(requests.some((request) => request.method === "GET" && request.url.endsWith("/paper-units/unit-1"))).toBe(true);
  });

  test("opens paper-owned answer records as a modal", async () => {
    installServer();
    render(<PaperManagement detail={{ kind: "answers", paperId: "unit-1" }} subjectId={subject.id} subjects={[subject]} />);

    const answersDialog = await visibleModal("作答记录 · June paper");
    const embeddedHistory = answersDialog.querySelector(".paper-history-embedded");
    expect(embeddedHistory).toBeInTheDocument();
    expect(embeddedHistory).not.toHaveClass("panel");
    expect(await within(answersDialog).findByText("还没有作答记录")).toBeInTheDocument();
  });

  test("does not rewrite an unbound history job onto the current paper route", async () => {
    const unboundJob: PaperJobSummary = {
      job_id: "unbound-job",
      filename: "legacy-unbound.pdf",
      display_name: null,
      answer_mode: "generated",
      pair_key: null,
      paper_unit_id: null,
      question_paper_document_id: null,
      source_booklet_document_id: null,
      source_booklet_checksum: null,
      source_booklet_filename: null,
      unit_code: "P1",
      status: "completed",
      stage: "completed",
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      source_integrity_status: "verified",
      split_contract_version: "paper-question-split-v6",
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      created_at: "2026-08-05T08:00:00+00:00",
      updated_at: "2026-08-05T08:30:00+00:00",
    };
    installServer(undefined, undefined, undefined, [unboundJob]);
    const onOpenJob = vi.fn();
    render(
      <PaperManagement
        detail={{ kind: "job", id: "route-job", paperId: "unit-1" }}
        onOpenJob={onOpenJob}
        subjectId={subject.id}
        subjects={[subject]}
      />,
    );

    const resultDialog = await visibleModal("作答详情 · June paper");
    expect(await within(resultDialog).findByText("正在加载作答详情")).toBeInTheDocument();
    expect(onOpenJob).not.toHaveBeenCalled();
    expect(resultDialog).toBeInTheDocument();
  });

  test("keeps a routed job reachable after its paper is archived", async () => {
    const archivedJob: PaperJobResult = {
      job_id: "archived-job",
      filename: "archived-answer.pdf",
      display_name: "Archived answer record",
      answer_mode: "generated",
      pair_key: "9660:2024:JUN:P1",
      paper_unit_id: "archived-unit",
      question_paper_document_id: "qp-archived",
      source_booklet_document_id: null,
      source_booklet_checksum: null,
      source_booklet_filename: null,
      subject_pack_id: subject.id,
      subject_code: subject.subject_code,
      knowledge_base_version_ids: [],
      graph_version_id: null,
      replaced_by_job_id: null,
      replacement_for_job_id: null,
      source_integrity_status: "verified",
      split_contract_version: "paper-question-split-v6",
      split_source_digest: "archived-source",
      unit_code: "P1",
      status: "completed",
      stage: "completed",
      total_pages: 1,
      parsed_pages: 1,
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:01:00Z",
      chunks: [],
      questions: [{
        position: 1,
        number: "1",
        question_markdown: "Archived question",
        answer_markdown: "Archived answer",
        diagrams: [],
        images: [],
        citations: [],
        knowledge_points: [],
        confidence: 1,
        grounded: true,
        warnings: [],
        attempts: 1,
        requires_visual_context: false,
        source_pages: [1],
        source_warnings: [],
        answer_requirements: [],
        agent_steps: [],
        source_digest: "archived-question",
        source_kind: "primary",
        status: "completed",
        total_marks: 1,
        error: null,
      }],
      error: null,
    };
    subscribeMock.mockImplementationOnce((options) => {
      expect(options.path).toBe("/papers/jobs/archived-job/events");
      options.onSnapshot(archivedJob);
      options.onState("idle");
      return () => undefined;
    });
    const { requests } = installServer([], undefined, undefined, [], null);
    render(
      <PaperManagement
        detail={{ kind: "job", id: "archived-job", paperId: "archived-unit" }}
        subjectId={subject.id}
        subjects={[subject]}
      />,
    );

    const resultDialog = await visibleModal("作答详情");
    expect(await within(resultDialog).findByText("Archived answer record")).toBeInTheDocument();
    expect(within(resultDialog).getByText("Archived question")).toBeInTheDocument();
    expect(within(resultDialog).getByText("Archived answer")).toBeInTheDocument();
    expect(within(resultDialog).queryByText("正在加载作答详情")).not.toBeInTheDocument();
    expect(within(resultDialog).queryByText(/无法打开作答详情/)).not.toBeInTheDocument();
    expect(requests.some((request) =>
      request.method === "GET" && request.url.endsWith("/paper-units/archived-unit")
    )).toBe(true);
  });

  test("shows a styled document detail with original preview and download actions", async () => {
    installServer();
    render(<PaperManagement detail={{ kind: "document", id: "ms-1" }} subjectId={subject.id} subjects={[subject]} />);
    const documentDialog = await visibleModal("资料详情");
    expect(within(documentDialog).getByRole("heading", { name: "MS-202406-P1.pdf", level: 2 })).toBeInTheDocument();
    const detail = documentDialog.querySelector<HTMLElement>(".paper-document-detail");
    expect(detail).toBeInTheDocument();
    expect(within(detail!).getAllByText("Mark Scheme")).toHaveLength(2);
    expect(within(detail!).getByText("已识别")).toBeInTheDocument();
    expect(within(detail!).getByText("已解析")).toBeInTheDocument();
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
    const { requests } = installServer([paper()], [source(), pendingScheme], 300);
    const onBackDocument = vi.fn();
    const user = userEvent.setup();
    render(<PaperManagement
      detail={{ kind: "document", id: "ms-1", parentPaperId: "unit-1" }}
      onBackDocument={onBackDocument}
      subjectId={subject.id}
      subjects={[subject]}
    />);
    const documentDialog = await visibleModal("资料详情");
    await user.click(within(documentDialog).getByRole("button", { name: "返回试卷详情" }));
    expect(onBackDocument).toHaveBeenCalledWith(subject.id, "unit-1");
    await user.click(within(documentDialog).getByRole("button", { name: "解析内容" }));
    expect(within(documentDialog).getByText("解析中")).toBeInTheDocument();
    await waitFor(() => expect(within(documentDialog).getByText("已解析")).toBeInTheDocument(), { timeout: 3000 });
    expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/corpus/convert"))).toBe(true);
    expect(within(documentDialog).queryByRole("button", { name: "解析内容" })).not.toBeInTheDocument();
  });

  test("moves a paper to trash, restores it, and only permanently deletes from trash", async () => {
    const { requests } = installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getByRole("button", { name: "编辑 June paper" }));
    expect(screen.queryByRole("combobox", { name: "Question Paper" })).not.toBeInTheDocument();
    const editorFiles = document.querySelectorAll<HTMLElement>(".paper-editor-current-file");
    expect(editorFiles).toHaveLength(3);
    expect(Array.from(editorFiles).every((file) => within(file).getByText("已解析"))).toBe(true);
    expect(screen.getAllByRole("button", { name: "更新文件" })).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "修改试卷名称" }));
    const name = screen.getByLabelText("试卷名称");
    await user.clear(name);
    await user.type(name, "Mock exam A");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    expect(await screen.findByText("Mock exam A")).toBeVisible();
    const updateRequest = requests.find((request) => request.method === "PATCH" && request.url.includes("/paper-units/"));
    expect(updateRequest).toBeDefined();
    await expect(updateRequest!.clone().json()).resolves.toEqual({ document_ids: null, display_name: "Mock exam A" });
    await user.click(screen.getByRole("button", { name: "删除 Mock exam A" }));
    await user.click(screen.getByRole("button", { name: "移入回收站" }));
    await waitFor(() => expect(screen.queryByText("Mock exam A")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "打开试卷回收站" }));
    const trash = await visibleModal("试卷回收站");
    expect(within(trash).getByText("Mock exam A")).toBeInTheDocument();
    expect(within(trash).getByText(/3 份资料 · 3 条作答/)).toBeInTheDocument();
    await user.click(within(trash).getByRole("button", { name: "恢复" }));
    expect(await screen.findByText("Mock exam A")).toBeVisible();
    expect(within(trash).getByText("回收站为空")).toBeInTheDocument();
    fireEvent.click(trash.querySelector(".ant-modal-close")!);

    await user.click(screen.getByRole("button", { name: "删除 Mock exam A" }));
    await user.click(screen.getByRole("button", { name: "移入回收站" }));
    await user.click(screen.getByRole("button", { name: "打开试卷回收站" }));
    const reopenedTrash = await visibleModal("试卷回收站");
    await user.click(within(reopenedTrash).getByRole("button", { name: "永久删除" }));
    const permanentDialog = screen.getByRole("alertdialog", { name: /永久删除/ });
    expect(permanentDialog).toHaveTextContent("3 份原始资料、3 条作答");
    await user.click(within(permanentDialog).getByRole("button", { name: "永久删除" }));
    await waitFor(() => expect(within(reopenedTrash).getByText("回收站为空")).toBeInTheDocument());
    expect(requests.some((request) => request.method === "PATCH" && request.url.includes("/paper-units/"))).toBe(true);
    expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/restore"))).toBe(true);
    expect(requests.some((request) => request.method === "DELETE" && request.url.endsWith("/permanent"))).toBe(true);
  });

  test("creates a paper with explicit Mark Scheme and Source Booklet membership", async () => {
    const { requests } = installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getAllByRole("button", { name: "添加试卷" })[0]);
    expect(screen.queryByLabelText("试卷名称")).not.toBeInTheDocument();
    expect(document.querySelector(".paper-editor-material-grid")).toBeInTheDocument();
    expect(document.querySelectorAll(".paper-editor-material-title-icon")).toHaveLength(3);
    expect(screen.getAllByText("资料库")).toHaveLength(3);
    const markSchemeCard = screen.getByText("官方评分标准 · 可选").closest<HTMLElement>(".paper-editor-material");
    expect(markSchemeCard).toBeInTheDocument();
    await user.click(within(markSchemeCard!).getByText("上传文件"));
    expect(within(markSchemeCard!).getByLabelText("上传 Mark Scheme（可选）")).toBeInTheDocument();
    await user.click(within(markSchemeCard!).getByText("资料库"));
    expect(within(markSchemeCard!).getByRole("combobox", { name: "Mark Scheme（可选）" })).toBeInTheDocument();
    async function selectLibraryMaterial(label: string, optionName: RegExp) {
      fireEvent.mouseDown(screen.getByRole("combobox", { name: label }));
      let option: HTMLElement | null = null;
      await waitFor(() => {
        option = Array.from(document.querySelectorAll<HTMLElement>(".paper-editor-library-option"))
          .find((item) => optionName.test(item.textContent ?? ""))?.closest<HTMLElement>(".ant-select-item-option") ?? null;
        expect(option).toBeInTheDocument();
      });
      fireEvent.click(option!);
    }
    await selectLibraryMaterial("Question Paper", /June paper/);
    await selectLibraryMaterial("Mark Scheme（可选）", /MS-202406-P1.pdf/);
    await selectLibraryMaterial("Source Booklet（可选）", /Insert-202406-P1.pdf/);
    expect(screen.getByRole("button", { name: "保存试卷" })).toBeEnabled();
    const editor = await visibleModal("添加试卷");
    expect(editor.querySelector(".paper-editor-name-value strong")).toHaveTextContent("June paper");
    await user.click(within(editor).getByRole("button", { name: "修改试卷名称" }));
    const name = within(editor).getByLabelText("试卷名称");
    await user.clear(name);
    await user.type(name, "June mock");
    await user.click(screen.getByRole("button", { name: "保存试卷" }));
    await waitFor(() => {
      expect(requests.some((request) => request.method === "POST" && request.url.endsWith("/paper-units"))).toBe(true);
    });
    const createRequest = requests.find((request) => request.method === "POST" && request.url.endsWith("/paper-units"));
    expect(createRequest).toBeDefined();
    await expect(createRequest!.clone().json()).resolves.toMatchObject({ document_ids: ["qp-1", "ms-1", "insert-1"], display_name: "June mock" });
    expect(await screen.findByText("June mock", {}, { timeout: 3000 })).toBeVisible();
  });

  test("collapses the drop zone and previews a staged Markdown file before saving", async () => {
    installServer();
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getAllByRole("button", { name: "添加试卷" })[0]);
    const markSchemeCard = screen.getByText("官方评分标准 · 可选").closest<HTMLElement>(".paper-editor-material");
    expect(markSchemeCard).toBeInTheDocument();
    await user.click(within(markSchemeCard!).getByText("上传文件"));
    const uploadInput = markSchemeCard!.querySelector<HTMLInputElement>('input[type="file"]');
    expect(uploadInput).toBeInTheDocument();
    await user.upload(uploadInput!, new File(["# Local preview\n\nScoring guidance."], "local-mark-scheme.md", { type: "text/markdown" }));

    expect(within(markSchemeCard!).queryByText("点击或拖拽文件到这里")).not.toBeInTheDocument();
    expect(within(markSchemeCard!).getByText("local-mark-scheme.md")).toBeInTheDocument();
    expect(screen.queryByText("我确认有权在本系统中使用以上考试资料。")).not.toBeInTheDocument();
    await user.click(within(markSchemeCard!).getByRole("button", { name: "预览" }));
    const preview = await visibleModal("文件预览 · local-mark-scheme.md");
    expect(within(preview).getByText(/Local preview/)).toHaveTextContent("Scoring guidance.");
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

  test("queues additional paper materials while one document is being parsed", async () => {
    const pendingQuestionPaper = source({ status: "discovered" });
    const pendingScheme = source({ id: "ms-1", filename: "MS-202406-P1.pdf", display_name: null, source_type: "mark_scheme", checksum: "ms", status: "discovered" });
    const pendingPaper = paper({
      documents: paper().documents.map((item) => item.id === "qp-1" || item.id === "ms-1" ? { ...item, status: "discovered" } : item),
    });
    const { requests } = installServer(
      [pendingPaper],
      [pendingQuestionPaper, pendingScheme, source({ id: "insert-1", filename: "Insert-202406-P1.pdf", display_name: null, source_type: "insert", checksum: "insert" })],
      1000,
    );
    const user = userEvent.setup();
    render(<PaperManagement subjectId={subject.id} subjects={[subject]} />);
    await screen.findByText("June paper");
    await user.click(screen.getByRole("button", { name: "编辑 June paper" }));

    const questionCard = screen.getByText("June paper", { selector: ".paper-editor-current-file strong" }).closest<HTMLElement>(".paper-editor-material");
    const schemeCard = screen.getByText("MS-202406-P1.pdf").closest<HTMLElement>(".paper-editor-material");
    expect(questionCard).not.toBeNull();
    expect(schemeCard).not.toBeNull();
    await user.click(within(questionCard!).getByRole("button", { name: "解析" }));
    expect(within(questionCard!).getByText("解析中", { selector: ".ant-tag" })).toBeInTheDocument();
    await user.click(within(schemeCard!).getByRole("button", { name: "解析" }));

    expect(within(schemeCard!).getByRole("button", { name: "排队中" })).toBeDisabled();
    expect(within(schemeCard!).getByText("排队中", { selector: ".ant-tag" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("已解析").length).toBeGreaterThanOrEqual(3), { timeout: 4000 });

    const conversionRequests = requests.filter((request) => request.method === "POST" && request.url.endsWith("/corpus/convert"));
    expect(conversionRequests).toHaveLength(2);
    const conversionBodies = await Promise.all(conversionRequests.map((request) => request.json() as Promise<{ document_ids: string[] }>));
    expect(conversionBodies.map((body) => body.document_ids)).toEqual([["qp-1"], ["ms-1"]]);
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
    await user.click(await screen.findByRole("button", { name: "更多试卷操作" }));
    await user.click(await screen.findByRole("menuitem", { name: "导入外部答卷" }));
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
