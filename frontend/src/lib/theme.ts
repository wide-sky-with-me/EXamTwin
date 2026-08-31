export type ThemePreference = "system" | "light" | "dark";

export const APP_THEME_PALETTE = {
  common: {
    info: "#32ade6",
    primary: "#0071e3",
    success: "#16846a",
  },
  dark: {
    base: "#000000",
    border: "#38383d",
    container: "#111113",
    header: "#1c1c1e",
    page: "#0b0d12",
    text: "#f5f5f7",
  },
  light: {
    base: "#f5f5f7",
    border: "#d9d9df",
    container: "#ffffff",
    header: "#f5f5f7",
    page: "#eef2f8",
    text: "#1d1d1f",
  },
} as const;

export const THEME_STORAGE_KEY = "examtwin.theme";

export function storedTheme(): ThemePreference {
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

export function applyTheme(preference: ThemePreference): void {
  const dark =
    preference === "dark" ||
    (preference === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const resolvedTheme = dark ? "dark" : "light";
  document.documentElement.dataset.theme = resolvedTheme;
  document.documentElement.dataset.themePreference = preference;
  document
    .querySelector<HTMLMetaElement>('meta[name="theme-color"]')
    ?.setAttribute("content", APP_THEME_PALETTE[resolvedTheme].page);
  window.dispatchEvent(new CustomEvent("examtwin-theme-change", {
    detail: resolvedTheme,
  }));
}

export function saveTheme(preference: ThemePreference): void {
  window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  applyTheme(preference);
}
