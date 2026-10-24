import type { RouteLocation } from "vue-router";

export function legacyStorageRedirect(to: Pick<RouteLocation, "hash" | "query">) {
  return to.hash === "#storage" || to.query?.tab === "storage"
    ? { path: "/settings", query: { tab: "storage" }, hash: "" }
    : null;
}
