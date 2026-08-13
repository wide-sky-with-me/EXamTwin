import { Segmented, Tooltip } from "antd";
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
    <Segmented<ThemePreference>
      aria-label="界面主题"
      onChange={(value) => {
        setPreference(value);
        saveTheme(value);
      }}
      options={choices.map(({ value, label, icon: Icon }) => ({
        label: <Tooltip title={label}><Icon aria-label={label} size={15} /></Tooltip>,
        value,
      }))}
      size="small"
      value={preference}
    />
  );
}
