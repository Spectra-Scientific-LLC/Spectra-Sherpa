import { test, expect } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";

test("new measured tables use Settings format and large plates have one keyboard entry", async ({ page, request }) => {
  const dataset = await createDataset(request, "Plate preference", { source: "sklearn", name: "iris" });
  const preferences = await request.put("/api/v1/acquisition-preferences", { data: { default_plate_format_id: "plate-1536" } });
  expect(preferences.ok(), await preferences.text()).toBeTruthy();
  await page.goto(`/data?project=${dataset.project.id}&experimentId=${dataset.experiment.id}&fileId=${dataset.files[0].id}&tab=my-dataset`);
  await page.getByRole("checkbox", { name: "Preview sklearn_iris.csv", exact: true }).check();
  await page.getByRole("button", { name: "sklearn_iris.csv", exact: true }).click();
  const focused = page.locator(".focused-dataset-details");
  if (await focused.getAttribute("open") === null) await focused.locator(":scope > summary").click();
  await page.getByRole("button", { name: "Edit measured samples", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Measured samples", exact: true });
  await expect(editor.locator("#plate-format")).toContainText("1536-well plate");
  await expect(editor.locator("#plate-end")).toContainText("AF48");
  await editor.getByRole("button", { name: "Assign", exact: true }).click();
  const plate = editor.locator(".plate-viewport");
  await expect(plate.locator('.well[tabindex="0"]')).toHaveCount(1);
  await plate.locator(".well").first().focus();
  await page.keyboard.press("ArrowDown");
  await expect(plate.locator(".well:focus .well-position")).toHaveText("B01");
  await page.keyboard.press("Control+End");
  await expect(plate.locator(".well:focus .well-position")).toHaveText("D06");
  await expect(plate.locator('.well[tabindex="0"]')).toHaveCount(1);
  await editor.getByRole("button", { name: "Cancel", exact: true }).click();
  await request.put("/api/v1/acquisition-preferences", { data: { default_plate_format_id: "plate-96" } });
});

for (const alias of ["project", "project_id"]) {
  test(`Data ${alias} link yields to explicit project selection across reload and Back`, async ({ page, request }) => {
    const first = await createDataset(request, `Copy first ${alias}`, { source: "sklearn", name: "iris" });
    const second = await createDataset(request, `Copy second ${alias}`, { source: "sklearn", name: "iris" });
    await page.goto(`/data?${alias}=${first.project.id}&tab=upload`);
    await expect(page.locator(".project-value")).toHaveText(first.project.name);
    await expect(page.locator(".workspace-header").getByRole("button", { name: "Load", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Add scientific files", exact: true })).toHaveCount(0);
    await page.locator(".project-dropdown").click();
    await page.getByRole("option", { name: new RegExp(second.project.name) }).click();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await expect.poll(() => new URL(page.url()).searchParams.has(alias)).toBe(false);
    await page.reload();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await page.getByRole("link", { name: "Documentation", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Documentation", exact: true })).toBeVisible();
    await page.goBack();
    await expect(page.locator(".project-value")).toHaveText(second.project.name);
    await expect.poll(() => new URL(page.url()).searchParams.has(alias)).toBe(false);
  });
}

test("workspace sections keep actions and context without duplicate introductions", async ({ page, request }, testInfo) => {
  const { project, experiment } = await createDataset(request, "Copy layout", { source: "sklearn", name: "iris" });
  for (const [tab, removed] of [
    ["upload", "Add scientific files"], ["import", "Reference Datasets"],
    ["library", "Reference Library"], ["multi-well", "Multi-well experiment"],
    ["synthesis", "FTIR Synthesis"],
  ]) {
    await page.goto(`/data?project=${project.id}&tab=${tab}`);
    await expect(page.getByRole("heading", { name: "Data", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: removed, exact: true })).toHaveCount(0);
    const header = page.locator(".workspace-header");
    await expect(header.getByRole("button", { name: "My Dataset", exact: true })).toBeVisible();
    await expect(header.getByRole("button", { name: "Workflow", exact: true })).toHaveCount(0);
    if (tab === "upload") {
      await expect(header.getByRole("button", { name: "Load", exact: true })).toBeVisible();
      await expect(page.getByText("Files, folders or ZIPs.", { exact: true })).toHaveCount(0);
      await testInfo.attach("upload-reduced", { body: await page.screenshot(), contentType: "image/png" });
    }
    if (tab === "library" || tab === "synthesis") {
      await expect(header.getByRole("button", { name: "Guide", exact: true })).toBeVisible();
    }
    if (tab === "multi-well") {
      await expect(page.locator('[aria-label="Data workspace context"]')).toContainText(experiment.name);
      await expect(page.locator('[aria-label="Data workspace context"]')).toContainText("0 wells configured");
      await expect(page.getByRole("button", { name: "Save acquisition plan", exact: true })).toHaveCount(0);
    }
  }
  await page.goto("/runs?tab=batch");
  await expect(page.getByRole("heading", { name: "Batch", exact: true })).toHaveCount(0);
  await expect(page.getByRole("radio", { name: "Apply trained model — no refit" })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Run workflow — train/evaluate" })).toBeVisible();
  await page.goto("/runs?tab=inspect");
  await expect(page.getByRole("heading", { name: "Inspect", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Open History", exact: true })).toBeVisible();
  const inspect = page.getByRole("region", { name: "Inspect", exact: true }).locator(".workspace-state--page");
  const inspectStyle = await inspect.evaluate(element => {
    const state = getComputedStyle(element), message = getComputedStyle(element.querySelector("p")!);
    return { padding: state.padding, gap: state.gap, size: message.fontSize, weight: message.fontWeight };
  });
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  const compare = page.getByRole("region", { name: "Compare", exact: true }).locator(".workspace-state--page");
  await expect(compare).toBeVisible();
  expect(await compare.evaluate(element => {
    const state = getComputedStyle(element), message = getComputedStyle(element.querySelector("p")!);
    return { padding: state.padding, gap: state.gap, size: message.fontSize, weight: message.fontWeight };
  })).toEqual(inspectStyle);
  await page.getByRole("button", { name: "Models", exact: true }).click();
  for (const section of ["Local Model History", "Saved Models", "Imported Models"]) {
    await expect(page.getByRole("button", { name: section, exact: true })).toBeVisible();
  }
  await page.goto("/report?tab=preview");
  await expect(page.getByText("Choose inputs in Setup, then generate the report.", { exact: true })).toBeVisible();
  await expect(page.getByText("Select a workflow to generate a report", { exact: true })).toHaveCount(0);
});

test("Inspect opens its exact fitted model under Models without promoting it", async ({ page, request }) => {
  const dataset = await createDataset(request, "Model navigation", { source: "sklearn", name: "iris" });
  const workflow = await instantiate(request, dataset, "pca");
  const result = await runWorkflow(page, workflow, dataset.project);
  const evidence = await request.get(`/api/v1/runs/${result.run_id}/evidence`, { params: { project_id: dataset.project.id } });
  expect(evidence.ok(), await evidence.text()).toBeTruthy();
  const { run } = await evidence.json();
  expect(run.produced_artifact_uids).toHaveLength(1);
  const uid = run.produced_artifact_uids[0];
  const modelResponse = await request.get(`/api/v1/models/${encodeURIComponent(uid)}`);
  expect(modelResponse.ok(), await modelResponse.text()).toBeTruthy();
  const model = await modelResponse.json();
  await page.goto(`/runs/${result.run_id}?tab=inspect&project=${dataset.project.id}`);
  const inspect = page.getByRole("region", { name: "Inspect", exact: true });
  const header = page.locator('.workspace-header');
  await expect(inspect.getByRole("button", { name: "Review for promotion", exact: true })).toHaveCount(0);
  await expect(inspect.getByRole("button", { name: "Open model", exact: true })).toHaveCount(0);
  await expect(header.getByRole('button', { name: 'Back to Runs', exact: true })).toBeVisible();
  await expect(header.getByRole('button', { name: /^Workflow/ })).toBeVisible();
  await expect(header.getByRole('button', { name: 'Report', exact: true })).toBeVisible();
  await expect(header.getByRole('button', { name: 'Open Deploy', exact: true })).toBeVisible();
  const exportBox = await header.getByRole('button', { name: 'Export', exact: true }).boundingBox();
  const modelBox = await header.getByRole('button', { name: 'Open model', exact: true }).boundingBox();
  expect(Math.abs(modelBox!.y + modelBox!.height / 2 - exportBox!.y - exportBox!.height / 2)).toBeLessThanOrEqual(1);
  await expect(inspect.locator('.plotly-canvas .main-svg').first()).toBeVisible();
  const panels = inspect.locator('.p-panel');
  expect(await panels.evaluateAll(elements => new Set(elements.map(element => element.getBoundingClientRect().left)).size)).toBe(1);
  await test.info().attach('inspect-sections.png', { body: await page.screenshot(), contentType: 'image/png' });
  await expect(inspect.getByRole('button', { name: 'Results', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await inspect.getByRole('button', { name: 'Validation', exact: true }).click();
  await expect(inspect.getByRole('button', { name: 'Results', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await expect(inspect.getByRole('button', { name: 'Validation', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await inspect.getByRole('button', { name: 'Summary', exact: true }).click();
  await expect(inspect.getByRole('button', { name: 'Summary', exact: true })).toHaveAttribute('aria-expanded', 'true');
  await page.setViewportSize({ width: 700, height: 1000 });
  await header.getByRole('button', { name: 'Actions', exact: true }).click();
  await page.getByRole('menuitem', { name: 'Open model', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await expect.poll(() => new URL(page.url()).searchParams.get("artifact")).toBe(uid);
  expect(new URL(page.url()).pathname).toBe("/runs");
  for (let reopen = 0; reopen < 2; reopen++) {
    if (reopen) await page.reload();
    await expect(page.getByRole("button", { name: "Models", exact: true })).toHaveAttribute("aria-current", "true");
    await expect(page.locator("#selected-model-detail")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Model name", exact: true })).toHaveValue(model.display_name || model.name);
    await expect(page.locator("#selected-model-detail").getByRole("button", { name: model.is_deploy_ready ? "Withdraw deploy-ready" : "Review for promotion", exact: true })).toBeVisible();
  }
  const after = await request.get(`/api/v1/models/${encodeURIComponent(uid)}`);
  expect((await after.json()).is_deploy_ready).toBe(model.is_deploy_ready);
});
