import { Segmented, Tooltip } from "antd";
import { Laptop, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import {
  appliedThemePreference,
  saveTheme,
  type ThemePreference,
} from "../lib/theme";

const choices: { value: ThemePreference; label: string; shortLabel: string; icon: typeof Sun }[] = [
  { value: "light", label: "浅色主题", shortLabel: "浅色", icon: Sun },
  { value: "system", label: "跟随系统", shortLabel: "跟随", icon: Laptop },
  { value: "dark", label: "深色主题", shortLabel: "深色", icon: Moon },
];

export function ThemeSwitch() {
  const [preference, setPreference] = useState<ThemePreference>(appliedThemePreference);

  useEffect(() => {
    const sync = () => setPreference(appliedThemePreference());
    window.addEventListener("examtwin-theme-change", sync);
    return () => window.removeEventListener("examtwin-theme-change", sync);
  }, []);

  return (
    <Segmented<ThemePreference>
      aria-label="界面主题"
      block
      className="app-theme-switch"
      onChange={saveTheme}
      options={choices.map(({ value, label, shortLabel, icon: Icon }) => ({
        label: (
          <Tooltip title={label}>
            <span aria-label={label} className="flex items-center justify-center gap-1.5">
              <Icon aria-hidden="true" size={14} />
              <span aria-hidden="true" className="text-[11px] font-medium">{shortLabel}</span>
            </span>
          </Tooltip>
        ),
        value,
      }))}
      size="small"
      value={preference}
    />
  );
}
