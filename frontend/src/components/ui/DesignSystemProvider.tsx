import { Theme } from "@radix-ui/themes";
import { MotionConfig } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";

type ResolvedTheme = "light" | "dark";

function currentTheme(): ResolvedTheme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<ResolvedTheme>(currentTheme);

  useEffect(() => {
    const syncTheme = () => setAppearance(currentTheme());
    window.addEventListener("examtwin-theme-change", syncTheme);
    return () => window.removeEventListener("examtwin-theme-change", syncTheme);
  }, []);

  return (
    <Theme
      accentColor="blue"
      appearance={appearance}
      grayColor="slate"
      panelBackground="solid"
      radius="large"
      scaling="100%"
    >
      <MotionConfig reducedMotion="user" transition={{ duration: 0.22 }}>
        {children}
      </MotionConfig>
    </Theme>
  );
}
