import type { SherpaDatasetDict } from "@/types";

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
  if (dataset) requests.delete(dataset);
}
const workspaces = new WeakMap<
  object,
  { scope: string; datasets: Map<number, SherpaDatasetDict> }
>();

/** Keep loaded sources across route changes, but never across account/project scopes. */
export function retainedDatasetWorkspace(
  owner: object,
  scope: string,
): Map<number, SherpaDatasetDict> {
  let workspace = workspaces.get(owner);
  if (!workspace || workspace.scope !== scope) {
    workspace?.datasets.clear();
    workspace = { scope, datasets: new Map() };
    workspaces.set(owner, workspace);
  }
  return workspace.datasets;
}
