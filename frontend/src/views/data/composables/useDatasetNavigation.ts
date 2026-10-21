import { ref } from "vue";
import { useScopedRequest, type ScopeIdentity } from "@/composables/useScopedRequest";
import type { LocationQuery } from "vue-router";
import type { useProjectStore } from "@/stores/project";

/** A declared project owns its dataset deep link; recency is only a fallback. */
export async function resolveDatasetProject(
  query: LocationQuery,
  project: Pick<ReturnType<typeof useProjectStore>, "fetchProject" | "ensureProjectForBrowserTab" | "error">,
): Promise<boolean> {
  const declared = [query.project, query.project_id].filter(value => value !== undefined);
  if (declared.length === 0) {
    await project.ensureProjectForBrowserTab();
    return true;
  }
  if (declared.some(value => typeof value !== "string" || !/^[1-9][0-9]*$/.test(value)
    || !Number.isSafeInteger(Number(value))) || new Set(declared).size !== 1) {
    throw new Error("The dataset link has an invalid project. Open Data from the project you want.");
  }
  const selected = await project.fetchProject(Number(declared[0]));
  if (!selected && project.error) {
    throw new Error("The linked project is unavailable. Check access or choose another project.");
  }
  // A superseding selection is not a failed request and must not fall back.
  return selected !== null;
}

/** Explicit user selection supersedes route/bootstrap restoration, even A → B → A. */
export function useDatasetNavigation(identity: () => readonly ScopeIdentity[]) {
  const intent = ref(0);
  const scopedIdentity = () => [...identity(), intent.value];
  const bootstrap = useScopedRequest(scopedIdentity);
  const route = useScopedRequest(scopedIdentity);
  const focus = useScopedRequest(scopedIdentity);
  function choose(): void { intent.value += 1; }
  return { intent, bootstrap, route, focus, choose };
}
