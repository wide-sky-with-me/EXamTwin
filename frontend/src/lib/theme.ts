export type ThemePreference = "system" | "light" | "dark";

const THEME_COLORS = {
  dark: "#000000",
  light: "#f5f5f7",
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
    ?.setAttribute("content", THEME_COLORS[resolvedTheme]);
}

export function saveTheme(preference: ThemePreference): void {
  window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  applyTheme(preference);
}
