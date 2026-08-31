import type { ReactElement } from "react";
import { fireEvent, render as testingLibraryRender, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { DesignSystemProvider } from "../components/ui/DesignSystemProvider";

import { subscribeTaskSnapshots } from "../lib/task-events";
import type { PaperJobResult, SubjectPack } from "../types";
import { PaperAnswering } from "./PaperAnswering";

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

vi.mock("../lib/task-events", () => ({
  subscribeTaskSnapshots: vi.fn(),
}));

const subscribeMock = vi.mocked(subscribeTaskSnapshots);

const subject: SubjectPack = {
  id: "math",
  subject_code: "9660",
  title: "Mathematics",
  board_name: "OxfordAQA",
  icon: "calculator",
  color: "#2F6FED",
  answering_enabled: true,
  version: "1",
  digest: "digest",
  capability_profile_id: "math",
  generic_qa_enabled: true,
  answering_disabled_reason: null,
  source_booklet_required: false,
  active_graph_version_id: null,
  units: [],
  knowledge_bases: [],
};

beforeEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  subscribeMock.mockReset();
});

describe("PaperAnswering", () => {
  test("creates a job through the navigation callback without persisting identity", async () => {
    const onOpenJob = vi.fn();
    window.localStorage.setItem("examtwin.paperJobId.math", "stale-job");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/papers/answer")) {
        return new Response(JSON.stringify({ job_id: "created-job", status: "queued", stage: "queued" }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }), {
        headers: { "Content-Type": "application/json" },
      });
    }));
    render(<PaperAnswering enabled onOpenJob={onOpenJob} subjects={[subject]} />);
    fireEvent.click(screen.getByRole("button", { name: "新建作答" }));
    fireEvent.click(screen.getByRole("button", { name: /Mathematics/ }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    const dropZone = screen.getByText(/选择或拖入一份.*试卷/).closest("label");
    const paper = new File(["# Question 1"], "paper.md", { type: "text/markdown" });

    fireEvent.drop(dropZone!, { dataTransfer: { files: [paper] } });
    fireEvent.click(screen.getByRole("button", { name: "开始整卷作答" }));

    await waitFor(() => expect(onOpenJob).toHaveBeenCalledWith("created-job"));
    expect(window.localStorage.getItem("examtwin.paperJobId.math")).toBe("stale-job");
  });

  test("presents completion as answer status instead of evidence status", async () => {
    const imageUrl = (
      "/api/v1/papers/jobs/job-1/question-images/"
      + `p0001-${"a".repeat(64)}.png`
    );
    const completedJob: PaperJobResult = {
      job_id: "job-1",
      filename: "paper.pdf",
      display_name: null,
      answer_mode: "generated",
      paper_unit_id: "paper-1",
      pair_key: null,
      question_paper_document_id: null,
      source_booklet_document_id: null,
      source_booklet_checksum: null,
      source_booklet_filename: null,
      subject_pack_id: "oxfordaqa-mathematics-9660",
      subject_code: "9660",
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "completed",
      stage: "completed",
      total_pages: 1,
      parsed_pages: 1,
      total_questions: 1,
      completed_questions: 1,
      failed_questions: 0,
      created_at: "2026-08-05T00:00:00Z",
      updated_at: "2026-08-05T00:00:00Z",
      chunks: [],
      source_integrity_status: "verified",
      split_contract_version: "paper-question-split-v6",
      split_source_digest: "source-digest",
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      questions: [{
        position: 0,
        number: "1",
        question_markdown: `Solve x + 1 = 2.\n\n![Equation diagram](${imageUrl})`,
        answer_markdown: "### (a)\n\nx = 1\n\n### (b)\n\nCheck by substitution.",
        diagrams: [{
          artifact_id: "artifact-1",
          answer_anchor: "(a)",
          answer_order: 1,
          caption: "",
          elements: [{
            arrow_end: false,
            arrow_start: false,
            cx: null,
            cy: null,
            d: null,
            dashed: false,
            emphasis: false,
            fill: "none",
            kind: "point",
            points: [],
            r: null,
            rx: null,
            ry: null,
            text: null,
            tone: "default",
            x: 1,
            x1: null,
            x2: null,
            y: 1,
            y1: null,
            y2: null,
          }],
          legend: [],
          source: null,
          title: "Part A graph",
          tool_name: "math_plot",
          view_box: [0, 0, 600, 360],
        }],
        images: [],
        citations: [],
        knowledge_points: [],
        confidence: 0.9,
        grounded: true,
        warnings: [],
        attempts: 1,
        source_pages: [1],
        source_warnings: [],
        source_kind: "primary",
        source_digest: "source-digest",
        requires_visual_context: false,
        answer_requirements: [],
        agent_steps: [],
        status: "completed",
        total_marks: 1,
        error: null,
      }],
      error: null,
    };
    subscribeMock.mockImplementation((options) => {
      options.onSnapshot(completedJob);
      options.onState("live");
      return () => undefined;
    });
    window.localStorage.setItem(`examtwin.paperJobId.${subject.id}`, "stale-job");

    const onBack = vi.fn();
    render(<PaperAnswering enabled initialJobId={completedJob.job_id} initialPaperUnitId="paper-1" onBack={onBack} onOpenJob={vi.fn()} subject={subject} />);

    expect(await screen.findByText("已作答")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI 作答" })).toBeInTheDocument();
    expect(screen.getByText("AI 作答", { selector: ".paper-answer-origin" })).toBeInTheDocument();
    expect(screen.queryByLabelText("作答流程")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "返回试卷详情" })[0]);
    expect(onBack).toHaveBeenCalledWith("paper-1");
    expect(screen.getByText("Q1 · 已作答")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Equation diagram" })).toHaveAttribute(
      "src",
      `${imageUrl}?subject=${subject.id}`,
    );
    fireEvent.click(screen.getByRole("button", { name: "收起题目" }));
    expect(screen.queryByRole("img", { name: "Equation diagram" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开题目" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "展开题目" }));
    expect(screen.getByRole("img", { name: "Equation diagram" })).toBeInTheDocument();
    const answer = screen.getByRole("heading", { name: "证据化解答" }).closest("section")!;
    const answerText = answer.textContent ?? "";
    expect(answerText.indexOf("x = 1")).toBeLessThan(answerText.indexOf("Part A graph"));
    expect(answerText.indexOf("Part A graph")).toBeLessThan(
      answerText.indexOf("Check by substitution."),
    );
    expect(window.localStorage.getItem(`examtwin.paperJobId.${subject.id}`)).toBe("stale-job");
  });

  test("shows one calm processing state before questions are identified", async () => {
    const parsingJob: PaperJobResult = {
      job_id: "job-parsing",
      filename: "QP-202601-Economics-U4A-Level-AQA经济学-A-Level.pdf",
      display_name: "QP-202601-Economics-U4A-Level-AQA经济学-A-Level",
      answer_mode: "generated",
      paper_unit_id: "paper-1",
      pair_key: null,
      question_paper_document_id: null,
      source_booklet_document_id: null,
      source_booklet_checksum: null,
      subject_pack_id: subject.id,
      subject_code: subject.subject_code,
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "U4",
      status: "parsing",
      stage: "parsing",
      total_pages: 28,
      parsed_pages: 0,
      total_questions: 0,
      completed_questions: 0,
      failed_questions: 0,
      created_at: "2026-08-13T01:44:16Z",
      updated_at: "2026-08-13T01:44:16Z",
      chunks: [],
      source_integrity_status: "pending",
      split_contract_version: null,
      split_source_digest: null,
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      source_booklet_filename: "IN-202601-Economics-U4A-Level-AQA经济学-9640.pdf",
      questions: [],
      error: null,
    };
    subscribeMock.mockImplementation((options) => {
      options.onSnapshot(parsingJob);
      options.onState("live");
      return () => undefined;
    });

    const { container } = render(
      <PaperAnswering embedded enabled initialJobId={parsingJob.job_id} initialPaperUnitId="paper-1" onBack={vi.fn()} onOpenJob={vi.fn()} subject={subject} />,
    );

    expect(await screen.findByText("正在识别试卷题目")).toBeInTheDocument();
    expect(screen.getByText("完成后将自动展示逐题结果；任务会继续在后台处理。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回作答记录" })).toBeInTheDocument();
    expect(screen.getByText("实时进度已连接", { exact: false })).toBeInTheDocument();
    expect(container.querySelectorAll(".paper-processing-empty")).toHaveLength(1);
    expect(container.querySelector(".question-nav")).not.toBeInTheDocument();
    expect(container.querySelector(".paper-answer")).not.toBeInTheDocument();
    expect(screen.queryByText("解析完成后将在这里逐题出现。")).not.toBeInTheDocument();
    expect(screen.queryByText("等待题目识别结果")).not.toBeInTheDocument();
  });

  test("presents a recoverable parsing failure without an indefinite waiting workspace", async () => {
    const failedJob: PaperJobResult = {
      job_id: "job-failed",
      filename: "paper.pdf",
      display_name: null,
      answer_mode: "generated",
      pair_key: null,
      paper_unit_id: null,
      question_paper_document_id: null,
      source_booklet_document_id: null,
      source_booklet_checksum: null,
      source_booklet_filename: null,
      subject_pack_id: "oxfordaqa-mathematics-9660",
      subject_code: "9660",
      knowledge_base_version_ids: [],
      graph_version_id: null,
      unit_code: "P2",
      status: "failed",
      stage: "parsing",
      total_pages: 32,
      parsed_pages: 10,
      total_questions: 0,
      completed_questions: 0,
      failed_questions: 0,
      created_at: "2026-08-11T01:44:16Z",
      updated_at: "2026-08-11T01:45:45Z",
      chunks: [{
        chunk_index: 2,
        page_start: 11,
        page_end: 15,
        status: "failed",
        attempts: 1,
        error: "ValueError: MinerU 题目图片缺少物理页位置",
      }],
      source_integrity_status: "legacy_unverified",
      split_contract_version: null,
      split_source_digest: null,
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      questions: [],
      error: "ValueError: MinerU 题目图片缺少物理页位置",
    };
    subscribeMock.mockImplementation((options) => {
      options.onSnapshot(failedJob);
      options.onState("idle");
      return () => undefined;
    });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/replace")) {
        return new Response(JSON.stringify({ job_id: "replacement-job", status: "queued", stage: "queued" }), {
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }), {
        headers: { "Content-Type": "application/json" },
      });
    }));
    const onOpenJob = vi.fn();
    const onOpenPaper = vi.fn();
    window.localStorage.setItem(`examtwin.paperJobId.${subject.id}`, "stale-job");

    render(
      <PaperAnswering
        enabled
        initialJobId={failedJob.job_id}
        initialPaperUnitId="paper-1"
        onBack={vi.fn()}
        onOpenJob={onOpenJob}
        onOpenPaper={onOpenPaper}
        subject={subject}
      />,
    );

    expect(await screen.findByText("解析中断 · 已完成 10 / 32 页")).toBeInTheDocument();
    expect(screen.getByText("任务在题目识别前中断")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "从失败步骤继续" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "上传另一份试卷" }));
    expect(onOpenPaper).toHaveBeenCalledWith("paper-1");
    expect(screen.queryByText("等待题目识别结果")).not.toBeInTheDocument();
    expect(window.localStorage.getItem(`examtwin.paperJobId.${subject.id}`)).toBe("stale-job");
    fireEvent.click(screen.getByRole("button", { name: "修复并重跑" }));
    await waitFor(() => expect(onOpenJob).toHaveBeenCalledWith("replacement-job", "paper-1"));
  });

  test("uses prop changes as the only source of active job identity", async () => {
    window.localStorage.setItem(`examtwin.paperJobId.${subject.id}`, "stale-job");
    subscribeMock.mockImplementation(() => () => undefined);
    const onOpenJob = vi.fn();
    const { rerender } = render(
      <PaperAnswering enabled initialJobId="job-from-url-1" onOpenJob={onOpenJob} subject={subject} />,
    );

    await waitFor(() => expect(subscribeMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: "/papers/jobs/job-from-url-1/events" }),
    ));
    rerender(
      <PaperAnswering enabled initialJobId="job-from-url-2" onOpenJob={onOpenJob} subject={subject} />,
    );

    await waitFor(() => expect(subscribeMock).toHaveBeenCalledWith(
      expect.objectContaining({ path: "/papers/jobs/job-from-url-2/events" }),
    ));
    expect(window.localStorage.getItem(`examtwin.paperJobId.${subject.id}`)).toBe("stale-job");
  });

  test("loads routed history when new answering is disabled", async () => {
    subscribeMock.mockImplementation(() => () => undefined);
    const disabledSubject = {
      ...subject,
      answering_enabled: false,
      answering_disabled_reason: "暂不允许新建 AI 作答",
    };

    render(
      <PaperAnswering
        enabled={false}
        initialJobId="existing-uploaded-job"
        initialPaperUnitId="paper-1"
        onBack={vi.fn()}
        onOpenJob={vi.fn()}
        subject={disabledSubject}
      />,
    );

    await waitFor(() => expect(subscribeMock).toHaveBeenCalledWith(
      expect.objectContaining({
        path: "/papers/jobs/existing-uploaded-job/events",
        subjectId: disabledSubject.id,
      }),
    ));
  });

  test("uses the embedded paper-scoped history shell before a routed job snapshot arrives", async () => {
    const requests: Request[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : new Request(input, init);
      requests.push(request);
      return new Response(
        JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }),
        { headers: { "Content-Type": "application/json" } },
      );
    }));

    render(
      <PaperAnswering
        embedded
        enabled
        initialPaperUnitId="paper-1"
        initialSubjectId={subject.id}
        onOpenJob={vi.fn()}
        subjects={[subject]}
      />,
    );

    const emptyState = await screen.findByText("还没有作答记录");
    const historyShell = emptyState.closest("article");
    expect(historyShell).toHaveClass("paper-history", "paper-history-embedded");
    expect(historyShell).not.toHaveClass("panel");
    expect(screen.queryByRole("heading", { name: "全部作答记录" })).not.toBeInTheDocument();
    await waitFor(() => expect(requests.some((request) => (
      new URL(request.url).searchParams.get("paper_unit_id") === "paper-1"
    ))).toBe(true));
  });
});
