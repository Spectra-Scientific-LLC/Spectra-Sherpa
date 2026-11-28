import { expect, test } from "@playwright/test";
import { createDataset, instantiate } from "./journeys";

test("the workspace shell keeps one decision in view across supported widths @smoke", async ({ page, request }) => {
  const fixture = await createDataset(request, "Corn instrument transfer — Long project name for layout", {
    source: "sklearn", name: "iris",
  });
  await page.goto(`/data?project=${fixture.project.id}&experiment=${fixture.experiment.id}&tab=my-dataset`);
  await page.getByRole("link", { name: "Project", exact: true }).click();
  await page.goto(`/project/provenance?project=${fixture.project.id}`);
  const heading = page.getByRole("heading", { name: "Provenance", exact: true });
  const primary = page.getByRole("button", { name: "Verify all", exact: true });
  await expect(heading).toBeVisible();
  for (const width of [390, 540, 700, 768, 871, 1027, 1440]) {
    await page.setViewportSize({ width, height: 960 });
    await expect(primary).toBeInViewport();
    await expect(primary).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Workspace navigation" })).toHaveCount(1);
    await expect(page.getByRole("tablist")).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
  }
  await page.screenshot({ path: test.info().outputPath("provenance-shell.png") });
});

test("Data sections restore the original scoped dataset when navigating back @smoke", async ({ page, request }) => {
  const fixture = await createDataset(request, "Navigation evidence", { source: "sklearn", name: "iris" });
  await page.goto(`/data?project=${fixture.project.id}&experiment=${fixture.experiment.id}&fileId=${fixture.files[0].id}&tab=my-dataset`);
  const nav = page.getByRole("navigation", { name: "Workspace navigation" });
  await expect(nav.getByRole("button", { name: "My Dataset", exact: true })).toHaveAttribute("aria-current", "true");
  await nav.getByRole("button", { name: "Load", exact: true }).click();
  await expect(page).toHaveURL(/section=upload/);
  await page.goBack();
  await expect(nav.getByRole("button", { name: "My Dataset", exact: true })).toHaveAttribute("aria-current", "true");
  const params = new URL(page.url()).searchParams;
  expect(params.get("project")).toBe(String(fixture.project.id));
  expect(params.get("experiment")).toBe(String(fixture.experiment.id));
  expect(params.get("fileId")).toBe(String(fixture.files[0].id));
  await page.goForward();
  await expect(page).toHaveURL(/section=upload/);
});

test("project and dataset decisions stay usable at all workspace widths", async ({ page, request }) => {
  const fixture = await createDataset(request, "Long project and dataset names preserve the next decision", {
    source: "sklearn", name: "iris",
  });
  const surfaces = [
    { name: "dashboard", url: "/dashboard?tab=projects", action: "New project" },
    { name: "project", url: `/project?project=${fixture.project.id}`, action: "New workflow" },
    { name: "my-dataset", url: `/data?project=${fixture.project.id}&experiment=${fixture.experiment.id}&fileId=${fixture.files[0].id}&section=my-dataset`, action: "Build workflow" },
    { name: "load", url: `/data?project=${fixture.project.id}&section=upload`, action: "Choose files" },
    { name: "contents", url: `/data?project=${fixture.project.id}&section=contents`, action: "Load data" },
    { name: "guide", url: `/data?project=${fixture.project.id}&section=guide`, action: "Build workflow" },
  ];
  for (const surface of surfaces) {
    await page.goto(surface.url);
    const primary = page.locator(".workspace-page-header").getByRole("button", { name: surface.action, exact: true });
    await expect(primary).toBeVisible();
    for (const width of [390, 540, 700, 768, 871, 1027, 1440]) {
      await page.setViewportSize({ width, height: 960 });
      await expect(primary).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1);
    }
    await page.screenshot({ path: test.info().outputPath(`${surface.name}.png`) });
  }
  await page.goto(surfaces[2].url);
  const evidence = page.getByRole("navigation", { name: "Dataset evidence" });
  await evidence.getByRole("link", { name: "Samples", exact: true }).click();
  await expect(page.getByRole("region", { name: "Sample details", exact: true })).toBeFocused();
  await evidence.getByRole("link", { name: "Metadata", exact: true }).click();
  await expect(page.getByRole("region", { name: "Dataset metadata and quality", exact: true })).toBeFocused();
  await page.goBack();
  await expect(page.getByRole("region", { name: "Sample details", exact: true })).toBeFocused();
  await page.goto(surfaces[1].url);
  await page.getByRole("button", { name: "New workflow", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Analysis Starters", exact: true })).toBeVisible();
  const query = new URL(page.url()).searchParams;
  expect(query.get("project_id")).toBe(String(fixture.project.id));
  expect(query.has("templates")).toBe(false);
});

test("Workflow views keep the selected sheet and Settings keeps legacy links", async ({ page, request }) => {
  const dataset = await createDataset(request, "Workspace decision views", { source: "sklearn", name: "iris" });
  const workflow = await instantiate(request, dataset, "pca");
  await page.goto(`/workflow?project_id=${dataset.project.id}&workflow_id=${workflow.id}`);
  const nav = page.getByRole("navigation", { name: "Workspace navigation" });
  const primary = page.locator(".workspace-page-header").getByRole("button", { name: "Run", exact: true });
  await expect(primary).toBeEnabled();
  await nav.getByRole("link", { name: "Active Sheet", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Active Sheet", exact: true })).toBeVisible();
  await nav.getByRole("link", { name: "Data Portfolio", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Data Portfolio", exact: true })).toBeVisible();
  const query = new URL(page.url()).searchParams;
  expect(query.get("project_id")).toBe(String(dataset.project.id));
  expect(query.get("workflow_id")).toBe(String(workflow.id));
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Active Sheet", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.locator(".workflow-workspace")).toBeVisible();
  await page.goto("/settings?tab=api-keys");
  await expect(page.getByRole("heading", { name: "Chat", exact: true, level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What chat can see", exact: true })).toBeVisible();
  await nav.getByRole("button", { name: "Integrations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Data & Privacy", exact: true })).toBeVisible();
  await page.goto("/settings?tab=data");
  await expect(page.getByRole("heading", { name: "General", exact: true, level: 1 })).toBeVisible();
  await expect(page.getByRole("radio", { name: "Menu bar", exact: true })).toBeDisabled();
  await expect(page.getByRole("radio", { name: "Sidebar", exact: true })).toBeChecked();
});

test("desktop menu routes the active project and restores browser-style navigation on demand", async ({ page, request }) => {
  const fixture = await createDataset(request, "Native menu evidence", { source: "sklearn", name: "iris" });
  await page.bringToFront();
  await page.addInitScript(() => {
    Object.defineProperty(window, "spectraDesktop", { value: {
      publishNavigation: (snapshot: object) => Reflect.set(window, "__nativeNavigation", snapshot),
      onNavigationCommand: (listener: (command: object) => void) => {
        const forward = (event: Event) => listener((event as CustomEvent).detail);
        window.addEventListener("test-native-command", forward);
        return () => window.removeEventListener("test-native-command", forward);
      },
    } });
  });
  await page.goto(`/data?project=${fixture.project.id}&section=my-dataset`);
  const nav = page.getByRole("navigation", { name: "Workspace navigation" });
  await expect(nav).toHaveCount(0);
  const snapshot = () => page.evaluate(() => Reflect.get(window, "__nativeNavigation") as {
    generation: number; menu: boolean; title: string; pages: { id: string; label: string; sections: { label: string }[] }[];
  });
  await expect.poll(async () => (await snapshot())?.title).toContain("Native menu evidence");
  await expect.poll(async () => (await snapshot())?.pages.find(item => item.label === "Data")?.sections.map(item => item.label))
    .toContain("My Dataset");
  const published = await snapshot();
  const workflow = published.pages.find((item) => item.label === "Workflow");
  expect(workflow).toBeDefined();
  const navigate = (generation: number, id: string) => page.evaluate((detail) => {
    window.dispatchEvent(new CustomEvent("test-native-command", { detail }));
  }, { kind: "navigate", generation, id });
  await navigate(published.generation - 1, workflow!.id);
  await expect(page).toHaveURL(/\/data\?/);
  // The menu reads the actual visible snapshot at the time of the click.
  await page.evaluate((id) => {
    const current = Reflect.get(window, "__nativeNavigation");
    window.dispatchEvent(new CustomEvent("test-native-command", {
      detail: { kind: "navigate", generation: current.generation, id },
    }));
  }, workflow!.id);
  await expect(page).toHaveURL(new RegExp(`/workflow\\?project_id=${fixture.project.id}`));
  // Workflow may place focus on node search when that control becomes ready.
  await expect.poll(() => page.locator("main.content").evaluate(main => main.contains(document.activeElement))).toBe(true);

  await page.goto("/settings?section=general");
  await page.getByRole("radio", { name: "Sidebar" }).check();
  await expect(nav).toHaveCount(1);
  await expect.poll(async () => (await snapshot())?.menu).toBe(false);
});
