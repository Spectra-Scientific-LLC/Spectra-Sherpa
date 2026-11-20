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
    await page.getByRole("button", { name: "Export", exact: true }).click();
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
});
