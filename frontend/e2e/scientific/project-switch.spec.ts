import { test, expect } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";

test("a delayed run-list response cannot restore the previous project's results", async ({
  page,
  request,
}) => {
  const first = await createDataset(request, "Iris race", { source: "sklearn", name: "iris" });
  const second = await createDataset(request, "moisture-nir");
  const workflow = await instantiate(request, first, "pca");
  await runWorkflow(page, workflow, first.project);
  let release!: () => void, received!: () => void, fulfilled!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const intercepted = new Promise<void>((resolve) => {
    received = resolve;
  });
  const delivered = new Promise<void>((resolve) => {
    fulfilled = resolve;
  });
  await page.route("**/api/v1/runs?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("project_id") !== String(first.project.id)) return route.continue();
    const response = await route.fetch();
    received();
    await held;
    await route.fulfill({ response });
    fulfilled();
  });
  try {
    await page.getByRole("link", { name: "Runs", exact: true }).click();
    await intercepted;
    await page.locator(".project-dropdown").click();
    await page.getByRole("option", { name: new RegExp(second.project.name) }).click();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    release();
    await delivered;
    await expect(page.locator(".models-content")).not.toContainText(workflow.name);
    await page.reload();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await expect(page.locator(".models-content")).not.toContainText(workflow.name);
  } finally {
    release();
    await page.unroute("**/api/v1/runs?*");
  }
});
