import { readFileSync } from "node:fs";
import { test, expect, type APIRequestContext } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";

// This is a transport-controlled UI race, not qualification of NIST data or
// synthesis science. No provider is contacted and no synthetic file is claimed.
test("editing a synthesis draft keeps its accepted save single-flight and acknowledges the captured name", async ({
  page, request,
}) => {
  const dataset = await createDataset(request, "Iris synthesis destination", { source: "sklearn", name: "iris" });
  const source = "nist_quant_ir";
  const component = {
    id: "original-ui-fixture", name: "Original UI fixture", source,
    formula: "fixture", variants: [{ resolution_cm1: 1, apodization: "Blackman-Harris" }],
  };
  const submitted: Array<{ name: string; project_id: number }> = [];
  let release!: () => void, received!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const intercepted = new Promise<void>(resolve => { received = resolve; });
  let refreshes = 0;
  page.on("request", req => {
    if (submitted.length && req.url().includes("/datasets/available")) refreshes++;
  });
  await page.route("**/api/v1/synthesis/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/sources")) return route.fulfill({ json: { sources: [{ id: source, label: "Fixture source", available: true }] } });
    if (path.endsWith("/search")) return route.fulfill({ json: { components: [component] } });
    if (path.endsWith("/spectrum")) return route.fulfill({ json: {
      component_id: component.id, name: component.name, source,
      wavenumber: [1000, 1001, 1002, 1003, 1004], intensity: [0, 0.1, 0.3, 0.1, 0],
      y_quantity: "absorption_coefficient", y_units: "fixture", resolution_cm1: 1,
    } });
    if (path.endsWith("/save")) {
      submitted.push(route.request().postDataJSON());
      received();
      await held;
      return route.fulfill({ json: { experiment_id: dataset.experiment.id } });
    }
    throw new Error(`Unexpected provider operation in UI-only test: ${path}`);
  });
  try {
    await page.goto(`/data?project=${dataset.project.id}&tab=synthesis`);
    const panel = page.locator(".synthesis-panel");
    await panel.getByRole("button", { name: "Add", exact: true }).click();
    await panel.locator('[data-action="synthesis_load_spectrum"]').click();
    const save = panel.locator('[data-action="synthesis_save_dataset"]');
    await expect(save).toBeEnabled();
    await panel.getByLabel("Dataset name", { exact: true }).fill("Captured synthesis");
    await save.click();
    await intercepted;
    await panel.getByLabel("Dataset name", { exact: true }).fill("Next draft");
    await expect(save).toBeDisabled();
    expect(submitted).toHaveLength(1);
    expect(submitted[0]).toMatchObject({ name: "Captured synthesis", project_id: dataset.project.id });
    release();
    await expect(page.getByText("Synthetic dataset saved", { exact: true })).toBeVisible();
    await expect(page.getByText(`Saved "Captured synthesis" in project ${dataset.project.id}`, { exact: true })).toBeVisible();
    await expect(panel.getByLabel("Dataset name", { exact: true })).toHaveValue("Next draft");
    await expect(save).toBeEnabled();
    await expect.poll(() => refreshes).toBeGreaterThan(0);
    expect(submitted).toHaveLength(1);
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

async function addMixture(request: APIRequestContext, project: { id: number; name: string }) {
  const created = await request.post("/api/v1/experiments", {
    data: { name: "mixture-ir scope", project_id: project.id },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const experiment = await created.json();
  const imported = await request.post(`/api/v1/experiments/${experiment.id}/files`, {
    multipart: {
      stage: "raw",
      file: {
        name: "mixture-ir.csv",
        mimeType: "text/csv",
        buffer: readFileSync(new URL("./fixtures/mixture-ir.csv", import.meta.url)),
      },
    },
  });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  return { project, experiment, files: [await imported.json()] };
}

test("a delayed dataset inspection cannot replace the newly selected dataset @smoke", async ({
  page,
  request,
}) => {
  const iris = await createDataset(request, "Iris dataset scope", {
    source: "sklearn",
    name: "iris",
  });
  const mixture = await addMixture(request, iris.project);
  const expected = JSON.parse(
    readFileSync(new URL("./fixtures/mixture-ir.json", import.meta.url), "utf8"),
  ) as { labels: string[]; included: boolean[] };
  const selectedCount = String(expected.included.filter(Boolean).length);
  let release!: () => void, received!: () => void, delivered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const intercepted = new Promise<void>((resolve) => {
    received = resolve;
  });
  const completed = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  let delay = true;
  await page.route("**/api/v1/builder/file-info", async (route) => {
    if (!delay || route.request().postDataJSON()?.experiment_id !== iris.experiment.id) {
      return route.continue();
    }
    delay = false;
    const response = await route.fetch();
    received();
    await held;
    await route.fulfill({ response });
    delivered();
  });
  try {
    await page.goto(
      `/data?project=${iris.project.id}&experimentId=${iris.experiment.id}&tab=my-dataset`,
    );
    await intercepted;
    await page.getByRole("button", { name: mixture.experiment.name, exact: true }).click();
    const heading = page.locator(".focused-dataset-details > summary");
    await expect(heading).toContainText("mixture-ir");
    await heading.click();
    const metadata = page.getByRole("region", {
      name: "Dataset metadata and quality",
      exact: true,
    });
    const count = metadata.locator(".meta-row").filter({ hasText: "Samples in selection" });
    await expect(count.locator(".meta-val")).toHaveText(selectedCount);
    release();
    await completed;
    await expect(heading).toContainText("mixture-ir");
    await expect(count.locator(".meta-val")).toHaveText(selectedCount);
    for (const [index, label] of expected.labels.entries()) {
      const mark = page
        .getByRole("checkbox", { name: `Include sample ${label}`, exact: true })
        .first();
      if (expected.included[index]) await expect(mark).toBeChecked();
      else await expect(mark).not.toBeChecked();
    }
  } finally {
    release();
    if (!delay) await completed;
    await page.unroute("**/api/v1/builder/file-info");
  }
});

test("cold multi-file inspection retains both sibling source inventories", async ({
  page,
  request,
}) => {
  const first = await createDataset(request, "mixture-ir");
  const [header, ...rows] = readFileSync(
    new URL("./fixtures/mixture-ir.csv", import.meta.url),
    "utf8",
  ).split("\n");
  const [schema, encoded] = header.split(",");
  expect(schema).toBe("#spectrasherpa-portable-csv/2");
  // Both the typed envelope and visible CSV carry identity. Rename both;
  // otherwise the canonical loader correctly refuses this second fixture.
  const envelope = Buffer.from(encoded, "base64url").toString("utf8")
    .replace(/mixture-ir-/g, "second-mixture-");
  const content = [
    `${schema},${Buffer.from(envelope).toString("base64url")}`,
    ...rows.map(row => row.replace(/mixture-ir-/g, "second-mixture-")),
  ].join("\n");
  const uploaded = await request.post(`/api/v1/experiments/${first.experiment.id}/files`, {
    multipart: {
      stage: "raw",
      file: { name: "second.csv", mimeType: "text/csv", buffer: Buffer.from(content) },
    },
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();
  await page.goto(
    `/data?project=${first.project.id}&experimentId=${first.experiment.id}&tab=my-dataset`,
  );
  const heading = page.locator(".focused-dataset-details > summary");
  await expect(heading).toContainText(first.experiment.name);
  await heading.click();
  const metadata = page.getByRole("region", { name: "Dataset metadata and quality", exact: true });
  const count = metadata.locator(".meta-row").filter({ hasText: "Samples in selection" });
  await expect(count.locator(".meta-val")).toHaveText("44");
  await expect(
    page.getByRole("checkbox", { name: "Include sample mixture-ir-01", exact: true }).first(),
  ).toBeChecked();
  await expect(
    page.getByRole("checkbox", { name: "Include sample second-mixture-01", exact: true }).first(),
  ).toBeChecked();
});

test("clicking the active sheet preserves its pending initial graph load", async ({
  page,
  request,
}) => {
  const iris = await createDataset(request, "Iris initial sheet scope", {
    source: "sklearn",
    name: "iris",
  });
  const workflow = await instantiate(request, iris, "pca");
  let release!: () => void, received!: () => void, delivered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const intercepted = new Promise<void>((resolve) => {
    received = resolve;
  });
  const completed = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  const pattern = `**/api/v1/workflows/${workflow.id}`;
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    received();
    await held;
    await route.fulfill({ response });
    delivered();
  });
  try {
    await page.goto(`/workflow?workflow_id=${workflow.id}&project_id=${iris.project.id}`);
    await intercepted;
    const sheet = page.locator(".sheet-tab.active");
    await expect(sheet).toContainText(workflow.name);
    await sheet.click();
    release();
    await completed;
    await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
    await expect(
      page.locator(".workflow-node").filter({ hasText: "Load Data" }).first(),
    ).toBeVisible();
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("switching sheets during retained Data View loading cannot open the previous run", async ({
  page,
  request,
}) => {
  const iris = await createDataset(request, "Iris retained scope", {
    source: "sklearn",
    name: "iris",
  });
  const mixture = await addMixture(request, iris.project);
  const first = await instantiate(request, iris, "pca");
  const second = await instantiate(request, mixture, "pca");
  const result = await runWorkflow(page, first, iris.project);
  await page.reload();
  await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
  let release!: () => void, received!: () => void, delivered!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const intercepted = new Promise<void>((resolve) => {
    received = resolve;
  });
  const completed = new Promise<void>((resolve) => {
    delivered = resolve;
  });
  const pattern = `**/api/v1/runs/${result.run_id}/outputs/**`;
  await page.route(pattern, async (route) => {
    const response = await route.fetch();
    received();
    await held;
    await route.fulfill({ response });
    delivered();
  });
  try {
    await page.locator(".workflow-node").filter({ hasText: "Load Data" }).first().click();
    await page.getByRole("button", { name: "View Data", exact: true }).click();
    await intercepted;
    await page.locator(".sheet-tab").filter({ hasText: second.name }).click();
    await expect(page.locator(".sheet-tab.active")).toContainText(second.name);
    await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
    release();
    await completed;
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.locator(".sheet-tab.active")).toContainText(second.name);
  } finally {
    release();
    await page.unroute(pattern);
  }
  await runWorkflow(page, second, iris.project);
  await page.locator(".workflow-node").filter({ hasText: "Load Data" }).first().click();
  await page.getByRole("button", { name: "View Data", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator("tbody tr")).toHaveCount(22);
  await expect(dialog).toContainText("mixture-ir-01");
  await expect(dialog).not.toContainText("No data to display");
});

test("leaving an accepted run preserves its successful sheet status without painting the new sheet", async ({
  page, request,
}) => {
  const iris = await createDataset(request, "Iris accepted run scope", {
    source: "sklearn", name: "iris",
  });
  const mixture = await addMixture(request, iris.project);
  const first = await instantiate(request, iris, "pca");
  const second = await instantiate(request, mixture, "pca");
  let release!: () => void, received!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const intercepted = new Promise<void>(resolve => { received = resolve; });
  let result: { status: string; run_id: number } | undefined;
  let executionRequests = 0;
  const pattern = `**/api/v1/workflows/${first.id}/execute`;
  await page.route(pattern, async route => {
    executionRequests += 1;
    const response = await route.fetch();
    expect(response.ok(), await response.text()).toBeTruthy();
    result = await response.json();
    received();
    await held;
    await route.fulfill({ response });
  });
  try {
    await page.goto(`/workflow?workflow_id=${first.id}&project_id=${iris.project.id}`);
    await page.getByRole("button", { name: /^Run(?:\s|$)/ }).first().click();
    await intercepted;
    expect(result?.status).toBe("completed");
    expect(result?.run_id).toBeGreaterThan(0);
    const origin = page.locator(".sheet-tab").filter({ hasText: first.name });
    const destination = page.locator(".sheet-tab").filter({ hasText: second.name });
    await expect(origin.locator(".pi-spinner")).toBeVisible();
    await destination.click();
    await expect(destination).toHaveClass(/active/);
    await expect(page.locator(".canvas-container")).toHaveAttribute("aria-busy", "false");
    release();
    await expect(origin.locator(".status-icon.success")).toBeVisible();
    await expect(origin.locator(".status-icon.error")).toHaveCount(0);
    await expect(destination.locator(".status-icon")).toHaveCount(0);
    await expect(destination).toHaveClass(/active/);
    expect(executionRequests).toBe(1);
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});
