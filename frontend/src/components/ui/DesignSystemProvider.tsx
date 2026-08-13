import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { MotionConfig } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";

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
          colorBgBase: appearance === "dark" ? "#000000" : "#f5f5f7",
          colorBgContainer: appearance === "dark" ? "#111113" : "#ffffff",
          colorBorder: appearance === "dark" ? "#38383d" : "#d9d9df",
          colorInfo: "#32ade6",
          colorPrimary: "#0071e3",
          colorSuccess: "#16846a",
          colorText: appearance === "dark" ? "#f5f5f7" : "#1d1d1f",
          fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Segoe UI', sans-serif",
        },
        components: {
          Button: { controlHeight: 40, primaryShadow: "none" },
          Input: { controlHeight: 40 },
          Select: { controlHeight: 40 },
          Table: { headerBg: appearance === "dark" ? "#1c1c1e" : "#f5f5f7" },
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
