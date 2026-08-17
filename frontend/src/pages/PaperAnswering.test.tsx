import type { ReactElement } from "react";
import { fireEvent, render as testingLibraryRender, screen } from "@testing-library/react";
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

const subject = {
  id: "math",
  subject_code: "9660",
  title: "Mathematics",
  board_name: "OxfordAQA",
  answering_enabled: true,
  version: "1",
  digest: "digest",
  capability_profile_id: "math",
  generic_qa_enabled: true,
  answering_disabled_reason: null,
  active_graph_version_id: null,
  units: [],
  knowledge_bases: [],
} as SubjectPack;

beforeEach(() => {
  window.localStorage.clear();
  subscribeMock.mockReset();
});

describe("PaperAnswering", () => {
  test("accepts a supported paper through drag and drop", async () => {
    render(<PaperAnswering enabled subjects={[subject]} />);
    fireEvent.click(screen.getByRole("button", { name: "新建作答" }));
    fireEvent.click(screen.getByRole("button", { name: /Mathematics/ }));
    fireEvent.click(screen.getByRole("button", { name: "下一步" }));
    const dropZone = screen.getByText(/选择或拖入一份.*试卷/).closest("label");
    const paper = new File(["# Question 1"], "paper.md", { type: "text/markdown" });

    fireEvent.drop(dropZone!, { dataTransfer: { files: [paper] } });

    expect(screen.getByText("paper.md")).toBeInTheDocument();
  });

  test("presents completion as answer status instead of evidence status", async () => {
    const imageUrl = (
      "/api/v1/papers/jobs/job-1/question-images/"
      + `p0001-${"a".repeat(64)}.png`
    );
    const completedJob: PaperJobResult = {
      job_id: "job-1",
      filename: "paper.pdf",
      answer_mode: "generated",
      paper_unit_id: "paper-1",
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
    window.localStorage.setItem(`examtwin.paperJobId.${subject.id}`, completedJob.job_id);

    const onBack = vi.fn();
    render(<PaperAnswering enabled initialPaperUnitId="paper-1" onBack={onBack} subject={subject} />);

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
  });

  test("shows one calm processing state before questions are identified", async () => {
    const parsingJob: PaperJobResult = {
      job_id: "job-parsing",
      filename: "QP-202601-Economics-U4A-Level-AQA经济学-A-Level.pdf",
      display_name: "QP-202601-Economics-U4A-Level-AQA经济学-A-Level",
      answer_mode: "generated",
      paper_unit_id: "paper-1",
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
      <PaperAnswering embedded enabled initialJobId={parsingJob.job_id} initialPaperUnitId="paper-1" onBack={vi.fn()} subject={subject} />,
    );

    expect(await screen.findByText("正在识别试卷题目")).toBeInTheDocument();
    expect(screen.getByText("完成后将自动展示逐题结果，你可以关闭弹窗继续处理其他工作。")).toBeInTheDocument();
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
      source_integrity_status: "verified",
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
    window.localStorage.setItem(`examtwin.paperJobId.${subject.id}`, failedJob.job_id);

    render(<PaperAnswering enabled subject={subject} />);

    expect(await screen.findByText("解析中断 · 已完成 10 / 32 页")).toBeInTheDocument();
    expect(screen.getByText("任务在题目识别前中断")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "从失败步骤继续" })).toBeInTheDocument();
    expect(screen.queryByText("等待题目识别结果")).not.toBeInTheDocument();
  });
});
