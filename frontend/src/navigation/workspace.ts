import { watch } from "vue";
import type { LocationQueryRaw, RouteLocationNormalizedLoaded, RouteLocationRaw } from "vue-router";
import { activeProjectScope } from "@/stores/projectScopeRegistry";
import { createNavigationRegistry } from "./registry";

export const navigationRegistry = createNavigationRegistry();
watch(activeProjectScope, navigationRegistry.disposeProjectScoped, { flush: "sync" });

const pages = [
  ["dashboard", "Dashboard", "pi pi-home", "/dashboard"],
  ["project", "Project", "pi pi-folder", "/project"],
  ["data", "Data", "pi pi-database", "/data"],
  ["workflow", "Workflow", "pi pi-sitemap", "/workflow"],
  ["runs", "Runs", "pi pi-history", "/runs"],
  ["deploy", "Deploy", "pi pi-cloud-upload", "/deploy"],
  ["report", "Report", "pi pi-file-edit", "/report"],
  ["logs", "Logs", "pi pi-list", "/logs"],
  ["settings", "Settings", "pi pi-sliders-h", "/settings"],
  ["documentation", "Documentation", "pi pi-book", "/documentation"],
] as const;

navigationRegistry.register("host", {
  pages: pages.map(([id, label, icon, route]) => ({ id, label, icon, route })),
  sections: [
    { id: "project.overview", pageId: "project", label: "Overview", route: "/project" },
    { id: "project.memory", pageId: "project", label: "Memory map", route: "/project/memory-map" },
    { id: "project.provenance", pageId: "project", label: "Provenance", route: "/project/provenance" },
    { id: "workflow.builder", pageId: "workflow", label: "Builder", route: { path: "/workflow", query: { view: "canvas" } } },
    { id: "project.audit", pageId: "project", label: "Audit", route: "/audit" },
  ],
  views: [
    { id: "workflow.builder.canvas", sectionId: "workflow.builder", label: "Canvas", route: { path: "/workflow", query: { view: "canvas" } } },
    { id: "workflow.builder.sheet", sectionId: "workflow.builder", label: "Active Sheet", route: { path: "/workflow", query: { view: "active-sheet" } } },
    { id: "workflow.builder.portfolio", sectionId: "workflow.builder", label: "Data Portfolio", route: { path: "/workflow", query: { view: "data-portfolio" } } },
  ],
});

export function routePath(route: RouteLocationRaw): string | undefined {
  return typeof route === "string" ? route.split(/[?#]/, 1)[0] : "path" in route ? route.path : undefined;
}

export function navigationPage(path: string | undefined) {
  if (!path) return undefined;
  const pagePath = path === "/audit" ? "/project" : path;
  return navigationRegistry.tree().find(({ entry }) => {
    const root = routePath(entry.route);
    return root && (pagePath === root || pagePath.startsWith(`${root}/`));
  });
}

/** An entry's default view is also active at legacy URLs without a view. */
export function workspaceView(target: RouteLocationRaw) {
  return typeof target === "string" || !("query" in target) ? undefined : target.query?.view;
}

/** Links within a page retain its location; crossing pages retains the project only. */
export function workspaceDestination(target: RouteLocationRaw, current: RouteLocationNormalizedLoaded): RouteLocationRaw {
  const path = routePath(target);
  const project = current.query?.project ?? current.query?.project_id ?? activeProjectScope.value;
  const route = typeof target === "string"
    ? (target === path ? { path: target } : null)
    : target;
  if (!route) return target;
  const query: LocationQueryRaw = path === current.path ? { ...current.query } : {};
  if (path !== current.path && project != null) {
    if (path === "/workflow") query.project_id = project;
    else if (path === "/audit") {
      query.scope_type = "Project";
      query.scope_id = String(project);
      query.target_type = "Project";
      query.target_id = String(project);
    } else query.project = project;
  }
  if (typeof target === "string" && !Object.keys(query).length) return target;
  if ("query" in route && route.query?.section != null) delete query.tab;
  return { ...route, query: { ...query, ...("query" in route ? route.query : {}) } };
}
