import { test, expect } from "@playwright/test";
import { createDataset, instantiate } from "./journeys";

test("collapsed sidebar separates page links from section expanders @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "Navigation", { source: "sklearn", name: "iris" });
  await page.addInitScript(() => localStorage.setItem("navCollapsed", "true"));
  await page.setViewportSize({ width: 871, height: 1000 });
  await page.goto(`/data?project=${dataset.project.id}&tab=my-dataset`);
  const link = page.locator('.sidebar.collapsed a[aria-label="Data"]');
  const expand = page.getByRole("button", { name: "Expand Data sections", exact: true });
  await expect(expand).toBeVisible();
  const linkBox = (await link.boundingBox())!;
  const expandBox = (await expand.boundingBox())!;
  expect(Math.max(linkBox.x, expandBox.x)).toBeGreaterThanOrEqual(Math.min(linkBox.x + linkBox.width, expandBox.x + expandBox.width));
  await page.mouse.click(linkBox.x + linkBox.width / 2, linkBox.y + linkBox.height / 2);
  await expect(page.locator(".sidebar")).toHaveClass(/collapsed/);
  await expand.click();
  await expect(page.locator(".sidebar")).not.toHaveClass(/collapsed/);
  await page.getByRole("button", { name: "Collapse navigation", exact: true }).click();
  await expect(page.locator(".sidebar")).toHaveClass(/collapsed/);
  for (const name of ["Report", "Data", "Runs"]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { name, exact: true }).first()).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/${name.toLowerCase()}(?:[?#]|$)`));
  }
});

test("retained report fits a narrow workspace and keeps tables inside the frame @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "Lavender Essential Oil FTIR Corpus v1 PCA Exploration & Outlier Diagnostics", { source: "sklearn", name: "iris" });
  const workflow = await instantiate(request, dataset, "pca");
  const response = await request.post(`/api/v1/workflows/${workflow.id}/execute`, { data: {}, timeout: 60000 });
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  expect(result.status).toBe("completed");
  await page.addInitScript(() => localStorage.setItem("navCollapsed", "true"));
  for (const width of [871, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`/report?workflow=${workflow.id}&run=${result.run_id}&project=${dataset.project.id}`);
    const frame = page.frameLocator('iframe[title="Report preview"]');
    await expect(frame.getByText(`#${result.run_id} — completed`, { exact: true })).toBeVisible();
    // Focusing a topbar control must not scroll the clipped workspace to the
    // right when the active project has a long name.
    await page.getByRole("button", { name: "User menu", exact: true }).focus();
    const geometry = await page.locator(".report-content").evaluate(element => {
      const bounds = element.getBoundingClientRect();
      const content = element.closest(".content")!;
      return { left: bounds.left, right: bounds.right, scrollLeft: content.scrollLeft, shellScroll: element.closest(".workspace")!.scrollLeft, viewport: innerWidth };
    });
    expect(geometry.left).toBeGreaterThanOrEqual(72);
    expect(geometry.right).toBeLessThanOrEqual(geometry.viewport);
    expect(geometry.scrollLeft).toBe(0);
    expect(geometry.shellScroll).toBe(0);
    const inner = await frame.locator("body").evaluate(element => ({
      width: element.ownerDocument.documentElement.clientWidth,
      scrollWidth: element.ownerDocument.documentElement.scrollWidth,
      titleLeft: element.querySelector("h1")!.getBoundingClientRect().left,
    }));
    expect(inner.titleLeft).toBeGreaterThanOrEqual(0);
    expect(inner.scrollWidth).toBeLessThanOrEqual(inner.width + 1);
    await page.screenshot({ path: test.info().outputPath(`report-${width}.png`) });
  }
});
