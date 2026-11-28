// Lets native commands use the same admitted routes and action scope as the sidebar.
import { computed, nextTick, onScopeDispose, watchEffect } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { WorkspaceNavigation } from "@/composables/useWorkspaceNavigation";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { useAppConfig } from "@/composables/useAppConfig";
import { useNavigationActionContext } from "./actionContext";
import { hasNativeNavigation, menuNavigation } from "./mode";
import { navigationPage, navigationRegistry, routePath, workspaceDestination, workspaceView } from "./workspace";

export type NativeMenuCommand = {
  generation: number;
} & (
  { kind: "navigate"; id: string }
  | { kind: "primary"; id: string; revision: number; locationKey: string }
);

function focusWorkspace() {
  const modal = document.querySelectorAll<HTMLElement>('[aria-modal="true"]');
  if ([...modal].some(dialog => dialog.getClientRects().length)) return;
  const workspace = document.querySelector<HTMLElement>("main.content");
  if (workspace && !workspace.contains(document.activeElement)) workspace.focus({ preventScroll: true });
}

export function useNativeNavigation(legacy: WorkspaceNavigation): void {
  if (!hasNativeNavigation) return;
  const bridge = window.spectraDesktop;
  if (!bridge?.publishNavigation || !bridge.onNavigationCommand) return;

  const router = useRouter();
  const route = useRoute();
  const project = useProjectStore();
  const auth = useAuthStore();
  const { appConfig, appMode, siteProfile } = useAppConfig();
  const action = useNavigationActionContext(legacy);
  let generation = 0;
  let last = "";

  const visiblePages = computed(() => {
    const audit = appConfig.value?.audit;
    const showAudit = !["demo", "pro"].includes(siteProfile.value ?? "") && (audit?.localQuery || audit?.fullPipeline);
    const showLogs = !(appMode.value === "enterprise" && (siteProfile.value === "pro" ||
      (siteProfile.value === "demo" && (!auth.user?.capabilities?.admin || auth.user?.is_active === false))));
    return navigationRegistry.tree().filter(page => page.id !== "host:logs" || showLogs).map(page => ({
      ...page, sections: page.sections.filter(section => section.id !== "host:project.audit" || showAudit),
    }));
  });

  watchEffect(() => {
    const active = navigationPage(route.path);
    const pages = visiblePages.value.map(({ id, entry, sections }) => ({
      id, label: entry.label, sections: sections.map(section => ({
        id: section.id, label: section.entry.label,
        views: section.views.map(view => ({ id: view.id, label: view.entry.label })),
      })),
    }));
    const selected = legacy.entry.value?.path === route.path ? legacy.entry.value.selected : undefined;
    const section = active?.sections.find(item => item.entry.id === `${active.entry.id}.${selected}`)
      ?? active?.sections.find(item => routePath(item.entry.route) === route.path);
    const selectedView = route.query.view ?? (section && workspaceView(section.entry.route));
    const view = section?.views.find(item => selectedView != null && workspaceView(item.entry.route) === selectedView);
    const location = [active?.entry.label, section?.entry.label, view?.entry.label].filter(Boolean).join(" › ");
    const title = [project.currentProject?.name, location].filter(Boolean).join(" — ").replace(/\s+/g, " ").trim().slice(0, 320);
    const snapshot = {
      menu: menuNavigation.value && !route.meta.public && !route.meta.standalone,
      title: title || "Spectra Sherpa", pageId: pages.find(page => page.id === active?.id)?.id,
      pages, primary: action.primary.value ? { ...action.primary.value, disabled: action.primary.value.disabled || action.busy.value } : null,
    };
    const serialized = JSON.stringify(snapshot);
    if (serialized === last) return;
    last = serialized;
    bridge.publishNavigation?.({ ...snapshot, generation: ++generation });
  }, { flush: "post" });

  const detach = bridge.onNavigationCommand(async (command) => {
    if (!menuNavigation.value || command?.generation !== generation || route.meta.public || route.meta.standalone) return;
    if (command.kind === "primary") {
      const current = action.primary.value;
      if (!current || current.id !== command.id || current.revision !== command.revision || current.locationKey !== command.locationKey) return;
      await action.invoke(current);
    } else if (command.kind === "navigate") {
      const nodes = visiblePages.value.flatMap(page => [page, ...page.sections.flatMap(section => [section, ...section.views])]);
      const target = nodes.find(node => node.id === command.id);
      if (!target) return;
      const entry = legacy.entry.value;
      const active = navigationPage(route.path);
      const item = entry?.path === route.path && entry.items.find(item => `${active?.id}.${item.id}` === target.id);
      if (item && !item.disabled) entry!.select(item.id);
      else if (!item) await router.push(workspaceDestination(target.entry.route, route));
    } else return;
    await nextTick();
    requestAnimationFrame(() => {
      if (menuNavigation.value) focusWorkspace();
    });
  });
  onScopeDispose(detach);
}
