import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test } from "vitest";

import { applyTheme } from "../lib/theme";
import { ThemeSwitch } from "./ThemeSwitch";

describe("ThemeSwitch", () => {
  beforeEach(() => {
    window.localStorage.clear();
    applyTheme("system");
  });

  test("keeps every mounted switch on the preference chosen in any of them", async () => {
    const user = userEvent.setup();
    render(<><ThemeSwitch /><ThemeSwitch /></>);

    await user.click(screen.getAllByText("深色", { exact: true })[0]);

    const selected = [...document.querySelectorAll(".ant-segmented-item-selected")].map((node) => node.textContent);
    expect(selected).toEqual(["深色", "深色"]);
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
