import { test, expect, type Locator } from "@playwright/test";
import { closeDialog, plotData, settledSurfaceLayout } from "./assertions";
import { createDataset, instantiate, runWorkflow } from "./journeys";

async function expectUnclippedFigure(surface: Locator) {
  await expect(surface.locator(".plotly-canvas .main-svg").first()).toBeVisible();
  await settledSurfaceLayout(surface);
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

test("figure geometry waits for ancestor transitions without accepting short or clipped plots @smoke", async ({ page }) => {
  // Use the application's actual PrimeVue theme, not a test-only transition.
  // Install the theme before inserting the fixture, as the application does.
  // Styling an already-rendered unstyled dialog starts unrelated transitions
  // toward scale(.7); reversing those immediately can omit transform entirely.
  await page.setContent("");
  await page.addStyleTag({ path: "node_modules/primevue/resources/themes/lara-light-blue/theme.css" });
  await page.evaluate(() => {
    document.body.innerHTML = '<div role="dialog" class="p-dialog p-dialog-enter-from p-dialog-enter-active"><section class="embedded-plot"><div class="plotly-container"><div class="plotly-chart" style="height:850px"><div class="plotly-canvas"><svg class="main-svg" width="800" height="850"></svg></div></div></div></section></div>';
  });
  const dialog = page.getByRole("dialog");
  const plot = dialog.locator(".embedded-plot");
  await dialog.evaluate(async el => {
    // Flush the enter-from state, then deterministically hold its real CSS
    // transition mid-flight. Host speed cannot turn this into retry-to-green.
    if (new DOMMatrixReadOnly(getComputedStyle(el).transform).m22 !== 0.7) {
      throw new Error("Expected the settled dialog enter-from scale");
    }
    el.classList.remove("p-dialog-enter-from");
    const animations = el.getAnimations();
    if (!animations.some(animation => animation instanceof CSSTransition && animation.transitionProperty === "transform")) {
      throw new Error("Expected the real dialog transform transition");
    }
    animations.forEach(animation => animation.pause());
    await Promise.all(animations.map(animation => animation.ready));
    for (const animation of animations) {
      animation.currentTime = Number(animation.effect!.getTiming().duration) * 0.85;
    }
  });
  const chart = plot.locator(".plotly-chart");
  expect(await chart.evaluate(el => el.clientHeight)).toBe(850);
  // The old immediate >=850 assertion genuinely fails during this transition.
  expect(await chart.evaluate(el => el.getBoundingClientRect().height)).toBeLessThan(850);
  let settled = false;
  const ready = settledSurfaceLayout(plot).then(() => { settled = true; });
  await plot.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  expect(settled, "Geometry readiness must not skip a paused ancestor transition").toBe(false);
  await dialog.evaluate(el => el.getAnimations().forEach(animation => animation.play()));
  await ready;
  expect(await chart.evaluate(el => el.getBoundingClientRect().height)).toBe(850);
  await expectUnclippedFigure(plot);

  await chart.evaluate(el => { el.style.height = "849px"; });
  await settledSurfaceLayout(plot);
  const shortened = await chart.evaluate(el => el.getBoundingClientRect().height);
  expect(shortened).toBe(849);
  expect(() => expect(shortened).toBeGreaterThanOrEqual(850)).toThrow();
  await chart.evaluate(el => { el.style.height = "850px"; });
  await plot.locator(".plotly-container").evaluate(el => {
    Object.assign((el as HTMLElement).style, { height: "400px", overflowY: "auto" });
  });
  await expect(expectUnclippedFigure(plot)).rejects.toThrow();
});
