import { readFileSync } from "node:fs";
import { test, expect, type APIRequestContext } from "@playwright/test";
import { createDataset, instantiate, runWorkflow } from "./journeys";

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
  const content = readFileSync(
    new URL("./fixtures/mixture-ir.csv", import.meta.url),
    "utf8",
  ).replace(/mixture-ir-/g, "second-mixture-");
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
