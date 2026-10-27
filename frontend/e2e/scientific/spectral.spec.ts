import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
import {
  assertIdentity,
  assertMatrix,
  assertDefaultDisplayMatrix,
  assertSameScreenshot,
  settledPlotScreenshot,
  settledTableScreenshot,
  closeDialog,
  downloadTable,
  plotData,
} from "./assertions";
import AxeBuilder from "@axe-core/playwright";
import { createDataset, instantiate, runWorkflow } from "./journeys";

for (const name of ["mixture-ir", "moisture-nir"]) {
  test(`${name}: source inclusion and component orientation @smoke`, async ({ page, request }) => {
    const expected = JSON.parse(
      readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"),
    );
    const dataset = await createDataset(request, name);
    const {
      project,
      experiment,
      files: [file],
    } = dataset;
    await page.goto(
      `/data?project=${project.id}&experimentId=${experiment.id}&fileId=${file.id}&tab=my-dataset`,
    );
    await expect(page.getByRole("region", { name: "My Dataset", exact: true })).toBeVisible();
    await page.locator("summary").filter({ hasText: "Active dataset:" }).click();
    for (let index = 0; index < expected.labels.length; index++) {
      const checkbox = page
        .getByRole("checkbox", { name: `Include sample ${expected.labels[index]}`, exact: true })
        .first();
      await expect(checkbox).toBeVisible();
      if (expected.included[index]) await expect(checkbox).toBeChecked();
      else await expect(checkbox).not.toBeChecked();
    }
    const workflow = await instantiate(request, dataset, "pca");
    const result = await runWorkflow(page, workflow, project);
    const indices = expected.included.flatMap((included: boolean, i: number) =>
      included ? [i] : [],
    );
    const labels = indices.map((i: number) => expected.labels[i]);
    const values = indices.map((i: number) => expected.values[i]);
    const source = result.results.data_1.default;
    assertMatrix(source.data, values);
    assertIdentity(source.y_axis.labels, labels);
    expect(source.y_axis.include_mask).toEqual(labels.map(() => true));
    const membership = result.results.data_1.exclusions;
    expect(membership.source_count).toBe(expected.labels.length);
    expect(membership.active_count).toBe(labels.length);
    assertIdentity(membership.rows.map((row: { sample_label: string }) => row.sample_label), expected.labels);
    expect(membership.rows.map((row: { included: boolean }) => row.included)).toEqual(expected.included);
    expect(membership.rows.map((row: { source_included: boolean }) => row.source_included)).toEqual(expected.included);
    expect(membership.rows.map((row: { source_row: number }) => row.source_row)).toEqual(expected.labels.map((_: string, i: number) => i + 1));
    let resultRow = 0;
    expect(membership.rows.map((row: { result_row: number | null }) => row.result_row)).toEqual(
      expected.included.map((included: boolean) => included ? ++resultRow : null),
    );
    assertIdentity(result.results.inclusion_1.default.y_axis.labels, labels);
    assertMatrix(result.results.inclusion_1.default.data, values);
    await page.locator(".workflow-node").filter({ hasText: "Load Data" }).first().click();
    await page.getByRole("button", { name: "View Data", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator("tbody tr")).toHaveCount(22);
    await expect(dialog).not.toContainText("No data to display");
    await expect(dialog).toContainText(`${name}-01`);
    await expect(dialog).not.toContainText(`${name}-02`);
    await expect(dialog).not.toContainText(`${name}-23`);
    await expect(dialog).toContainText(`${name}-24`);
    const rows = await dialog
      .locator("tbody tr")
      .evaluateAll((rows) =>
        rows.map((row) =>
          Array.from(row.querySelectorAll("td"), (cell) => cell.textContent?.trim() ?? ""),
        ),
      );
    assertIdentity(
      rows.map((row) => row[1]),
      labels,
    );
    assertDefaultDisplayMatrix(
      rows.map((row) => row.slice(2)),
      values.map((row: number[]) => row.slice(0, 8)),
    );
    const csv = await downloadTable(page, dialog);
    const tableImage = await settledTableScreenshot(page, test.info().outputPath("table-before.png"));
    assertIdentity(
      csv.slice(1).map((row) => row[1]),
      labels,
    );
    assertMatrix(
      csv.slice(1).map((row) => row.slice(2).map(Number)),
      values,
    );
    const accessibility = await new AxeBuilder({ page })
      .include(".data-table-modal")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      accessibility.violations.map(({ id, nodes }) => ({
        id,
        targets: nodes.map((node) => node.target),
      })),
    ).toEqual([]);
    await closeDialog(page);
    await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
    await expect(
      page.getByRole("dialog").locator(".plotly-canvas .main-svg").first(),
    ).toBeVisible();
    const plot = await plotData(page.getByRole("dialog"));
    // The table/fit contain active rows; source plots also show excluded rows
    // as display-only traces. Keep both populations independently asserted.
    const observationTraces = plot.traces.filter((trace) => expected.labels.includes(trace.name));
    assertIdentity(
      observationTraces.map((trace) => trace.name),
      expected.labels,
    );
    assertMatrix(
      observationTraces.map((trace) => trace.y),
      expected.values,
    );
    assertMatrix(
      observationTraces.map((trace) => trace.x),
      expected.values.map(() => expected.axis),
    );
    expect(plot.traces.map((trace) => trace.name)).toContain("Excluded / not in fit");
    const roles = await page.getByRole("dialog").locator(".plotly-canvas").first().evaluate((el) => {
      const graph = el as HTMLElement & { data: Array<{
        name: string; line?: { dash?: string }; meta?: { workflow_excluded?: boolean };
      }> };
      return graph.data.map((trace) => ({ name: trace.name, dash: trace.line?.dash, meta: trace.meta }));
    });
    // Numerical parity alone cannot establish that excluded rows are visibly
    // distinguished from observations used for fitting.
    for (let i = 0; i < expected.labels.length; i++) {
      const trace = roles.find((trace) => trace.name === expected.labels[i]);
      expect(trace).toBeDefined();
      if (!expected.included[i]) expect(trace?.dash).toBe("dot");
      else expect(trace?.dash).not.toBe("dot");
    }
    expect(plot.xTitle).toBe(name === "mixture-ir" ? "Wavenumber (cm-1)" : "Wavelength (nm)");
    await closeDialog(page);
    // Reopening must read the retained result, not refit or use a current draft.
    await page.reload();
    await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
    await page.locator(".workflow-node").filter({ hasText: "Load Data" }).first().click();
    await page.getByRole("button", { name: "View Data", exact: true }).click();
    expect(await downloadTable(page, page.getByRole("dialog"))).toEqual(csv);
    await assertSameScreenshot(
      page,
      tableImage,
      await settledTableScreenshot(page, test.info().outputPath("table-reopened.png")),
    );
    await closeDialog(page);
    await page.locator(".workflow-node").filter({ hasText: "Fit PCA Transform" }).first().click();
    await page.locator("#scientific-presentation").click();
    await page.getByRole("option", { name: "Loadings", exact: true }).click();
    await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
    const loadings = await plotData(page.getByRole("dialog"));
    expect(loadings.traces).toHaveLength(3);
    assertMatrix(
      loadings.traces.map((trace) => trace.x),
      [expected.axis, expected.axis, expected.axis],
    );
    assertMatrix(
      loadings.traces.map((trace) => trace.y),
      result.results.model_1.loadings.data,
    );
    expect(loadings.xTitle).toBe(plot.xTitle);
    const componentImage = await settledPlotScreenshot(
      page,
      test.info().outputPath("components-before.png"),
    );
    await test
      .info()
      .attach(`${name}-components.png`, { body: componentImage, contentType: "image/png" });
    const plotAccessibility = await new AxeBuilder({ page })
      .include(".quick-plot-modal")
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    expect(
      plotAccessibility.violations.map(({ id, nodes }) => ({
        id,
        targets: nodes.map((node) => node.target),
      })),
    ).toEqual([]);
    await closeDialog(page);
    await page.getByRole("button", { name: "View Data", exact: true }).click();
    await expect(page.getByRole("dialog")).not.toContainText("No data to display");
    const componentCsv = await downloadTable(page, page.getByRole("dialog"));
    expect(componentCsv[0]).toEqual(["Index", "Label", ...expected.axis.map(String)]);
    assertIdentity(
      componentCsv.slice(1).map((row) => row[1]),
      result.results.model_1.loadings.y_axis.labels,
    );
    assertMatrix(
      componentCsv.slice(1).map((row) => row.slice(2).map(Number)),
      result.results.model_1.loadings.data,
    );
    await closeDialog(page);
    await page.reload();
    await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
    await page.locator(".workflow-node").filter({ hasText: "Fit PCA Transform" }).first().click();
    await page.locator("#scientific-presentation").click();
    await page.getByRole("option", { name: "Loadings", exact: true }).click();
    await page.getByRole("button", { name: "Quick Plot", exact: true }).click();
    expect(await plotData(page.getByRole("dialog"))).toEqual(loadings);
    const reopenedImage = await settledPlotScreenshot(
      page,
      test.info().outputPath("components-reopened.png"),
    );
    await assertSameScreenshot(page, componentImage, reopenedImage);
  });
}
