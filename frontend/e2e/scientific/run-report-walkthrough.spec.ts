import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";
import { plotData } from "./assertions";

test("executed PCA results keep the title clear of tools and export the retained run @smoke", async ({ page, request }) => {
  const dataset = await createDataset(request, "Run and report walkthrough", { source: "sklearn", name: "iris" });
  const workflow = await instantiate(request, dataset, "pca");
  await page.addInitScript(() => localStorage.setItem("navCollapsed", "false"));
  const result = await runWorkflow(page, workflow, dataset.project);
  await page.goto(`/runs/${result.run_id}?project=${dataset.project.id}&tab=inspect&node=model_1`);
  const results = page.getByRole("region", { name: "Results", exact: true });
  const chart = results.locator(".plotly-chart");
  await expect(chart.locator(".gtitle")).toHaveText("PCA Summary");
  const retainedPlot = await plotData(chart);
  for (const width of [1027, 871]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect.poll(() => chart.evaluate(element => {
      const title = element.querySelector(".gtitle")!.getBoundingClientRect();
      const tools = element.querySelector(".modebar")!.getBoundingClientRect();
      return title.top >= tools.bottom || title.bottom <= tools.top;
    })).toBe(true);
    expect(await plotData(chart)).toEqual(retainedPlot);
  }
  await page.screenshot({ path: test.info().outputPath("retained-pca-inspector.png") });
  await results.getByRole("button", { name: "View Data", exact: true }).click();
  await expect(results.locator("table")).toBeVisible();
  await expect(results.locator("table")).toContainText("PC1");
  await expect(results.locator("table")).toContainText("PC2");
  await page.goto(`/report?workflow=${workflow.id}&run=${result.run_id}&project=${dataset.project.id}`);
  const frame = page.frameLocator('iframe[title="Report preview"]');
  await expect(frame.getByText(`#${result.run_id} — completed`, { exact: true })).toBeVisible();
  const preview = await page.locator('iframe[title="Report preview"]').getAttribute("srcdoc");
  for (const name of ["HTML Report", "JSON Data (full evidence)"]) {
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Other formats", exact: true }).click();
    await page.getByRole("menuitem", { name, exact: true }).click();
    const content = await readFile((await (await download).path())!, "utf8");
    if (name === "HTML Report") expect(content).toBe(preview);
    else {
      const evidence = JSON.parse(content);
      expect(evidence.runs.map((run: { id: number }) => run.id)).toEqual([result.run_id]);
      expect(evidence.runs[0].status).toBe("completed");
      expect(evidence.workflow_id).toBe(workflow.id);
    }
  }
  const reportNav = page.getByRole("navigation", { name: "Workspace navigation" });
  await reportNav.getByRole("button", { name: "Exports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Exports", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Available formats" }).getByRole("button", { name: "HTML Report" })).toBeVisible();
  await page.getByRole("button", { name: "Open draft", exact: true }).click();
  await expect(page.locator('iframe[title="Report preview"]')).toHaveAttribute("srcdoc", preview!);
});

test("History compares explicit retained runs and can return to the same pair", async ({ page, request }) => {
  const dataset = await createDataset(request, "Scoped run comparison", { source: "sklearn", name: "iris" });
  const workflow = await instantiate(request, dataset, "pca");
  const id = async () => {
    const execution = await request.post(`/api/v1/workflows/${workflow.id}/execute`, { data: {}, timeout: 60000 });
    expect(execution.ok(), await execution.text()).toBeTruthy();
    const run = await execution.json();
    expect(run.status).toBe("completed");
    return run.run_id;
  };
  const first = await id();
  const second = await id();
  expect(first).not.toEqual(second);
  await page.goto(`/runs?project=${dataset.project.id}&section=run_history`);
  const header = page.locator(".workspace-page-header");
  const compare = header.getByRole("button", { name: "Compare runs", exact: true });
  await expect(compare).toBeDisabled();
  const rows = page.locator(".runs-table tbody tr");
  await expect(rows).toHaveCount(2);
  await rows.nth(0).getByRole("checkbox").check();
  await expect(compare).toBeDisabled();
  await rows.nth(1).getByRole("checkbox").check();
  const comparisonResponse = page.waitForResponse(response =>
    response.request().method() === "POST" && /\/runs\/compare$/.test(new URL(response.url()).pathname));
  await compare.click();
  const response = await comparisonResponse;
  expect(response.ok(), await response.text()).toBeTruthy();
  expect((await response.json()).runs.map((run: { id: number }) => run.id).sort()).toEqual([first, second].sort());
  await expect(page).toHaveURL(/section=compare/);
  const panel = page.getByRole("region", { name: "Compare", exact: true });
  await expect(panel.getByRole("region", { name: "Scientific comparison", exact: true }).getByText(/^Unavailable: calibration, training cv/)).toBeVisible();
  await header.getByRole("button", { name: "Actions", exact: true }).click();
  await page.getByRole("menuitem", { name: "Change runs", exact: true }).click();
  await expect(panel.getByRole("checkbox", { checked: true })).toHaveCount(2);
  await expect(compare).toBeEnabled();
});

test("PLS-DA reopens the held-out specimen ledger and its actual classes", async ({ page, request }) => {
  const dataset = await createDataset(request, "Iris classification", { source: "sklearn", name: "iris" });
  const selected = await request.put(`/api/v1/experiments/${dataset.experiment.id}/analysis-selection`, {
    data: { selected_target: "target", target_type: "categorical" },
  });
  expect(selected.ok(), await selected.text()).toBeTruthy();
  const workflow = await instantiate(request, dataset, "classification_plsda");
  const result = await runWorkflow(page, workflow, dataset.project);
  const savedRows = result.results.eval_1.comparison.data as { sample: string; reference: string; predicted: string; role: string }[];
  expect(savedRows.length).toBeGreaterThan(0);
  expect(new Set(savedRows.map(row => row.role))).toEqual(new Set(["held_out_test"]));
  expect(new Set(savedRows.map(row => row.reference)).size).toBe(3);
  await page.goto(`/runs/${result.run_id}?project=${dataset.project.id}&node=eval_1&view=samples&presentation=sample_comparison`);
  const ledger = page.getByRole("region", { name: "Validation ledger", exact: true });
  await expect(ledger).toBeVisible();
  await expect(page.locator(".workspace-page-role")).toHaveText("Held-out evaluation");
  const firstSample = ledger.getByRole("row").filter({ has: page.getByRole("cell", { name: savedRows[0].sample, exact: true }) });
  await expect(firstSample).toBeVisible();
  const retainedCells = await firstSample.getByRole("cell").allTextContents();
  expect(retainedCells).toEqual(expect.arrayContaining([savedRows[0].sample, savedRows[0].reference, savedRows[0].predicted]));
  await page.reload();
  await expect(firstSample).toBeVisible();
  expect(await firstSample.getByRole("cell").allTextContents()).toEqual(retainedCells);
  await page.screenshot({ path: test.info().outputPath("held-out-classification.png") });
});
