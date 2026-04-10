import { test, expect } from "./fixtures/auth";

test.describe("Workflow Builder Smoke", () => {
  test("navigate to workflow builder, add nodes, and run", async ({
    authenticatedPage: page,
  }) => {
    // Navigate to workflow builder
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);
    await expect(page.locator("h1")).toContainText("Workflow Builder");

    // Click "New" to start a fresh workflow
    await page.getByRole("button", { name: "New", exact: true }).click();

    // Expand "Data Sources" section in the toolbar and add a Data Source node
    await page.locator(".section-header").filter({ hasText: "Data Sources" }).click();
    await page.locator(".node-button").filter({ hasText: "Data Source" }).first().click();

    // Verify a node appeared on the canvas
    await expect(page.locator(".workflow-canvas .node")).toHaveCount(1);

    // Expand "Preprocessing" section and add an SNV node
    await page.locator(".section-header").filter({ hasText: "Preprocessing" }).click();
    await page.locator(".node-button").filter({ hasText: "SNV" }).first().click();

    // Should now have 2 nodes
    await expect(page.locator(".workflow-canvas .node")).toHaveCount(2);

    // Run button should be enabled with nodes present
    const runButton = page.getByRole("button", { name: /Run/ });
    await expect(runButton).toBeEnabled();
  });

  test("workflow page loads node toolbar", async ({
    authenticatedPage: page,
  }) => {
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);

    // Toolbar sections should be present
    await expect(
      page.locator(".section-header").filter({ hasText: "Data Sources" })
    ).toBeVisible();
    await expect(
      page.locator(".section-header").filter({ hasText: "Preprocessing" })
    ).toBeVisible();
    await expect(
      page.locator(".section-header").filter({ hasText: "Exploratory" })
    ).toBeVisible();
  });
});
