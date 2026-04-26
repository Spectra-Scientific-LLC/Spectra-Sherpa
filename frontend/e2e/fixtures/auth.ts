import { test as base, expect, type Page } from "@playwright/test";

async function login(_page: Page): Promise<void> {
  throw new Error(
    "OSS e2e tests run in local single-user mode; managed login is provided by the server module.",
  );
}

/**
 * Local-mode test fixture.
 *
 * The fixture name is kept for compatibility with older specs, but it no
 * longer performs managed login. OSS local mode has an implicit single user
 * and no /login or /register UI.
 */
export const test = base.extend<{ authenticatedPage: Page }>({
  authenticatedPage: async ({ page }, use) => {
    await page.goto("/");
    await use(page);
  },
});

export { expect, login };
