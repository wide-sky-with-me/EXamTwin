import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme, saveTheme, storedTheme, THEME_STORAGE_KEY } from "./theme";

describe("theme preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: true }));
    document.head.innerHTML = '<meta name="theme-color" content="#f5f5f7" />';
  });

  it("starts from system mode and persists an explicit override", () => {
    expect(storedTheme()).toBe("system");
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(
      "#000000",
    );

    saveTheme("light");

    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(storedTheme()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe(
      "#f5f5f7",
    );
  });
});
