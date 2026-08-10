import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { deletePaperJobs, listPaperJobs, replacePaperJob } from "../lib/api";
import type { PaperJobList, SubjectPack } from "../types";
import { PaperJobHistory } from "./PaperJobHistory";

vi.mock("../lib/api", () => ({
  deletePaperJobs: vi.fn(),
  listPaperJobs: vi.fn(),
  replacePaperJob: vi.fn(),
}));

const subject = {
  id: "oxfordaqa-mathematics-9660",
  subject_code: "9660",
  units: [
    { code: "P1", title: "Pure Mathematics 1" },
    { code: "M1", title: "Mechanics 1" },
  ],
} as SubjectPack;

const history: PaperJobList = {
  items: [
    {
      job_id: "job-1",
      filename: "QP-2026-P1.pdf",
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
  test("loads records, applies filters and opens the selected result", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <PaperJobHistory
        currentJobId={null}
        onDeleted={vi.fn()}
        onOpen={onOpen}
        refreshKey={0}
        subject={subject}
      />,
    );

    expect(await screen.findByText("QP-2026-P1.pdf")).toBeInTheDocument();
    expect(screen.getByText("处理完成", { selector: ".paper-history-status" }))
      .toBeInTheDocument();
    expect(screen.getByText("13/13 题已处理")).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox", { name: "按文件名筛选" }), "2026");
    await user.selectOptions(screen.getByRole("combobox", { name: "按状态筛选" }), "completed");
    await user.selectOptions(screen.getByRole("combobox", { name: "按单元筛选" }), "P1");
    await user.click(screen.getByRole("button", { name: "筛选" }));

    await waitFor(() => {
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          status: "completed",
          unitCode: "P1",
          query: "2026",
          limit: 10,
          offset: 0,
        }),
      );
    });
    await user.click(screen.getByRole("button", { name: "查看" }));
    expect(onOpen).toHaveBeenCalledWith("job-1");
  });

  test("requires inline confirmation before deleting a terminal record", async () => {
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
    await user.click(screen.getByRole("button", { name: "删除记录 QP-2026-P1.pdf" }));
    expect(screen.getByText("确认删除？")).toBeInTheDocument();
    expect(deleteMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "确认删除" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(["job-1"]));
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

    await user.click(await screen.findByRole(
      "button",
      { name: "删除记录 stuck-paper.pdf" },
    ));
    expect(screen.getByText("确认取消并删除？")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(["queued-job"]));
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
      ],
      total: 2,
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
    await user.click(screen.getByRole("checkbox", { name: "全选当前页可删除记录" }));
    expect(screen.getByRole("checkbox", { name: "选择记录 QP-2026-P1.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "选择记录 QP-2026-P2.pdf" })).toBeChecked();
    expect(screen.getByText("已选择 2 条")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "批量删除" }));
    expect(screen.getByText("确认删除选中的 2 条记录？")).toBeInTheDocument();
    expect(deleteMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "确认批量删除" }));
    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith(["job-1", "job-2"]));
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
    await user.click(screen.getByRole("button", { name: "修复并重跑" }));
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("job-1"));
    expect(onOpen).toHaveBeenCalledWith("replacement-job");
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

    await screen.findByText("第 1 / 3 页");
    await user.selectOptions(screen.getByRole("combobox", { name: "每页显示条数" }), "20");
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 20, offset: 0 }),
      ),
    );
    expect(screen.getByText("第 1 / 2 页")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页作答记录" }));
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 20, offset: 20 }),
      ),
    );
  });
});
