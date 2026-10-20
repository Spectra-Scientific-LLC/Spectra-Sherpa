import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "../scientific/journeys";
import {
  assertIdentity,
  assertMatrix,
  closeDialog,
  downloadTable,
  plotData,
} from "../scientific/assertions";

test("Lavender: SIMPLISMA is component spectra against retained wavenumber", async ({
  request,
  page,
}) => {
  const dataset = await createDataset(request, "Lavender", {
    source: "builtin",
    name: "lavender-essential-oil-v1",
  });
  const workflow = await instantiate(request, dataset, "simplisma");
  const result = await runWorkflow(page, workflow, dataset.project);
  const spectra = result.results.model_1.spectra;
  expect(spectra.shape).toEqual([3, 1868]);
  await page
    .locator(".workflow-node")
    .filter({ hasText: "Fit SIMPLISMA Pure Components" })
    .first()
    .click();
  await page.locator("#scientific-presentation").click();
  await page.getByRole("option", { name: "Pure Spectra", exact: true }).click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  const csv = await downloadTable(page, page.getByRole("dialog"));
  await expect(page.getByRole("dialog").locator("tbody tr")).toHaveCount(3);
  assertMatrix(
    csv.slice(1).map((row) => row.slice(2).map(Number)),
    spectra.data,
  );
  await closeDialog(page);
  await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
  const plot = await plotData(page.getByRole("dialog"));
  expect(plot.traces).toHaveLength(3);
  assertMatrix(
    plot.traces.map((trace) => trace.y),
    spectra.data,
  );
  assertMatrix(
    plot.traces.map((trace) => trace.x),
    spectra.data.map(() => spectra.x_axis.data),
  );
  expect(plot.xTitle).toMatch(/Wavenumber.*cm/);
  expect(plot.traces.every((trace) => trace.mode.includes("lines"))).toBeTruthy();
});

test("Corn: registered M5 Moisture import, PLS and held-out identities", async ({
  request,
  page,
}) => {
  const archive = process.env.CORN_ARCHIVE_PATH;
  expect(
    archive,
    "Explicit qualification requires CORN_ARCHIVE_PATH; never download or silently skip",
  ).toBeTruthy();
  const project = await (
    await request.post("/api/v1/projects", { data: { name: "Acceptance — Corn provider" } })
  ).json();
  const experiment = await (
    await request.post("/api/v1/experiments", {
      data: { name: "Corn M5", project_id: project.id },
    })
  ).json();
  const imported = await request.post(
    `/api/v1/experiments/${experiment.id}/import-registered-reference`,
    {
      multipart: {
        projection_id: "public-corn-m5-moisture-v1",
        file: { name: "corn.zip", mimeType: "application/zip", buffer: readFileSync(archive!) },
      },
    },
  );
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const { files } = await imported.json();
  const selection = await request.put(`/api/v1/experiments/${experiment.id}/analysis-selection`, {
    data: { selected_target: "Moisture", target_type: "continuous" },
  });
  expect(selection.ok(), await selection.text()).toBeTruthy();
  const workflow = await instantiate(request, { project, experiment, files }, "pls_calibration");
  const result = await runWorkflow(page, workflow, project);
  const split = result.results.partition_1;
  expect(split.X_train.data.length + split.X_test.data.length).toBe(80);
  expect(split.X_test.data).toHaveLength(20);
  assertIdentity(
    [...split.X_train.y_axis.labels, ...split.X_test.y_axis.labels].sort(),
    [...result.results.data_1.default.y_axis.labels].sort(),
  );
  expect(split.X_test.target_context?.target_units ?? null).toBe(
    result.results.data_1.default.target_context?.target_units ?? null,
  );
  await page.locator(".workflow-node").filter({ hasText: "Train/Test Split" }).first().click();
  await page.locator("#scientific-presentation").click();
  await page.getByRole("option", { name: "Test Data", exact: true }).click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  const csv = await downloadTable(page, page.getByRole("dialog"));
  await expect(page.getByRole("dialog").locator("tbody tr")).toHaveCount(20);
  assertIdentity(
    csv.slice(1).map((row) => row[1]),
    split.X_test.y_axis.labels,
  );
  assertMatrix(
    csv.slice(1).map((row) => row.slice(2).map(Number)),
    split.X_test.data,
  );
  await closeDialog(page);
  await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
  const plot = await plotData(page.getByRole("dialog"));
  const spectra = plot.traces.filter(
    (trace) =>
      !(trace.x.length === 1 && trace.x[0] === null && trace.y.length === 1 && trace.y[0] === null),
  );
  assertIdentity(
    spectra.map((trace) => trace.name),
    split.X_test.y_axis.labels,
  );
  assertMatrix(
    spectra.map((trace) => trace.y),
    split.X_test.data,
  );
  assertMatrix(
    spectra.map((trace) => trace.x),
    split.X_test.data.map(() => split.X_test.x_axis.data),
  );
  expect(plot.xTitle).toMatch(/Wavelength.*nm/);
  await closeDialog(page);
  await page.reload();
  await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
  await page.locator(".workflow-node").filter({ hasText: "Train/Test Split" }).first().click();
  await page.locator("#scientific-presentation").click();
  await page.getByRole("option", { name: "Test Data", exact: true }).click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  expect(await downloadTable(page, page.getByRole("dialog"))).toEqual(csv);
});
