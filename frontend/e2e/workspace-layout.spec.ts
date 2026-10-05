import { test, expect } from "@playwright/test";

// Run against an isolated local-mode backend serving the built frontend.
// Retained-run fixtures test navigation/layout without executing or changing user science.
test("Dashboard, Data and Runs preserve workspace flow", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const project = { id: 1, name: "Corn calibration", description: "Layout validation", metadata: {},
    experiments: [], workflows: [], models: [], scripts: [], children: [], advisor_channels: [], data_sources: [],
    experiment_count: 0, workflow_count: 1, model_count: 0, script_count: 0, children_count: 0,
    updated_at: new Date(Date.now() - 86_400_000).toISOString(), created_at: "2026-09-01T12:00:00Z" };
  const run = { id: 42, project_id: 1, workflow_id: 7, name: "Corn PLS calibration", status: "completed",
    run_kind: "training", executed_at: "2026-10-02T12:00:00Z", labels: [], results_summary: {}, node_statuses: {},
    params_snapshot: {}, diagnostics: {}, produced_artifact_uids: [], attempted_artifact_uids: [], succeeded_artifact_uids: [] };
  const secondRun = { ...run, id: 43, name: "Corn PLS repeat" };
  await page.route("**/api/v1/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    let data: unknown;
    if (path === "/projects") data = url.searchParams.get("archived") === "true" ? [{ ...project, id: 2, name: "Archived calibration" }] : [project];
    else if (path === "/projects/1") data = project;
    else if (path === "/runs") data = { runs: [run, secondRun], total: 2 };
    else if (path === "/runs/compare") data = {
      runs: [run, secondRun], metric_keys: [], diff: {}, rankable_metric_keys: [],
      result_pairs: [{ left_run_id: 42, right_run_id: 43, kind: "out_of_fold_evaluation",
        state: "ambiguous", requires_pairing: true, left: [], right: [], reason: "Multiple results" }],
    };
    else if (path === "/models") data = [];
    else if (path === "/experiments") data = [];
    else if (path === "/runs/42/evidence") data = {
      run, notes: "Retained calibration record", integrity_hash: "saved-workflow-revision", node_statuses: {},
      environment_snapshot: { python: "3.11.14", backend_build_commit: "recorded-build", packages: { numpy: "1.26.4" } },
      evidence: { qualification: "incomplete", outputs: { __workflow__: { definition: { state: "exact", storage: "file" } } } },
      evidence_gaps: [{ node_id: "pls", output: "scores", state: "missing", category: "storage_limit",
        reason: "Scores not retained", recovery: "Re-run the saved workflow to retain scores" }],
    };
    else if (path === "/runs/42/outputs/__workflow__/definition") data = { value: { schema_version: 1, nodes: [], edges: [] } };
    if (data !== undefined) return route.fulfill({ json: data });
    return route.continue();
  });

  await page.goto("/dashboard");
  const dashboard = page.locator(".simplified-dashboard");
  await expect(dashboard.getByRole("tab")).toHaveText(["Your Project", "Archive", "Storage"]);
  const actions = dashboard.locator(".workspace-header .responsive-header-actions__full");
  const newAnalysis = await actions.getByRole("button", { name: "New Analysis", exact: true }).boundingBox();
  const projectButton = await actions.getByRole("button", { name: "Project", exact: true }).boundingBox();
  expect(projectButton!.x).toBeGreaterThan(newAnalysis!.x + newAnalysis!.width);
  expect(Math.abs(projectButton!.y - newAnalysis!.y)).toBeLessThan(2);
  await expect(dashboard.locator(".current-strip__time")).toBeVisible();
  const time = await dashboard.locator(".current-strip__time").boundingBox();
  const context = await dashboard.locator(".workspace-context").boundingBox();
  expect(Math.abs(time!.x + time!.width - context!.x - context!.width)).toBeLessThan(2);
  await dashboard.getByRole("tab", { name: "Archive", exact: true }).click();
  await expect(page).toHaveURL(/#archive$/);
  await expect(dashboard.getByText("Archived calibration", { exact: true })).toBeVisible();
  await page.reload();
  await expect(dashboard.getByRole("tab", { name: "Archive", exact: true })).toHaveAttribute("aria-selected", "true");

  await page.goto("/data?project=1");
  const datasetTab = page.getByRole("tab", { name: "My Dataset", exact: true });
  await expect(datasetTab).toBeVisible();
  const lastTab = await datasetTab.boundingBox();
  const nav = await page.locator(".data-content .p-tabview-nav").first().boundingBox();
  expect(Math.abs(lastTab!.x + lastTab!.width - nav!.x - nav!.width)).toBeLessThan(2);

  await page.goto("/runs?project=1&tab=run_history");
  const runs = page.locator(".models-content");
  await expect(runs.getByRole("tab")).toHaveText(["History", "Inspect", "Compare", "Artifacts", "Batch"]);
  await runs.getByText(run.name, { exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/42\?/);
  await expect(runs.getByRole("tab", { name: "Inspect", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(runs.locator(".run-detail__identity")).toContainText(run.name);
  await expect(runs.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();
  await expect(runs.getByRole("heading", { name: "Inspect", exact: true })).toBeVisible();
  const runActions = runs.getByRole("group", { name: "Run actions" });
  const boxes = await runActions.locator(":scope > button").evaluateAll(nodes => nodes.map(node => {
    const { x, y, width } = node.getBoundingClientRect(); return { x, y, width };
  }));
  expect(boxes.length).toBeGreaterThanOrEqual(4);
  for (let i = 1; i < boxes.length; i++) {
    expect(Math.abs(boxes[i].y - boxes[0].y)).toBeLessThan(2);
    expect(boxes[i].x).toBeGreaterThan(boxes[i - 1].x + boxes[i - 1].width);
  }
  await expect(runs.locator(".summary > :last-child")).toHaveAttribute("aria-label", "Incomplete durable evidence");
  await page.screenshot({ path: test.info().outputPath("inspect-desktop.png"), fullPage: true });
  await runs.getByRole("tab", { name: "History", exact: true }).click();
  await expect(page).toHaveURL(/\/runs\?/);
  await expect(runs.getByText(run.name, { exact: true })).toBeVisible();
  await runs.getByRole("tab", { name: "Inspect", exact: true }).click();
  await expect(runs.locator(".run-detail__identity")).toContainText(run.name);
  await page.reload();
  await expect(runs.getByRole("tab", { name: "Inspect", exact: true })).toHaveAttribute("aria-selected", "true");
  await runs.getByRole("button", { name: "Back to Runs", exact: true }).click();
  await expect(runs.getByRole("tab", { name: "History", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.goBack();
  await expect(runs.getByRole("tab", { name: "Inspect", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(runs.locator(".run-detail__identity")).toBeVisible();
  const overflow = await runs.locator(".run-detail").evaluate(node => {
    const right = node.getBoundingClientRect().right;
    return [...node.querySelectorAll('*')].filter(child => child.getBoundingClientRect().right > right + 1)
      .map(child => ({ tag: child.tagName, class: child.className, text: child.textContent?.slice(0, 60) }));
  });
  expect(overflow).toEqual([]);
  await runs.locator('.run-detail').screenshot({ path: test.info().outputPath("inspect-mobile.png") });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await runs.getByRole("tab", { name: "History", exact: true }).click();
  await runs.getByRole('row').filter({ hasText: run.name }).getByRole('checkbox').check();
  await runs.getByRole('row').filter({ hasText: secondRun.name }).getByRole('checkbox').check();
  await runs.getByRole('button', { name: 'Compare (2)', exact: true }).click();
  await expect(runs.getByRole('tab', { name: 'Compare', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(runs.locator('.comparison-matrix')).toBeVisible();
  await expect(runs.getByText('Result pairing', { exact: true })).toHaveCount(0);
  await expect(runs.locator('.result-correspondence')).toHaveCount(0);
  await expect(runs.locator('.qualification-note')).toContainText('ranking requires matching evaluation evidence');
  expect(errors).toEqual([]);
});
