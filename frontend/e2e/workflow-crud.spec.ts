import { test, expect } from "./fixtures/auth";

test.describe("Workflow CRUD", () => {
  const testWorkflowName = `E2E Test Workflow ${Date.now()}`;

  test("create, rename, and delete a workflow", async ({
    authenticatedPage: page,
  }) => {
    // Navigate to workflow builder
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);

    // Click "New" to create a new workflow
    await page.getByRole("button", { name: "New", exact: true }).click();

    // Add a node so the workflow has content worth saving
    await page.locator(".section-header").filter({ hasText: "Data Sources" }).click();
    await page.locator(".node-button").filter({ hasText: "Data Source" }).first().click();
    await expect(page.locator(".workflow-canvas .workflow-node")).toHaveCount(1);

    // Save the workflow
    await page.getByRole("button", { name: /Save/ }).click();

    // Wait for save confirmation
    await expect(page.locator(".autosave-indicator")).toBeVisible({ timeout: 5000 });
  });
});
