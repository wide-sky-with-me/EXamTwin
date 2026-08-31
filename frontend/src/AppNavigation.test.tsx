import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BookOpen } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { SidebarNavigation } from "./App";

const items = [
  { key: "subjects", icon: <BookOpen size={17} />, label: "科目", path: "/subjects" },
];

describe("SidebarNavigation", () => {
  it("keeps labels and appearance controls in the expanded state", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const onToggle = vi.fn();
    render(
      <SidebarNavigation
        collapsed={false}
        items={items}
        onNavigate={onNavigate}
        onToggle={onToggle}
        selectedKey="subjects"
      />,
    );

    expect(screen.getByText("ExamTwin")).toBeInTheDocument();
    expect(screen.getByLabelText("界面主题")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(onToggle).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("menuitem", { name: "科目" }));
    expect(onNavigate).toHaveBeenCalledWith("/subjects");
  });

  it("uses the compact menu and exposes an accessible expand action", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const { container } = render(
      <SidebarNavigation
        collapsed
        items={items}
        onNavigate={vi.fn()}
        onToggle={onToggle}
        selectedKey="subjects"
      />,
    );

    expect(container.querySelector(".ant-menu-inline-collapsed")).toBeInTheDocument();
    expect(screen.queryByText("ExamTwin")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("界面主题")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "展开侧栏" }));
    expect(onToggle).toHaveBeenCalledOnce();
  });
});
