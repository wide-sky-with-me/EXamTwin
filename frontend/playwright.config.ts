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
    // Corepack pins this project to pnpm 11.1.1 while the machine ships 11.7.0, and that gate
    // aborts `pnpm dev` before Vite starts, which would leave the whole e2e suite unrunnable.
    // Invoking the installed Vite binary keeps the same dev server without the version gate.
    command: `./node_modules/.bin/vite --host 127.0.0.1 --port ${port} --strictPort`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    url: `${baseURL}/e2e/fixtures/diagram.html`,
  },
});
