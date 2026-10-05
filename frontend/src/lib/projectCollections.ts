import { shallowRef } from "vue";
import type { RouteLocationRaw } from "vue-router";

/** Optional resource summaries; the installed extension owns all provider calls. */
export interface ProjectCollection {
  key: string;
  label: string;
  total: number;
  to: RouteLocationRaw;
  items: Array<{ id: string; title: string; status: string; createdAt: string; to: RouteLocationRaw }>;
}
export type ProjectCollectionsLoader = (projectId: number) => Promise<ProjectCollection[]>;
export const projectCollectionsLoader = shallowRef<ProjectCollectionsLoader | null>(null);
export function installProjectCollections(loader: ProjectCollectionsLoader): () => void {
  projectCollectionsLoader.value = loader;
  return () => { if (projectCollectionsLoader.value === loader) projectCollectionsLoader.value = null; };
}
