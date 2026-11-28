import type { LocationQuery, LocationQueryRaw, RouteLocationRaw } from "vue-router";

const aliases: Record<string, Record<string, string>> = {
  data: { inspect: "my-dataset", explore: "my-dataset", dataset: "my-dataset", my_dataset: "my-dataset", multi_well: "multi-well" },
  runs: { history: "run_history", artifacts: "models" },
  deploy: { integrations: "watches", jobs: "history" },
};

const sectionPages = new Set(["data", "runs", "deploy", "report", "settings", "workflow"]);
const settingsSections = new Set(["preferences", "api-keys", "integrations", "data", "guidance", "storage"]);

export function navigationTab(query: LocationQuery): LocationQuery["section"] | undefined {
  return query.section ?? query.tab;
}

/** Translate the former tab address; keep scientific and ownership references intact. */
export function legacyNavigationRedirect(to: { path: string; query: LocationQuery; hash: string }, contributed = false): RouteLocationRaw | undefined {
  const page = to.path.split("/")[1];
  if (!sectionPages.has(page) && !contributed) return;
  const tab = typeof to.query.tab === "string" ? to.query.tab : undefined;
  const oldSettingsHash = page === "settings" && settingsSections.has(to.hash.slice(1)) ? to.hash.slice(1) : undefined;
  if (!tab && !oldSettingsHash) return;
  const requested = tab ?? (typeof to.query.section === "string" ? to.query.section : oldSettingsHash);
  if (!requested) return;
  const query: LocationQueryRaw = { ...to.query, section: aliases[page]?.[requested] ?? requested };
  delete query.tab;
  return { path: to.path, query, hash: oldSettingsHash ? "" : to.hash };
}
