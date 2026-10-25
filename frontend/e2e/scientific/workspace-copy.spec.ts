import { test, expect } from "@playwright/test";
import { createDataset } from "./journeys";

for (const alias of ["project", "project_id"]) {
  test(`Data ${alias} link yields to explicit project selection across reload and Back`, async ({ page, request }) => {
    const first = await createDataset(request, `Copy first ${alias}`, { source: "sklearn", name: "iris" });
    const second = await createDataset(request, `Copy second ${alias}`, { source: "sklearn", name: "iris" });
    await page.goto(`/data?${alias}=${first.project.id}&tab=upload`);
    await expect(page.locator(".project-value")).toHaveText(first.project.name);
    await expect(page.locator(".workspace-header").getByRole("button", { name: "Load", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Add scientific files", exact: true })).toHaveCount(0);
    await page.locator(".project-dropdown").click();
    await page.getByRole("option", { name: new RegExp(second.project.name) }).click();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await expect.poll(() => new URL(page.url()).searchParams.has(alias)).toBe(false);
    await page.reload();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await page.getByRole("link", { name: "Documentation", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Documentation", exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await expect.poll(() => new URL(page.url()).searchParams.has(alias)).toBe(false);
  });
}

test("workspace sections keep actions and context without duplicate introductions", async ({ page, request }, testInfo) => {
  const { project, experiment } = await createDataset(request, "Copy layout", { source: "sklearn", name: "iris" });
  for (const [tab, removed] of [
    ["upload", "Add scientific files"], ["import", "Reference Datasets"],
    ["library", "Reference Library"], ["multi-well", "Multi-well experiment"],
    ["synthesis", "FTIR Synthesis"],
  ]) {
    await page.goto(`/data?project=${project.id}&tab=${tab}`);
    await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: removed, exact: true })).toHaveCount(0);
    const header = page.locator(".workspace-header");
    await expect(header.getByRole("button", { name: "My Dataset", exact: true })).toBeVisible();
    await expect(header.getByRole("button", { name: "Workflow", exact: true })).toHaveCount(0);
    if (tab === "upload") {
      await expect(header.getByRole("button", { name: "Load", exact: true })).toBeVisible();
      await expect(page.getByText("Files, folders or ZIPs.", { exact: true })).toHaveCount(0);
      await testInfo.attach("upload-reduced", { body: await page.screenshot(), contentType: "image/png" });
    }
    if (tab === "library" || tab === "synthesis") {
      await expect(header.getByRole("button", { name: "Guide", exact: true })).toBeVisible();
    }
    if (tab === "multi-well") {
      await expect(page.locator('[aria-label="Data workspace context"]')).toContainText(experiment.name);
      await expect(page.locator('[aria-label="Data workspace context"]')).toContainText("0 wells configured");
      await expect(page.getByRole("button", { name: "Save acquisition plan", exact: true })).toHaveCount(0);
    }
  }
  await page.goto("/runs?tab=batch");
  await expect(page.getByRole("heading", { name: "Batch", exact: true })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Apply trained model — no refit" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Run workflow — train/evaluate" })).toBeVisible();
  await page.goto("/runs?tab=inspect");
  await expect(page.getByRole("heading", { name: "Inspect", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open History", exact: true })).toBeVisible();
  const inspect = page.getByRole("region", { name: "Inspect", exact: true }).locator(".workspace-state--page");
  const inspectStyle = await inspect.evaluate(element => {
    const state = getComputedStyle(element), message = getComputedStyle(element.querySelector("p")!);
    return { padding: state.padding, gap: state.gap, size: message.fontSize, weight: message.fontWeight };
  });
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  const compare = page.getByRole("region", { name: "Compare", exact: true }).locator(".workspace-state--page");
  await expect(compare).toBeVisible();
  expect(await compare.evaluate(element => {
    const state = getComputedStyle(element), message = getComputedStyle(element.querySelector("p")!);
    return { padding: state.padding, gap: state.gap, size: message.fontSize, weight: message.fontWeight };
  })).toEqual(inspectStyle);
  await page.getByRole("button", { name: "Models", exact: true }).click();
  for (const section of ["Local Model History", "Saved Models", "Imported Models"]) {
    await expect(page.getByRole("button", { name: section, exact: true })).toBeVisible();
  }
  await page.goto("/report?tab=preview");
  await expect(page.getByText("Choose inputs in Setup, then generate the report.", { exact: true })).toBeVisible();
  await expect(page.getByText("Select a workflow to generate a report", { exact: true })).toHaveCount(0);
});
