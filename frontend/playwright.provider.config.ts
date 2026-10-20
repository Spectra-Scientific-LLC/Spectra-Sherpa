import { defineConfig } from "@playwright/test";
import scientific from "./playwright.scientific.config";

// Explicit local/release qualification only. No ordinary CI discovers this
// directory and no test downloads provider data.
export default defineConfig({
  ...scientific,
  testDir: "./e2e/provider",
  timeout: 180_000,
  outputDir: "provider-browser-results",
  reporter: [["list"], ["html", { outputFolder: "provider-browser-report", open: "never" }]],
});
