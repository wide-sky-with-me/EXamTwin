import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { test, expect } from "vitest";

import { ToastProvider } from "./Toast";
import { useToast } from "./toast-context";

function WarningTrigger() {
  const { notify } = useToast();
  return <button onClick={() => notify("Source Booklet 尚未完成转换", "warning")}>trigger</button>;
}

test("renders warning notifications as a bottom-right semantic toast", async () => {
  const user = userEvent.setup();
  render(<ToastProvider><WarningTrigger /></ToastProvider>);
  await user.click(screen.getByRole("button", { name: "trigger" }));
  expect(screen.getByRole("status")).toHaveClass("toast", "toast-warning");
  expect(screen.getByText("Source Booklet 尚未完成转换")).toBeVisible();
});
