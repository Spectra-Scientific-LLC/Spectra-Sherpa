import { test, expect, type Locator } from "@playwright/test";
import { closeDialog, plotData } from "./assertions";
import { createDataset, instantiate, runWorkflow } from "./journeys";

async function expectUnclippedFigure(surface: Locator) {
  await expect(surface.locator(".plotly-canvas .main-svg").first()).toBeVisible();
  await expect.poll(() => surface.locator(".plotly-container").evaluate(el => {
    const canvas = el.querySelector(".plotly-chart")!;
    return {
      insideHeight: el.clientHeight >= canvas.getBoundingClientRect().height,
      innerScrollbar: el.scrollHeight > el.clientHeight + 1 && getComputedStyle(el).overflowY === "auto",
    };
  })).toEqual({ insideHeight: true, innerScrollbar: false });
}

test("paired preprocessing plots retain their full height in Quick Plot and Detailed View @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "mixture-ir");
  const workflow = await instantiate(request, dataset, "pca");
  await runWorkflow(page, workflow, dataset.project);
  await page.locator(".workflow-node").filter({ hasText: "Mean Center" }).first().click();
  await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
  const quick = page.getByRole("dialog");
  const expected = await plotData(quick);
  expect(expected.traces.length).toBeGreaterThan(22);
  await expectUnclippedFigure(quick);
  const height = await quick.locator(".plotly-chart").evaluate(el => el.getBoundingClientRect().height);
  expect(height).toBeGreaterThanOrEqual(850);
  await closeDialog(page);
  await page.getByRole("button", { name: "Open to Run Trials", exact: true }).click();
  const detail = page.locator(".node-detail-view");
  await expect(detail).toBeVisible();
  const plot = detail.locator(".embedded-plot");
  if (!await plot.isVisible()) await detail.getByRole("heading", { name: "Plots", exact: true }).click();
  await expectUnclippedFigure(plot);
  expect(await plotData(plot)).toEqual(expected);
  expect(await plot.locator(".plotly-chart").evaluate(el => el.getBoundingClientRect().height)).toBe(height);
  // Wrapped controls must not steal the graph's height at a narrower viewport.
  await page.setViewportSize({ width: 1100, height: 900 });
  await expectUnclippedFigure(plot);
  expect(await plotData(plot)).toEqual(expected);
  await test.info().attach("detailed-paired-figure.png", { body: await plot.screenshot(), contentType: "image/png" });
  await detail.getByRole("button", { name: "Cancel", exact: true }).click();
});
