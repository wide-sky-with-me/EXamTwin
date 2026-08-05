import { Laptop, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import {
  applyTheme,
  saveTheme,
  storedTheme,
  type ThemePreference,
} from "../lib/theme";

const choices: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "浅色主题", icon: Sun },
  { value: "system", label: "跟随系统", icon: Laptop },
  { value: "dark", label: "深色主题", icon: Moon },
];

export function ThemeSwitch() {
  const [preference, setPreference] = useState<ThemePreference>(storedTheme);

  useEffect(() => {
    applyTheme(preference);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const updateSystemTheme = () => {
      if (preference === "system") applyTheme("system");
    };
    media.addEventListener("change", updateSystemTheme);
    return () => media.removeEventListener("change", updateSystemTheme);
  }, [preference]);

  return (
    <div className="theme-switch" role="group" aria-label="界面主题">
      {choices.map(({ value, label, icon: Icon }) => (
        <button
          type="button"
          key={value}
          className={preference === value ? "active" : ""}
          aria-label={label}
          aria-pressed={preference === value}
          title={label}
          onClick={() => {
            setPreference(value);
            saveTheme(value);
          }}
        >
          <Icon size={15} />
        </button>
      ))}
    </div>
  );
}
