import { defineConfig } from "@playwright/test";

const port = Number(process.env.SCIENTIFIC_BROWSER_PORT ?? 8041);
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e/scientific",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "scientific-browser-report", open: "never" }]],
  outputDir: "scientific-browser-results",
  use: {
    baseURL,
    browserName: "chromium",
    channel: process.env.SCIENTIFIC_BROWSER_CHANNEL,
    viewport: { width: 1440, height: 1000 },
    locale: "en-US",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    actionTimeout: 15_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `${process.env.SCIENTIFIC_BROWSER_PYTHON ?? "python"} ../scripts/scientific_browser_server.py --port ${port}`,
    url: `${baseURL}/api/v1/health`,
    reuseExistingServer: false,
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
