import { test, expect } from "@playwright/test";
import { createDataset } from "./journeys";

for (const alias of ["project", "project_id"]) {
  test(`Data ${alias} link yields to explicit project selection across reload and Back`, async ({ page, request }) => {
    const first = await createDataset(request, `Copy first ${alias}`, { source: "sklearn", name: "iris" });
    const second = await createDataset(request, `Copy second ${alias}`, { source: "sklearn", name: "iris" });
    await page.goto(`/data?${alias}=${first.project.id}&tab=upload`);
    await expect(page.locator(".project-value")).toHaveText(first.project.name);
    await expect(page.getByRole("button", { name: "Choose sources", exact: true })).toBeVisible();
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
  const { project } = await createDataset(request, "Copy layout", { source: "sklearn", name: "iris" });
  for (const [tab, removed] of [
    ["upload", "Add scientific files"], ["import", "Reference Datasets"],
    ["library", "Reference Library"], ["multi-well", "Multi-well experiment"],
    ["synthesis", "FTIR Synthesis"],
  ]) {
    await page.goto(`/data?project=${project.id}&tab=${tab}`);
    await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: removed, exact: true })).toHaveCount(0);
    if (tab === "upload") {
      await expect(page.getByRole("button", { name: "Choose sources", exact: true })).toBeVisible();
      await testInfo.attach("upload-reduced", { body: await page.screenshot(), contentType: "image/png" });
    }
    if (tab === "library") await expect(page.getByRole("link", { name: /Reference library and dataset import/ })).toBeVisible();
  }
  await page.goto("/runs?tab=batch");
  await expect(page.getByRole("heading", { name: "Batch", exact: true })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Apply trained model — no refit" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Run workflow — train/evaluate" })).toBeVisible();
  await page.goto("/runs?tab=inspect");
  await expect(page.getByRole("heading", { name: "Inspect", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open History", exact: true })).toBeVisible();
  await page.goto("/report?tab=preview");
  await expect(page.getByText("Choose inputs in Setup, then generate the report.", { exact: true })).toBeVisible();
  await expect(page.getByText("Select a workflow to generate a report", { exact: true })).toHaveCount(0);
});
