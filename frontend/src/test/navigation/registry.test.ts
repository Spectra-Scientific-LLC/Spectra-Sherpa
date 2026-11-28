import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import type { NavPrimaryAction } from "@/extension-contract/navigation-v1";
import { createNavigationRegistry } from "@/navigation/registry";
import { legacyNavigationRedirect } from "@/router/legacyRoutes";

const pages = [{ id: "runs", label: "Runs", icon: "pi pi-history", route: "/runs" }];
const sections = [{ id: "inspect", pageId: "runs", label: "Inspect", route: { path: "/runs/7", query: { section: "inspect" } } }];
const views = [{ id: "outputs", sectionId: "inspect", label: "Outputs", route: { path: "/runs/7", query: { section: "inspect", view: "Outputs" } } }];

function snapshot(locationKey = "primary-7", contributor = "host") {
  return {
    contributor, locationKey, isCurrent: () => true,
    context: { pageId: "runs", sectionId: "inspect", viewId: "outputs", projectId: 1, runId: 7, resource: null },
  };
}
function action(id: string, scope: NavPrimaryAction["scope"] = { pageId: "runs" }): NavPrimaryAction {
  return { id, scope, label: "Open run", accelerator: "CmdOrCtrl+Enter", available: () => true, execute: vi.fn() };
}

describe("navigation registry", () => {
  it("registers owned entries, honors insertion order and disposes its contribution", () => {
    const registry = createNavigationRegistry();
    registry.register("host", { pages, sections, views });
    const dispose = registry.register("campaign", { pages: [
      { id: "runs", label: "Optimize", icon: "pi pi-chart-line", route: "/campaigns", before: "runs" },
    ] });
    expect(registry.tree().map((page) => page.id)).toEqual(["campaign:runs", "host:runs"]);
    expect(registry.tree()[1].sections[0].views[0].id).toBe("host:outputs");
    dispose();
    dispose();
    expect(registry.tree().map((page) => page.id)).toEqual(["host:runs"]);
  });

  it("rejects duplicate IDs, duplicate actions per scope, and foreign parents atomically", () => {
    const registry = createNavigationRegistry();
    registry.register("host", { pages, sections, primaryActions: [action("open")] });
    expect(() => registry.register("host", { pages })).toThrow("Duplicate navigation ID");
    expect(() => registry.register("host", { primaryActions: [action("review")] })).toThrow("Duplicate navigation action scope");
    expect(() => registry.register("other", { sections })).toThrow("Unknown navigation parent");
    expect(registry.tree()).toHaveLength(1);
    expect(registry.primary(snapshot())?.id).toBe("host:open");
  });

  it("chooses the single most specific available action and never falls through a disabled action", async () => {
    const registry = createNavigationRegistry();
    const onPage = action("open");
    const onSection = action("freeze", { pageId: "runs", sectionId: "inspect" });
    const onView = action("export", { pageId: "runs", sectionId: "inspect", viewId: "outputs" });
    let available = true;
    registry.register("host", { pages, sections, views, primaryActions: [
      onPage, onSection, { ...onView, available: () => available, disabled: () => true },
    ] });
    const current = snapshot();
    expect(registry.primary(current)?.id).toBe("host:export");
    expect(await registry.invoke({ id: "host:freeze", locationKey: current.locationKey, revision: 1 }, current)).toBe(false);
    expect(await registry.invoke({ id: "host:export", locationKey: current.locationKey, revision: 1 }, current)).toBe(false);
    available = false;
    expect(await registry.invoke({ id: "host:freeze", locationKey: current.locationKey, revision: 1 }, current)).toBe(true);
    expect(onSection.execute).toHaveBeenCalledOnce();
    expect(onView.execute).not.toHaveBeenCalled();
    expect(onPage.execute).not.toHaveBeenCalled();
  });

  it("refuses a changed project, run, artifact or owner and aborts an owned action on disposal", async () => {
    const registry = createNavigationRegistry();
    const execute = vi.fn((_ctx, signal: AbortSignal) => new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true })));
    registry.register("host", { pages, sections, views });
    registry.register("host", { primaryActions: [{ ...action("open"), execute }], projectScoped: true });
    const expected = { id: "host:open", locationKey: "project-1-run-7-artifact-a", revision: 2 };
    for (const key of ["project-2-run-7-artifact-a", "project-1-run-8-artifact-a", "project-1-run-7-artifact-b"]) {
      expect(await registry.invoke(expected, snapshot(key))).toBe(false);
    }
    expect(await registry.invoke(expected, snapshot(expected.locationKey, "retired"))).toBe(false);
    expect(execute).not.toHaveBeenCalled();
    const pending = registry.invoke(expected, snapshot(expected.locationKey));
    registry.disposeProjectScoped();
    expect(await pending).toBe(false);
    expect(registry.primary(snapshot())).toBeUndefined();
    expect(registry.tree()).toHaveLength(1);
  });

  it("aborts the action when the visible workspace loses its current scope", async () => {
    const registry = createNavigationRegistry();
    const mounted = new AbortController();
    const execute = vi.fn((_ctx, signal: AbortSignal) => new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true })));
    registry.register("host", { pages, primaryActions: [{ ...action("open"), execute }] });
    const current = { ...snapshot(), signal: mounted.signal, isCurrent: () => !mounted.signal.aborted };
    const pending = registry.invoke({ id: "host:open", locationKey: current.locationKey, revision: 1 }, current);
    mounted.abort();
    expect(await pending).toBe(false);
    expect(execute).toHaveBeenCalledOnce();
    expect(await registry.invoke({ id: "host:open", locationKey: current.locationKey, revision: 1 }, current)).toBe(false);
  });

  it("refuses an old menu command when a contributor registers the same ID again", async () => {
    const registry = createNavigationRegistry();
    registry.register("host", { pages });
    const dispose = registry.register("host", { primaryActions: [action("open")] });
    const current = snapshot();
    const previous = registry.primary(current)!;
    dispose();
    const replacement = action("open");
    registry.register("host", { primaryActions: [replacement] });
    expect(await registry.invoke({ id: previous.id, locationKey: current.locationKey, revision: previous.revision }, current)).toBe(false);
    expect(replacement.execute).not.toHaveBeenCalled();
  });

  it("serializes plain navigation data and an invocation identifier for Electron", () => {
    const registry = createNavigationRegistry();
    registry.register("host", { pages, sections, views, primaryActions: [action("open")] });
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/runs/:runId?", component: {} }] });
    const menu = registry.serialize((route) => router.resolve(route).href, snapshot());
    expect(structuredClone(menu)).toEqual(menu);
    expect(menu.pages[0].sections[0].views[0].href).toBe("/runs/7?section=inspect&view=Outputs");
    expect(menu.primary).toMatchObject({ id: "host:open", accelerator: "CmdOrCtrl+Enter" });
  });
});

describe("legacy navigation", () => {
  it.each([
    ["/data", "inspect", "my-dataset"], ["/data", "explore", "my-dataset"],
    ["/data", "my_dataset", "my-dataset"], ["/data", "dataset", "my-dataset"],
    ["/data", "multi_well", "multi-well"], ["/data", "library", "library"],
    ["/runs", "history", "run_history"], ["/runs", "artifacts", "models"],
    ["/runs/7", "inspect", "inspect"], ["/runs", "compare", "compare"],
    ["/deploy", "integrations", "watches"], ["/deploy", "jobs", "history"],
    ["/report", "preview", "preview"], ["/workflow", "canvas", "canvas"],
    ["/settings", "api-keys", "api-keys"], ["/extension", "overview", "overview"],
  ])("normalizes %s tab %s", (path, tab, section) => {
    const query = { project: "1", run: "7", node: "eval", artifact: "model-a", evidence: "saved", view: "Summary" };
    expect(legacyNavigationRedirect({ path, query: { ...query, tab }, hash: "#anchor" }, path === "/extension"))
      .toEqual({ path, query: { ...query, section }, hash: "#anchor" });
  });

  it("opens old Settings hash links and leaves canonical addresses alone", () => {
    expect(legacyNavigationRedirect({ path: "/settings", query: {}, hash: "#data" }))
      .toEqual({ path: "/settings", query: { section: "data" }, hash: "" });
    expect(legacyNavigationRedirect({ path: "/runs/7", query: { section: "inspect" }, hash: "#anchor" })).toBeUndefined();
  });
});
