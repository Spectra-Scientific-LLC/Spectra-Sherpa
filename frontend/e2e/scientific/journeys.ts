import { readFileSync } from "node:fs";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export async function createDataset(
  request: APIRequestContext,
  name: string,
  source?: { source: string; name: string },
) {
  const created = await request.post("/api/v1/projects", {
    data: { name: `Acceptance — ${name}` },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const project = await created.json();
  const response = await request.post("/api/v1/experiments", {
    data: { name, project_id: project.id },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const experiment = await response.json();
  const imported = source
    ? await request.post(`/api/v1/experiments/${experiment.id}/import-reference`, {
        data: { datasets: [source] },
      })
    : await request.post(`/api/v1/experiments/${experiment.id}/files`, {
        multipart: {
          stage: "raw",
          file: {
            name: `${name}.csv`,
            mimeType: "text/csv",
            buffer: readFileSync(new URL(`./fixtures/${name}.csv`, import.meta.url)),
          },
        },
      });
  expect(imported.ok(), await imported.text()).toBeTruthy();
  const payload = await imported.json();
  const files = source ? payload.files : [payload];
  return { project, experiment, files };
}

export async function instantiate(
  request: APIRequestContext,
  dataset: Awaited<ReturnType<typeof createDataset>>,
  slug: string,
) {
  const response = await request.get("/api/v1/workflow-templates");
  expect(response.ok()).toBeTruthy();
  const template = (await response.json()).templates.find(
    (item: { slug: string }) => item.slug === slug,
  );
  expect(template, `Required template ${slug}`).toBeTruthy();
  const preview = await request.post("/api/v1/workflow-templates/binding-compatibility-preview", {
    data: {
      project_id: dataset.project.id,
      use_saved_analysis_selection: true,
      binding: {
        source: "experiment",
        experiment_id: dataset.experiment.id,
        file_ids: dataset.files.map((file: { id: number }) => file.id),
        stage: "raw",
      },
    },
  });
  expect(preview.ok(), await preview.text()).toBeTruthy();
  const { binding } = await preview.json();
  const created = await request.post(`/api/v1/workflow-templates/${template.id}/instantiate`, {
    data: {
      workflow_name: `${dataset.experiment.name} ${slug} acceptance`,
      project_id: dataset.project.id,
      data_bindings: { data_1: binding },
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return created.json();
}

export async function runWorkflow(page: Page, workflow: { id: number }, project: { id: number }) {
  await page.goto(`/workflow?workflow_id=${workflow.id}&project_id=${project.id}`);
  const executed = page.waitForResponse(
    (r) => r.url().endsWith(`/workflows/${workflow.id}/execute`) && r.request().method() === "POST",
    // Execution includes fitting and durable persistence, not just a UI action.
    // Native macOS qualification measured 19–26 s for these small workflows.
    { timeout: 60_000 },
  );
  await page
    .getByRole("button", { name: /^Run(?:\s|$)/ })
    .first()
    .click();
  const response = await executed;
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  expect(result.status, result.error).toBe("completed");
  expect(result.run_id).toBeGreaterThan(0);
  return result;
}
