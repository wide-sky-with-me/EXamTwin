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

    await user.selectOptions(screen.getByRole("combobox", { name: "按科目状态筛选" }), "enabled");
    expect(screen.getByText("Subject 1")).toBeVisible();
    expect(screen.queryByText("Subject 2")).not.toBeInTheDocument();
    expect(screen.getByLabelText("科目分页")).toHaveTextContent("1–6/ 6 个");

    await user.selectOptions(screen.getByRole("combobox", { name: "按考试局筛选" }), "Cambridge");
    expect(screen.getByText("Subject 3")).toBeVisible();
    expect(screen.queryByText("Subject 1")).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("搜索科目"));
    await user.type(screen.getByLabelText("搜索科目"), "Subject 9");
    await user.click(screen.getByRole("button", { name: "搜索" }));
    await waitFor(() => {
      expect(screen.getByText("Subject 9")).toBeVisible();
      expect(screen.queryByText("Subject 3")).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "重置" }));
    expect(screen.getByLabelText("搜索科目")).toHaveValue("");
    expect(screen.getByLabelText("科目分页")).toHaveTextContent("1–10/ 12 个");
  }, 10_000);
});
