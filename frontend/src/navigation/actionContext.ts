import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { getActionContext } from "@/composables/useContextualActions";
import { useScopedRequest } from "@/composables/useScopedRequest";
import { useWorkspaceNavigation, type WorkspaceNavigation } from "@/composables/useWorkspaceNavigation";
import type { NavActionContext } from "@/extension-contract/navigation-v1";
import { navigationTab } from "@/router/legacyRoutes";
import { useAuthStore } from "@/stores/auth";
import { activeProjectScope } from "@/stores/projectScopeRegistry";
import type { NavigationSnapshot } from "./registry";
import { navigationPage, navigationRegistry, routePath, workspaceView } from "./workspace";

function positiveId(value: unknown): number | undefined {
  if (typeof value !== "string" && typeof value !== "number") return;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : undefined;
}

/** Bind a rendered action to the current actor, project, location and admitted evidence. */
export function useNavigationActionContext(workspace?: WorkspaceNavigation) {
  const route = useRoute();
  const auth = useAuthStore();
  const legacy = workspace ?? useWorkspaceNavigation();
  const busy = ref(false);
  const error = ref("");
  const locationKey = ref(0);

  const current = computed(() => {
    const page = navigationPage(route.path);
    const projectId = activeProjectScope.value;
    const query = route.query ?? {};
    const projects = [query.project, query.project_id].filter((value) => value != null);
    if (!page || projects.some((value) => positiveId(value) !== projectId)) return null;

    const activeLegacy = legacy?.entry.value?.path === route.path ? legacy.entry.value.selected : undefined;
    const selectedSection = activeLegacy ?? navigationTab(query);
    const section = page.sections.find(({ entry }) => {
      const target = entry.route;
      if (routePath(target) !== route.path) return false;
      if (typeof target === "string" || !("query" in target)) return selectedSection == null;
      return target.query?.section === selectedSection;
    });
    const selectedView = query.view ?? (section && workspaceView(section.entry.route));
    const view = section?.views.find(({ entry }) => selectedView != null && workspaceView(entry.route) === selectedView);

    const resource = getActionContext();
    if (resource && resource.projectId !== projectId) return null;
    const run = route.params?.runId;
    const expectedRun = positiveId(run);
    const runId = resource && "runId" in resource ? resource.runId : undefined;
    if (run != null && (!expectedRun || expectedRun !== runId)) return null;
    const artifact = query.artifact;
    const artifactUid = resource?.surface === "model" ? resource.artifactUid : undefined;
    if (artifact != null && artifact !== artifactUid) return null;

    const context: NavActionContext = {
      pageId: page.entry.id, sectionId: section?.entry.id, viewId: view?.entry.id, projectId, runId, artifactUid, resource,
    };
    return { context: Object.freeze(context), contributor: page.contributor };
  });

  const identity = () => [auth.user?.id, auth.sessionRevision, route.fullPath, activeProjectScope.value,
    current.value?.contributor, JSON.stringify(current.value?.context)];
  watch(identity, () => {
    locationKey.value += 1;
    busy.value = false;
    error.value = "";
  }, { flush: "sync" });
  const requests = useScopedRequest(identity);

  function snapshot(): NavigationSnapshot | null {
    const value = current.value;
    if (!value) return null;
    const ticket = requests.capture();
    const key = String(locationKey.value);
    return { ...value, locationKey: key, signal: ticket.signal, isCurrent: () => ticket.isCurrent() };
  }

  const primary = computed(() => {
    const value = current.value;
    if (!value) return undefined;
    const action = navigationRegistry.primary({ ...value, locationKey: String(locationKey.value), isCurrent: () => true });
    return action && {
      id: action.id, revision: action.revision, label: action.entry.label, locationKey: String(locationKey.value),
      disabled: action.entry.disabled?.(value.context) ?? false, accelerator: action.entry.accelerator,
    };
  });

  async function invoke(expected = primary.value): Promise<boolean> {
    if (!expected || busy.value) return false;
    const scope = snapshot();
    if (!scope) return false;
    busy.value = true;
    error.value = "";
    try {
      return await navigationRegistry.invoke(expected, scope);
    } catch (cause) {
      if (scope.isCurrent()) error.value = cause instanceof Error ? cause.message : "Action failed.";
      return false;
    } finally {
      if (scope.isCurrent()) busy.value = false;
    }
  }

  return { primary, snapshot, invoke, busy, error };
}
