import type { ReactElement } from "react";
import { render as testingLibraryRender, screen, waitFor } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { deletePaperJobs, listPaperJobs, replacePaperJob } from "../lib/api";
import type { PaperJobList, SubjectPack } from "../types";
import { DesignSystemProvider } from "./ui/DesignSystemProvider";
import { PaperJobHistory } from "./PaperJobHistory";

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

async function selectFilterOption(
  user: UserEvent,
  label: string,
  option: string,
) {
  await user.click(screen.getByRole("combobox", { name: label }));
  await user.click(await screen.findByText(option, { selector: ".ant-select-item-option-content" }));
}

async function selectRecordAction(
  user: UserEvent,
  recordName: string,
  action: string,
) {
  await user.click(await screen.findByRole(
    "button",
    { name: `更多作答记录操作：${recordName}` },
  ));
  await user.click(await screen.findByRole("menuitem", { name: action }));
}

vi.mock("../lib/api", () => ({
  deletePaperJobs: vi.fn(),
  listPaperJobs: vi.fn(),
  replacePaperJob: vi.fn(),
}));

const subject: SubjectPack = {
  id: "oxfordaqa-mathematics-9660",
  version: "1",
  digest: "test",
  subject_code: "9660",
  title: "Mathematics",
  board_name: "OxfordAQA",
  icon: "calculator",
  color: "#2F6FED",
  capability_profile_id: "oxfordaqa-mathematics-9660",
  generic_qa_enabled: true,
  answering_enabled: true,
  answering_disabled_reason: null,
  source_booklet_required: false,
  active_graph_version_id: null,
  knowledge_bases: [],
  units: [
    { code: "P1", title: "Pure Mathematics 1", strand: "Pure" },
    { code: "M1", title: "Mechanics 1", strand: "Mechanics" },
  ],
};
const economics: SubjectPack = {
  ...subject,
  id: "oxfordaqa-economics-9640",
  subject_code: "9640",
  title: "Economics",
  units: [],
};

const history: PaperJobList = {
  items: [
    {
      job_id: "job-1",
      filename: "QP-2026-P1.pdf",
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
      total_questions: 13,
      completed_questions: 13,
      failed_questions: 0,
      source_integrity_status: "verified",
      split_contract_version: "paper-question-split-v6",
      replacement_for_job_id: null,
      replaced_by_job_id: null,
      created_at: "2026-08-05T08:00:00+00:00",
      updated_at: "2026-08-05T08:30:00+00:00",
    },
  ],
  total: 1,
  limit: 10,
  offset: 0,
};

const listMock = vi.mocked(listPaperJobs);
const deleteMock = vi.mocked(deletePaperJobs);
const replaceMock = vi.mocked(replacePaperJob);

beforeEach(() => {
  vi.clearAllMocks();
  listMock.mockResolvedValue(history);
  deleteMock.mockResolvedValue({ deleted_count: 1 });
  replaceMock.mockResolvedValue({
    job_id: "replacement-job",
    status: "queued",
    stage: "queued",
  });
});


describe("PaperJobHistory", () => {
  test("clears selections and deletion confirmation when switching paper scope", async () => {
    const user = userEvent.setup();
    const props = { currentJobId: null, onDeleted: vi.fn(), onOpen: vi.fn(), refreshKey: 0, subject };
    const view = render(<PaperJobHistory {...props} paperUnitId="paper-A" />);
    await screen.findByText("QP-2026-P1.pdf");
    await user.click(screen.getByRole("button", { name: "进入批量选择" }));
    await user.click(screen.getByRole("checkbox", { name: "选择记录 QP-2026-P1.pdf" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));
    expect(screen.getByRole("alertdialog", { name: "确认批量删除" })).toBeInTheDocument();
    let resolveNext!: (value: PaperJobList) => void;
    listMock.mockReturnValueOnce(new Promise((resolve) => { resolveNext = resolve; }));
    view.rerender(<PaperJobHistory {...props} paperUnitId="paper-B" />);
    expect(screen.queryByText("QP-2026-P1.pdf")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("alertdialog", { name: "确认批量删除" })).not.toBeInTheDocument());
    expect(screen.queryByRole("region", { name: "批量删除操作" })).not.toBeInTheDocument();
    resolveNext({ ...history, items: [{ ...history.items[0], job_id: "job-B", filename: "paper-B.pdf", paper_unit_id: "paper-B" }] });
    await screen.findByText("paper-B.pdf");
    expect(deleteMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "进入批量选择" }));
    await user.click(screen.getByRole("checkbox", { name: "选择记录 paper-B.pdf" }));
    await user.click(screen.getByRole("button", { name: "批量删除" }));
    await user.click(screen.getByRole("button", { name: "删除 1 条记录" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(subject.id, ["job-B"]));
  });

  test("loads records, applies filters and opens the selected result", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onSubjectChange = vi.fn();
    render(
      <PaperJobHistory
        currentJobId={null}
        onDeleted={vi.fn()}
        onOpen={onOpen}
        onSubjectChange={onSubjectChange}
        refreshKey={0}
        subject={subject}
        subjects={[subject, economics]}
      />,
    );

    expect(await screen.findByText("QP-2026-P1.pdf")).toBeInTheDocument();
    const standaloneShell = screen.getByRole("heading", { name: "全部作答记录" }).closest("article");
    expect(standaloneShell).toHaveClass("panel", "paper-history");
    expect(standaloneShell).not.toHaveClass("paper-history-embedded");
    expect(screen.getByRole("button", { name: "刷新试卷作答记录" })).toBeInTheDocument();
    expect(screen.getByText("处理完成", { selector: ".paper-history-status" }))
      .toBeInTheDocument();
    expect(screen.getByText("13/13 题已处理")).toBeInTheDocument();
    await selectFilterOption(
      user,
      "按科目筛选",
      `${economics.title} · ${economics.subject_code}`,
    );
    await waitFor(() => expect(onSubjectChange).toHaveBeenCalledWith(economics.id));

    await user.type(screen.getByRole("searchbox", { name: "按名称或文件名筛选" }), "2026");
    await selectFilterOption(user, "按状态筛选", "处理完成");
    await selectFilterOption(user, "按来源筛选", "外部答卷");
    await selectFilterOption(user, "按单元筛选", "P1");
    await selectFilterOption(user, "按时间筛选", "最近 30 天");

    await waitFor(() => {
      expect(listMock).toHaveBeenLastCalledWith(
        subject.id,
        expect.objectContaining({
          status: "completed",
          answerMode: "uploaded",
          unitCode: "P1",
          createdAfter: expect.any(String),
          query: "2026",
          limit: 10,
          offset: 0,
        }),
      );
    });
    await user.click(screen.getByRole("button", { name: "重置" }));
    await waitFor(() => {
      expect(listMock).toHaveBeenLastCalledWith(
        subject.id,
        expect.objectContaining({
          status: undefined,
          answerMode: undefined,
          unitCode: undefined,
          query: undefined,
          createdAfter: undefined,
          limit: 10,
          offset: 0,
        }),
      );
    });
    await user.click(screen.getByRole("button", { name: "查看" }));
    expect(onOpen).toHaveBeenCalledWith("job-1", null);
  });

  test("requires dialog confirmation before deleting a terminal record", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    render(
      <PaperJobHistory
        currentJobId="job-1"
        onDeleted={onDeleted}
        onOpen={vi.fn()}
        refreshKey={0}
        subject={subject}
      />,
    );

    await screen.findByText("QP-2026-P1.pdf");
    await selectRecordAction(user, "QP-2026-P1.pdf", "删除记录");
    expect(screen.getByRole("alertdialog", { name: "确认删除作答记录" })).toBeInTheDocument();
    expect(screen.getByText(/将永久删除“QP-2026-P1\.pdf”的作答结果、关联评分、复核记录和作答文件/)).toBeInTheDocument();
    expect(deleteMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "删除作答记录" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(subject.id, ["job-1"]));
    expect(onDeleted).toHaveBeenCalledWith("job-1");
  });

  test("allows an unclaimed active task to be cancelled and deleted", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    listMock.mockResolvedValue({
      ...history,
      items: [{
        ...history.items[0],
        job_id: "queued-job",
        filename: "stuck-paper.pdf",
        status: "queued",
        stage: "queued",
        total_questions: 0,
        completed_questions: 0,
      }],
    });
    render(
      <PaperJobHistory
        currentJobId="queued-job"
        onDeleted={onDeleted}
        onOpen={vi.fn()}
        refreshKey={0}
        subject={subject}
      />,
    );

    await selectRecordAction(user, "stuck-paper.pdf", "取消并删除任务");
    expect(screen.getByRole("alertdialog", { name: "确认删除作答记录" })).toBeInTheDocument();
    expect(screen.getByText(/将永久删除“stuck-paper\.pdf”的作答结果、关联评分、复核记录和作答文件/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "删除作答记录" }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(subject.id, ["queued-job"]));
    expect(onDeleted).toHaveBeenCalledWith("queued-job");
  });

  test("selects every deletable row on the page and confirms one bulk deletion", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    listMock.mockResolvedValue({
      ...history,
      items: [
        history.items[0],
        {
          ...history.items[0],
          job_id: "job-2",
          filename: "QP-2026-P2.pdf",
          unit_code: "P2",
        },
        {
          ...history.items[0],
          job_id: "job-replaced",
          filename: "QP-2026-replaced.pdf",
          replaced_by_job_id: "job-2",
        },
      ],
      total: 3,
    });
    deleteMock.mockResolvedValue({ deleted_count: 2 });
    render(
      <PaperJobHistory
        currentJobId="job-2"
        onDeleted={onDeleted}
        onOpen={vi.fn()}
        refreshKey={0}
        subject={subject}
      />,
    );

    await screen.findByText("QP-2026-P2.pdf");
    await user.click(screen.getByRole("button", { name: "进入批量选择" }));
    const masterCheckbox = screen.getByRole("checkbox", { name: "全选当前页可删除记录" });
    const firstCheckbox = screen.getByRole("checkbox", { name: "选择记录 QP-2026-P1.pdf" });
    const secondCheckbox = screen.getByRole("checkbox", { name: "选择记录 QP-2026-P2.pdf" });
    const disabledCheckbox = screen.getByRole("checkbox", { name: "选择记录 QP-2026-replaced.pdf" });
    expect(disabledCheckbox).toBeDisabled();

    await user.click(firstCheckbox);
    expect(masterCheckbox).toBePartiallyChecked();
    await user.click(masterCheckbox);
    expect(masterCheckbox).toBeChecked();
    expect(firstCheckbox).toBeChecked();
    expect(secondCheckbox).toBeChecked();
    expect(disabledCheckbox).not.toBeChecked();
    expect(screen.getByText("已选择 2 条")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "批量删除" }));
    expect(screen.getByRole("alertdialog", { name: "确认批量删除" })).toBeInTheDocument();
    expect(screen.getByText(/将永久删除选中的 2 条作答记录，以及关联评分、复核记录和作答文件/)).toBeInTheDocument();
    expect(deleteMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "删除 2 条记录" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(subject.id, ["job-1", "job-2"]));
    expect(onDeleted).toHaveBeenCalledWith("job-2");
  });

  test("marks legacy results untrusted and creates an auditable replacement", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    listMock.mockResolvedValue({
      ...history,
      items: [{
        ...history.items[0],
        source_integrity_status: "legacy_unverified",
        split_contract_version: null,
      }],
    });
    render(
      <PaperJobHistory
        currentJobId={null}
        onDeleted={vi.fn()}
        onOpen={onOpen}
        refreshKey={0}
        subject={subject}
      />,
    );

    expect(await screen.findByText("旧版未验证结果 · 不应作为可信答案"))
      .toBeInTheDocument();
    await selectRecordAction(user, "QP-2026-P1.pdf", "修复并重跑");
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith(subject.id, "job-1"));
    expect(onOpen).toHaveBeenCalledWith("replacement-job", null);
  });

  test("groups AI and uploaded answers under one paper with source labels", async () => {
    listMock.mockResolvedValue({
      ...history,
      items: [
        { ...history.items[0], answer_mode: "generated", paper_unit_id: "paper-1" },
        {
          ...history.items[0],
          job_id: "job-uploaded",
          filename: "student-answer.pdf",
          answer_mode: "uploaded",
          paper_unit_id: "paper-1",
        },
      ],
      total: 2,
    });
    render(
      <PaperJobHistory
        currentJobId={null}
        embedded
        onDeleted={vi.fn()}
        onOpen={vi.fn()}
        paperUnitId="paper-1"
        refreshKey={0}
        subject={subject}
      />,
    );

    const generatedMode = await screen.findByText("AI 作答", { selector: ".paper-history-mode" });
    expect(generatedMode).toBeInTheDocument();
    expect(screen.getByText("外部答卷", { selector: ".paper-history-mode" })).toBeInTheDocument();
    const embeddedShell = generatedMode.closest("article");
    expect(embeddedShell).toHaveClass("paper-history", "paper-history-embedded");
    expect(embeddedShell).not.toHaveClass("panel");
    expect(screen.queryByRole("heading", { name: "全部作答记录" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新试卷作答记录" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "按来源筛选" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "按科目筛选" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "按单元筛选" })).not.toBeInTheDocument();
    await waitFor(() => expect(listMock).toHaveBeenCalledWith(
      subject.id,
      expect.objectContaining({ paperUnitId: "paper-1" }),
    ));
  });

  test("starts grading from the exact completed answer record", async () => {
    const user = userEvent.setup();
    const onGrade = vi.fn();
    render(
      <PaperJobHistory
        currentJobId={null}
        embedded
        onDeleted={vi.fn()}
        onGrade={onGrade}
        onOpen={vi.fn()}
        paperUnitId="paper-1"
        refreshKey={0}
        subject={subject}
      />,
    );

    await selectRecordAction(user, "QP-2026-P1.pdf", "评分");
    expect(onGrade).toHaveBeenCalledWith("job-1", null);
  });

  test("changes page size and loads the next page with the matching offset", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue({ ...history, total: 21 });
    render(
      <PaperJobHistory
        currentJobId={null}
        onDeleted={vi.fn()}
        onOpen={vi.fn()}
        refreshKey={0}
        subject={subject}
      />,
    );

    await screen.findByText("1 / 3");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "每页显示条数" }),
      "20",
    );
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        subject.id,
        expect.objectContaining({ limit: 20, offset: 0 }),
      ),
    );
    expect(screen.getByText("1 / 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页作答记录" }));
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        subject.id,
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });
});
