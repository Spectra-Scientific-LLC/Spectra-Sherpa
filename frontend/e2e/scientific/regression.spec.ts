import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";
import { assertIdentity, assertMatrix, assertRegressionReport, closeDialog, downloadTable, plotData } from "./assertions";

test("Synthetic moisture: PLS preserves held-out identity and response units @smoke", async ({
  request,
  page,
}) => {
  const expected = JSON.parse(
    readFileSync(new URL("./fixtures/moisture-nir.json", import.meta.url), "utf8"),
  );
  const dataset = await createDataset(request, "moisture-nir");
  const selection = await request.put(
    `/api/v1/experiments/${dataset.experiment.id}/analysis-selection`,
    {
      data: { selected_target: "Moisture", target_type: "continuous" },
    },
  );
  expect(selection.ok(), await selection.text()).toBeTruthy();
  const workflow = await instantiate(request, dataset, "pls_calibration");
  const result = await runWorkflow(page, workflow, dataset.project);
  expect(result.results.eval_1.default.population_authority.role).toBe("held_out_test");
  expect(result.results.eval_1.default.population_authority.qualification).toBe("graph_verified");
  const split = result.results.partition_1;
  const train = split.X_train.y_axis.labels;
  const heldOut = split.X_test.y_axis.labels;
  const all = [...train, ...heldOut].sort();
  assertIdentity(
    all,
    expected.labels.filter((_: string, i: number) => expected.included[i]).sort(),
  );
  expect(train.filter((label: string) => heldOut.includes(label))).toEqual([]);
  expect(split.X_test.target_context.target_units).toBe("wt %");
  await page.locator(".workflow-node").filter({ hasText: "Train/Test Split" }).first().click();
  await page.locator("#scientific-presentation").click();
  await page.getByRole("option", { name: "Test Data", exact: true }).click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  const csv = await downloadTable(page, page.getByRole("dialog"));
  assertIdentity(
    csv.slice(1).map((row) => row[1]),
    heldOut,
  );
  assertMatrix(
    csv.slice(1).map((row) => row.slice(2).map(Number)),
    split.X_test.data,
  );
  await closeDialog(page);
  await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
  const plot = await plotData(page.getByRole("dialog"));
  // Null-coordinate traces carry the metadata legend, not extra observations.
  const spectra = plot.traces.filter(
    (trace) =>
      !(trace.x.length === 1 && trace.x[0] === null && trace.y.length === 1 && trace.y[0] === null),
  );
  assertIdentity(
    spectra.map((trace) => trace.name),
    heldOut,
  );
  assertMatrix(
    spectra.map((trace) => trace.y),
    split.X_test.data,
  );
  await closeDialog(page);
  const comparison = result.results.eval_1.comparison.data;
  assertIdentity(
    comparison.map((row: { sample: string }) => row.sample),
    heldOut,
  );
  const reference = heldOut.map((label: string) => expected.target[expected.labels.indexOf(label)]);
  assertMatrix(
    comparison.map((row: { reference: number; predicted: number }) => [
      row.reference,
      row.predicted,
    ]),
    reference.map((value: number) => [value, value]),
    1e-8,
  );
  expect(result.results.eval_1.default.n_samples).toBe(heldOut.length);
  // Synthetic response is an exact linear combination, not a provider benchmark.
  expect(result.results.eval_1.default.r2).toBeCloseTo(1, 8);
  await page.goto(
    `/report?workflow=${workflow.id}&run=${result.run_id}&project=${dataset.project.id}`,
  );
  const body = page.frameLocator('iframe[title="Report preview"]').locator("body");
  await assertRegressionReport(page, {
    training: train.length,
    heldOut: csv.length - 1,
    rmse: result.results.eval_1.default.rmse,
  });
  await expect(body).toContainText("Moisture");
  await expect(body).toContainText("wt %");
  await expect(body).not.toContainText("[object Object]");
  const preview = await page.locator('iframe[title="Report preview"]').getAttribute("srcdoc");
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page.getByRole("menuitem", { name: "HTML Report" }).click();
  expect(await readFile((await (await downloaded).path())!, "utf8")).toBe(preview);
});
