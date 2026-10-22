import type { SherpaDatasetDict } from "@/types";
import { toRaw } from "vue";

// This is a receipt of an actual complete-source inspection, not a shape-based
// inference. Weak keys retain no extra dataset after its workspace releases it.
const completeSources = new WeakMap<object, string>();

export function retainCompleteSource(dataset: SherpaDatasetDict, scope: string): void {
  completeSources.set(toRaw(dataset), scope);
}

export function retainedCompleteSource(
  dataset: SherpaDatasetDict | null | undefined, scope: string,
): SherpaDatasetDict | null {
  return dataset && completeSources.get(toRaw(dataset)) === scope ? dataset : null;
}

// Cache only while the exact admitted dataset object is retained. Replacing
// that object after an import, edit, or refresh invalidates its derived reads.
const requests = new WeakMap<object, Map<string, Promise<unknown>>>();

export function retainedInspection<T>(
  dataset: object,
  key: string,
  read: () => Promise<T>,
): Promise<T> {
  let entries = requests.get(dataset);
  if (!entries) {
    entries = new Map();
    requests.set(dataset, entries);
  }
  const existing = entries.get(key);
  if (existing) return existing as Promise<T>;
  const pending = read().catch((error: unknown) => {
    if (entries.get(key) === pending) entries.delete(key);
    throw error;
  });
  entries.set(key, pending);
  if (entries.size > 24) entries.delete(entries.keys().next().value!);
  return pending;
}

export function clearRetainedInspection(dataset: object | null): void {
  if (dataset) {
    requests.delete(dataset);
    completeSources.delete(toRaw(dataset));
  }
}
const workspaces = new WeakMap<
  object,
  { scope: string; datasets: Map<number, SherpaDatasetDict> }
>();

/** Invalidate retained facts even when the Data page is not mounted. */
export function clearRetainedDatasetWorkspace(owner: object): void {
  const workspace = workspaces.get(owner);
  workspace?.datasets.forEach(clearRetainedInspection);
  workspace?.datasets.clear();
  workspaces.delete(owner);
}

/** Keep loaded sources across route changes, but never across account/project scopes. */
export function retainedDatasetWorkspace(
  owner: object,
  scope: string,
): Map<number, SherpaDatasetDict> {
  let workspace = workspaces.get(owner);
  if (!workspace || workspace.scope !== scope) {
    clearRetainedDatasetWorkspace(owner);
    workspace = { scope, datasets: new Map() };
    workspaces.set(owner, workspace);
  }
  return workspace.datasets;
}
