import type { ReactElement } from "react";
import { render as testingLibraryRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { DesignSystemProvider } from "../components/ui/DesignSystemProvider";
import type { SubjectStatus } from "../types";
import { SubjectManagement } from "./SubjectManagement";

function subjectFixture(index: number): SubjectStatus {
  const enabled = index % 2 === 1;
  return {
    id: `subject-${index}`,
    subject_code: `S${String(index).padStart(2, "0")}`,
    title: `Subject ${index}`,
    board_name: index % 3 === 0 ? "Cambridge" : "OxfordAQA",
    version: "1",
    digest: `digest-${index}`,
    capability_profile_id: null,
    generic_qa_enabled: true,
    answering_enabled: enabled,
    answering_disabled_reason: enabled ? null : "需配置",
    active_graph_version_id: null,
    knowledge_bases: [],
    units: [],
    source_booklet_required: false,
    vector_alias: `subject-${index}`,
    vector_index_ready: enabled,
    vector_points: index,
    stats: null,
    icon: "book-open",
    color: "#2F6FED",
  };
}

function render(ui: ReactElement) {
  return testingLibraryRender(ui, { wrapper: DesignSystemProvider });
}

describe("SubjectManagement", () => {
  test("searches, filters, resets, and paginates subjects with shared controls", async () => {
    const user = userEvent.setup();
    const subjects = Array.from({ length: 12 }, (_, index) => subjectFixture(index + 1));
    render(<SubjectManagement loading={false} refresh={vi.fn()} subjects={subjects} />);

    expect(screen.getByLabelText("科目分页")).toHaveTextContent("1–10/ 12 个");
    expect(screen.queryByText("Subject 11")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页科目" }));
    expect(screen.getByText("Subject 11")).toBeVisible();

    await user.click(screen.getByRole("combobox", { name: "按科目状态筛选" }));
    await user.click(await screen.findByText("可用", { selector: ".ant-select-item-option-content" }));
    expect(screen.getByText("Subject 1")).toBeVisible();
    expect(screen.queryByText("Subject 2")).not.toBeInTheDocument();
    expect(screen.getByLabelText("科目分页")).toHaveTextContent("1–6/ 6 个");

    await user.click(screen.getByRole("combobox", { name: "按考试局筛选" }));
    await user.click(await screen.findByText("Cambridge", { selector: ".ant-select-item-option-content" }));
    expect(screen.getByText("Subject 3")).toBeVisible();
    expect(screen.queryByText("Subject 1")).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("搜索科目"));
    await user.type(screen.getByLabelText("搜索科目"), "Subject 9");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => {
      expect(screen.getByText("Subject 9")).toBeVisible();
      expect(screen.queryByText("Subject 3")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "重置筛选" }));
    expect(screen.getByLabelText("搜索科目")).toHaveValue("");
    expect(screen.getByLabelText("科目分页")).toHaveTextContent("1–10/ 12 个");
  }, 10_000);

  test("keeps management actions on each course card and confirms deletion", async () => {
    const user = userEvent.setup();
    const subject = subjectFixture(1);
    render(<SubjectManagement loading={false} refresh={vi.fn()} subjects={[subject]} />);

    expect(screen.getByRole("heading", { name: "科目" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: `设置 ${subject.title}` })).toBeVisible();
    await user.hover(screen.getByText(subject.title));
    expect(await screen.findByRole("tooltip")).toHaveTextContent(subject.title);
    await user.click(screen.getByRole("button", { name: `删除 ${subject.title}` }));

    const dialog = screen.getByRole("alertdialog", { name: "确认删除科目" });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveTextContent(`将删除“${subject.title}”`);
  });
});
