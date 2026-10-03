import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { AppDialog } from "./AppDialog";
import { DesignSystemProvider } from "./DesignSystemProvider";

describe("AppDialog", () => {
  test("renders only the caller's actions, without Ant Design's default footer", () => {
    render(
      <AppDialog onOpenChange={vi.fn()} open title="审核评分标准">
        <button type="button">确认评分标准</button>
      </AppDialog>,
      { wrapper: DesignSystemProvider },
    );

    expect(screen.getByRole("button", { name: "确认评分标准" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(确定|OK)$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^(取消|Cancel)$/ })).not.toBeInTheDocument();
  });
});
