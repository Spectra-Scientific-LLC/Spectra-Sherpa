import { test, expect } from "./fixtures/auth";

/**
 * The original spec title was "create, rename, and delete a workflow" but
 * the frontend has no in-UI rename or delete affordance — only a
 * store-level `deleteWorkflow(id)` API wrapper with no button. Until one
 * of those UIs lands, this spec covers what is actually testable:
 * create → save → reload → the workflow's nodes survived the roundtrip.
 */
test.describe("Workflow create + persist", () => {
  test("create, add a node, save, reload, node is still there", async ({
    authenticatedPage: page,
  }) => {
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);

    // Fresh workflow
    await page.getByRole("button", { name: "New", exact: true }).click();

    // Add a node so the workflow has content worth saving
    await page
      .locator(".section-header")
      .filter({ hasText: "Data Sources" })
      .click();
    await page
      .locator(".node-button")
      .filter({ hasText: "Data Source" })
      .first()
      .click();
    await expect(page.locator(".workflow-canvas .workflow-node")).toHaveCount(1);

    // Save
    await page.getByRole("button", { name: /^Save/ }).click();
    await expect(page.locator(".autosave-indicator")).toBeVisible({
      timeout: 5000,
    });

    // Reload the page and confirm the workflow (and its node) came back.
    // The builder autoloads the most recent workflow on mount.
    await page.reload();
    await expect(page).toHaveURL(/\/workflow/);
    await expect(page.locator(".workflow-canvas .workflow-node")).toHaveCount(
      1,
      { timeout: 10000 },
    );
  });
});
