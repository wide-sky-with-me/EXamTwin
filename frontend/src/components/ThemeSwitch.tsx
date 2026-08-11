import { Laptop, Moon, Sun } from "lucide-react";
import { Tooltip } from "@radix-ui/themes";
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
        <Tooltip
          content={label}
          delayDuration={300}
          disableHoverableContent
          key={value}
          side="right"
        >
          <button
            type="button"
            className={`theme-switch-button${preference === value ? " active" : ""}`}
            aria-label={label}
            aria-pressed={preference === value}
            onClick={() => {
              setPreference(value);
              saveTheme(value);
            }}
          >
            <Icon aria-hidden="true" size={15} />
          </button>
        </Tooltip>
      ))}
    </div>
  );
}
