import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";
import { assertDefaultDisplayMatrix, closeDialog } from "./assertions";
import { createDataset, instantiate, runWorkflow, EXECUTION_TIMEOUT_MS } from "./journeys";

test("source exclusions stay absent; workflow exclusions remain blank inspectable rows @smoke", async ({ page, request }) => {
  const name = "mixture-ir";
  const expected = JSON.parse(readFileSync(new URL(`./fixtures/${name}.json`, import.meta.url), "utf8"));
  const dataset = await createDataset(request, name);
  const workflow = await instantiate(request, dataset, "pca");
  const first = await runWorkflow(page, workflow, dataset.project);
  expect(first.results.data_1.default.data).toHaveLength(22);
  const eligible = expected.labels.filter((_: string, index: number) => expected.included[index]);
  const inspect = async (node: string, computed: number) => {
    await page.locator(".workflow-node").filter({ hasText: node }).first().click();
    await page.getByRole("button", { name: "View Data", exact: true }).click();
    const dialog = page.getByRole("dialog");
    const rows = dialog.locator("tbody tr");
    await expect(rows).toHaveCount(22);
    await expect(dialog).not.toContainText(`${name}-02`);
    await expect(dialog).not.toContainText(`${name}-23`);
    const headers = await dialog.locator("th").allTextContents();
    expect(headers.slice(0, 2).map(text => text.trim())).toEqual(["", ""]);
    const labelIndex = headers.findIndex(text => ["Sample", "Label"].includes(text.trim()));
    expect(labelIndex).toBeGreaterThanOrEqual(2);
    const labels = await rows.evaluateAll((elements, index) => elements.map(row => row.querySelectorAll("td")[index].textContent?.trim()), labelIndex);
    expect(labels).toEqual(eligible);
    await expect(dialog.getByRole("img", { name: "Used in this result", exact: true })).toHaveCount(computed);
    return dialog;
  };
  let dialog = await inspect("Load Data", 22);
  // The native control uses the exact source reference; labels only locate the
  // user's intended row, never establish scientific/navigation identity.
  await dialog.getByRole("button", { name: `Exclude ${eligible[0]}.`, exact: true }).click();
  await closeDialog(page);
  const executed = page.waitForResponse(response => response.url().endsWith(`/workflows/${workflow.id}/execute`)
    && response.request().method() === "POST", { timeout: EXECUTION_TIMEOUT_MS });
  await page.locator('[data-action="run_workflow"]').click();
  const response = await executed;
  expect(response.ok(), await response.text()).toBeTruthy();
  const second = await response.json();
  expect(second.status, second.error).toBe("completed");
  expect(second.results.model_1.scores.data).toHaveLength(21);
  const sourceRows = second.results.data_1.exclusions.rows;
  expect(sourceRows.filter((row: { source_included: boolean }) => !row.source_included)).toHaveLength(2);
  expect(sourceRows.filter((row: { source_included: boolean; workflow_excluded: boolean }) => row.source_included && row.workflow_excluded)).toHaveLength(1);
  dialog = await inspect("Fit PCA Transform", 21);
  const blankRow = dialog.locator("tbody tr").first();
  expect((await blankRow.locator("td").allTextContents()).slice(-3).map(text => text.trim())).toEqual(["-", "-", "-"]);
  const computedCells = await dialog.locator("tbody tr").evaluateAll(rows => rows.slice(1).map(row =>
    Array.from(row.querySelectorAll("td")).slice(-3).map(cell => cell.textContent?.trim() ?? "")));
  assertDefaultDisplayMatrix(computedCells, second.results.model_1.scores.data);
  await dialog.screenshot({ path: test.info().outputPath("workflow-excluded-blank-row.png") });
  await expect(blankRow.getByRole("img", { name: "Not used in this result", exact: true })).toBeVisible();
  await expect(blankRow.getByRole("button", { name: `Restore ${eligible[0]}.`, exact: true })).toBeVisible();
  await closeDialog(page);
  await page.reload();
  await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
  await inspect("Fit PCA Transform", 21);
});
