import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MotionConfig } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";

import { APP_THEME_PALETTE } from "../../lib/theme";

type ResolvedTheme = "light" | "dark";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
    mutations: {
      retry: false,
    },
  },
});

function currentTheme(): ResolvedTheme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<ResolvedTheme>(currentTheme);
  const palette = APP_THEME_PALETTE[appearance];

  useEffect(() => {
    const syncTheme = () => setAppearance(currentTheme());
    window.addEventListener("examtwin-theme-change", syncTheme);
    return () => window.removeEventListener("examtwin-theme-change", syncTheme);
  }, []);

  return (
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        algorithm: appearance === "dark" ? theme.darkAlgorithm : theme.defaultAlgorithm,
        cssVar: { key: "examtwin" },
        token: {
          borderRadius: 12,
          colorBgBase: palette.base,
          colorBgContainer: palette.container,
          colorBorder: palette.border,
          colorInfo: APP_THEME_PALETTE.common.info,
          colorPrimary: APP_THEME_PALETTE.common.primary,
          colorSuccess: APP_THEME_PALETTE.common.success,
          colorText: palette.text,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Segoe UI', sans-serif",
        },
        components: {
          Button: { controlHeight: 40, primaryShadow: "none" },
          Input: { controlHeight: 40 },
          Select: { controlHeight: 40 },
          Table: { headerBg: palette.header },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <MotionConfig reducedMotion="user" transition={{ duration: 0.22 }}>
            {children}
          </MotionConfig>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  );
}
