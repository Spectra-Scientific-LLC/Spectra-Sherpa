import { test, expect } from "@playwright/test";
import { assertIdentity, assertLabelledMatrixCsv, assertMatrix, closeDialog, downloadTable, plotData } from "./assertions";
import { readFile } from "node:fs/promises";
import { createDataset, instantiate, runWorkflow } from "./journeys";

test("Iris: import, execute and independently inspect retained scientific surfaces @smoke", async ({
  page,
  request,
}) => {
  const dataset = await createDataset(request, "Iris", { source: "sklearn", name: "iris" });
  const { project } = dataset;
  const workflow = await instantiate(request, dataset, "pca");
  const result = await runWorkflow(page, workflow, project);
  await test
    .info()
    .attach("execution.json", { body: JSON.stringify(result), contentType: "application/json" });
  await expect(page.locator(".workflow-node").filter({ hasText: "PCA" }).first()).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("iris-workflow.png") });
  await page.locator(".workflow-node").filter({ hasText: "Fit PCA Transform" }).first().click();
  await expect(page.getByRole("button", { name: "View Data", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("No data to display", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("dialog").locator("tbody tr").first()).toBeVisible();
  const csv = await downloadTable(page, page.getByRole("dialog"));
  const scores = result.results.model_1.default.data;
  expect(scores).toHaveLength(150);
  expect(scores[0]).toHaveLength(3);
  const sourceAxis = result.results.data_1.default.y_axis;
  const scoreOutput = result.results.model_1.default;
  const labels = Array.from({ length: 150 }, (_, index) => `Sample ${index + 1}`);
  expect(sourceAxis.labels).toEqual(labels);
  expect(scoreOutput.y_axis.labels).toEqual(labels);
  expect(sourceAxis.sample_table.sample_id).toHaveLength(150);
  expect(new Set(sourceAxis.sample_table.sample_id).size).toBe(150);
  assertIdentity(scoreOutput.y_axis.sample_table.sample_id, sourceAxis.sample_table.sample_id);
  const ratios: number[] = scoreOutput.metadata.explained_variance_ratio;
  expect(ratios).toHaveLength(3);
  const columns = ratios.map((ratio, index) => `PC${index + 1} (${(ratio * 100).toFixed(1)}%)`);
  assertLabelledMatrixCsv(csv, scores, labels, columns);
  await closeDialog(page);
  await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
  await page.getByRole("dialog").locator(".plot-type-dropdown").click();
  await page.getByRole("option", { name: "PCA Score Map", exact: true }).click();
  const plot = await plotData(page.getByRole("dialog"));
  const points = plot.traces
    .filter((trace) => trace.mode?.includes("markers"))
    .flatMap((trace) => trace.x.map((x, i) => [x, trace.y[i]]))
    .filter((row) => row.every(Number.isFinite));
  assertMatrix(
    points.sort((a, b) => a[0] - b[0]),
    scores.map((row: number[]) => row.slice(0, 2)).sort((a: number[], b: number[]) => a[0] - b[0]),
  );
  await closeDialog(page);
  await page.reload();
  await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
  await page.locator(".workflow-node").filter({ hasText: "Fit PCA Transform" }).first().click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  expect(await downloadTable(page, page.getByRole("dialog"))).toEqual(csv);
  await closeDialog(page);
  await page.goto(`/report?workflow=${workflow.id}&run=${result.run_id}&project=${project.id}`);
  const frame = page.frameLocator('iframe[title="Report preview"]');
  await expect(frame.locator("body")).toContainText(workflow.name);
  await expect(frame.locator("body")).toContainText("150");
  await expect(frame.locator("body")).not.toContainText("[object Object]");
  const preview = await page.locator('iframe[title="Report preview"]').getAttribute("srcdoc");
  expect(preview).toBeTruthy();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("menuitem", { name: "HTML Report" }).click();
  const saved = await download;
  expect(await readFile((await saved.path())!, "utf8")).toBe(preview);
  // Offline parity is exact HTML, not merely a similarly labelled second report.
  await test.info().attach("iris-report.html", { body: preview!, contentType: "text/html" });
});
