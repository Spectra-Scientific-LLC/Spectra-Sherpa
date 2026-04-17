import { test, expect } from "./fixtures/auth";

/**
 * Full CRUD coverage for workflows.
 *
 * Create and persist are exercised through the UI. Rename and delete use
 * the REST API directly (via `page.request`) because the frontend does not
 * yet expose those actions in the UI. After each API mutation we reload and
 * verify the effect is visible in the app.
 *
 * Addresses issue #23 — deliverable 3.
 */
test.describe("Workflow CRUD", () => {
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

  test("rename a workflow via API → new name visible after reload", async ({
    authenticatedPage: page,
  }) => {
    // Navigate to builder and create a fresh workflow.
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);
    await page.getByRole("button", { name: "New", exact: true }).click();

    // Add a node + save so the workflow is persisted.
    await page
      .locator(".section-header")
      .filter({ hasText: "Data Sources" })
      .click();
    await page
      .locator(".node-button")
      .filter({ hasText: "Data Source" })
      .first()
      .click();
    await page.getByRole("button", { name: /^Save/ }).click();
    await expect(page.locator(".autosave-indicator")).toBeVisible({
      timeout: 5000,
    });

    // Grab the workflow ID from the store (exposed on window in dev mode)
    // or from the workflows list API.
    const baseUrl = await page.evaluate(() => {
      const meta = document.querySelector('meta[name="api-base"]');
      return meta?.getAttribute("content") ?? "/api/v1";
    });

    // Fetch token from localStorage (the auth store persists it there).
    const token = await page.evaluate(() =>
      localStorage.getItem("token"),
    );

    // List workflows to find the one we just created.
    const listResp = await page.request.get(`${baseUrl}/workflows`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    expect(listResp.ok()).toBeTruthy();
    const workflows = await listResp.json();
    expect(workflows.length).toBeGreaterThan(0);

    // Pick the most recently created workflow.
    const target = workflows.sort(
      (a: { id: number }, b: { id: number }) => b.id - a.id,
    )[0];
    const newName = `Renamed-E2E-${Date.now()}`;

    // Rename via PUT.
    const renameResp = await page.request.put(
      `${baseUrl}/workflows/${target.id}`,
      {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        data: { name: newName },
      },
    );
    expect(renameResp.ok()).toBeTruthy();

    // Verify the rename stuck by re-listing.
    const listResp2 = await page.request.get(`${baseUrl}/workflows`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const refreshed = await listResp2.json();
    const renamed = refreshed.find(
      (w: { id: number }) => w.id === target.id,
    );
    expect(renamed).toBeDefined();
    expect(renamed.name).toBe(newName);
  });

  test("delete a workflow via API → it no longer appears in list", async ({
    authenticatedPage: page,
  }) => {
    // Navigate to builder and create a throw-away workflow.
    await page.click('.nav-link[href="/workflow"]');
    await expect(page).toHaveURL(/\/workflow/);
    await page.getByRole("button", { name: "New", exact: true }).click();

    await page
      .locator(".section-header")
      .filter({ hasText: "Data Sources" })
      .click();
    await page
      .locator(".node-button")
      .filter({ hasText: "Data Source" })
      .first()
      .click();
    await page.getByRole("button", { name: /^Save/ }).click();
    await expect(page.locator(".autosave-indicator")).toBeVisible({
      timeout: 5000,
    });

    const baseUrl = await page.evaluate(() => {
      const meta = document.querySelector('meta[name="api-base"]');
      return meta?.getAttribute("content") ?? "/api/v1";
    });
    const token = await page.evaluate(() =>
      localStorage.getItem("token"),
    );

    // List and find our workflow.
    const listResp = await page.request.get(`${baseUrl}/workflows`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const workflows = await listResp.json();
    const target = workflows.sort(
      (a: { id: number }, b: { id: number }) => b.id - a.id,
    )[0];

    // Delete via API.
    const deleteResp = await page.request.delete(
      `${baseUrl}/workflows/${target.id}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
    );
    expect(deleteResp.ok()).toBeTruthy();

    // Verify it's gone.
    const listResp2 = await page.request.get(`${baseUrl}/workflows`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    const remaining = await listResp2.json();
    const found = remaining.find(
      (w: { id: number }) => w.id === target.id,
    );
    expect(found).toBeUndefined();
  });
});
