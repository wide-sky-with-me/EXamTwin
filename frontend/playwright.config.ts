import { defineConfig, devices } from "@playwright/test";

const port = process.env.PLAYWRIGHT_PORT || "4173";
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 5_000,
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
    },
  },
  snapshotPathTemplate: "{testDir}/__screenshots__/{platform}/{arg}{ext}",
  use: {
    baseURL,
    colorScheme: "light",
    locale: "zh-CN",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chrome",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
      },
    },
  ],
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: `${baseURL}/e2e/fixtures/diagram.html`,
  },
});
