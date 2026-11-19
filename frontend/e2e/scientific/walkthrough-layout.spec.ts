import { test, expect } from "@playwright/test";
import { createDataset } from "./journeys";

test("project cards and Data controls fit beside expanded navigation @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "Walkthrough — Lavender Essential Oil FTIR Corpus v1 PCA Exploration & Outlier Diagnostics", { source: "sklearn", name: "iris" });
  await page.addInitScript(() => localStorage.setItem("navCollapsed", "false"));
  await page.setViewportSize({ width: 871, height: 1000 });
  await page.goto(`/dashboard?project=${dataset.project.id}&tab=projects`);
  const card = page.locator(".project-card").filter({ has: page.getByRole("button", { name: new RegExp(`^(Open|Select) project ${dataset.project.name}$`) }) });
  await expect(card).toBeVisible();
  const cardGeometry = await card.evaluate(element => ({ right: element.getBoundingClientRect().right, viewport: innerWidth }));
  expect(cardGeometry.right).toBeLessThanOrEqual(cardGeometry.viewport);
  const archive = card.getByRole("button", { name: "Archive project", exact: true });
  await archive.focus();
  await expect(archive).toBeInViewport();
  const open = card.getByRole("button", { name: /^(Open|Select) project/ });
  await open.click();
  await page.getByRole("link", { name: "Project", exact: true }).click();
  await expect(page).toHaveURL(/\/project(?:[?#]|$)/);
  await page.getByRole("link", { name: "Data", exact: true }).click();
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  const action = page.locator(".upload-action");
  await expect(action).toBeVisible();
  const upload = await action.evaluate(element => {
    const parent = element.getBoundingClientRect();
    const button = element.querySelector("button")!.getBoundingClientRect();
    return { right: parent.right, buttonRight: button.right, buttonWidth: button.width };
  });
  expect(upload.buttonRight).toBeLessThanOrEqual(upload.right + 1);
  expect(upload.buttonWidth).toBeGreaterThan(140);
  await page.getByRole("button", { name: "Synthesis", exact: true }).click();
  for (const label of ["Samples", "Path length (cm)", "Noise sigma (AU)"]) {
    const input = page.getByRole("spinbutton", { name: label, exact: true });
    await expect(input).toBeVisible();
    const bounds = await input.evaluate(element => {
      const field = element.closest(".field")!.getBoundingClientRect();
      const box = element.getBoundingClientRect();
      return { right: box.right, fieldRight: field.right };
    });
    expect(bounds.right).toBeLessThanOrEqual(bounds.fieldRight + 1);
  }
  await page.screenshot({ path: test.info().outputPath("expanded-navigation-data.png") });
});

test("source preview chart and toolbar fit inside the padded graph panel @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "Source preview layout", { source: "sklearn", name: "iris" });
  await page.addInitScript(() => localStorage.setItem("navCollapsed", "false"));
  await page.setViewportSize({ width: 871, height: 1000 });
  await page.goto(`/data?project=${dataset.project.id}&tab=import`);
  const catalog = page.locator(".ref-group-panel").filter({ hasText: "scikit-learn datasets" });
  await catalog.locator(".p-panel-header button").click();
  await catalog.locator(".ref-dataset-item").filter({ hasText: "Iris" }).click();
  const graph = page.locator(".source-plot .plotly-chart");
  await expect(graph.locator(".main-svg").first()).toBeVisible();
  for (const width of [871, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    const bounds = await graph.evaluate(element => {
      const plot = element.getBoundingClientRect();
      const panel = element.closest(".source-plot")!.getBoundingClientRect();
      return { left: plot.left, right: plot.right, panelLeft: panel.left, panelRight: panel.right };
    });
    expect(bounds.left).toBeGreaterThanOrEqual(bounds.panelLeft);
    expect(bounds.right).toBeLessThanOrEqual(bounds.panelRight);
  }
  await page.screenshot({ path: test.info().outputPath("source-preview-layout.png") });
});
