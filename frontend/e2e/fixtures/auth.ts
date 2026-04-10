import { test as base, expect, type Page } from "@playwright/test";
import { fileURLToPath } from "url";
import * as path from "path";
import * as dotenv from "dotenv";

// Load e2e credentials
const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, "../.env.e2e") });

const E2E_USERNAME = process.env.E2E_USERNAME!;
const E2E_PASSWORD = process.env.E2E_PASSWORD!;

if (!E2E_USERNAME || !E2E_PASSWORD) {
  throw new Error(
    "E2E_USERNAME and E2E_PASSWORD must be set in frontend/e2e/.env.e2e"
  );
}

async function login(page: Page) {
  await page.goto("/login");
  await page.getByPlaceholder("Enter your username").fill(E2E_USERNAME);
  await page.getByPlaceholder("Enter your password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Sign In" }).click();
  // Wait for redirect to landing page
  await expect(page).not.toHaveURL(/\/login/);
}

/** Authenticated test fixture — logs in before each test. */
export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ page }, use) => {
    await login(page);
    await use(page);
  },
});

export { expect, login };
