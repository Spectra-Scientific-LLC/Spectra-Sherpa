import { navigationPage, navigationRegistry } from "@/navigation/workspace";
import { inject, provide, readonly, shallowRef, type InjectionKey } from "vue";

export interface WorkspaceNavigationItem {
  id: string;
  label: string;
  disabled: boolean;
  panelId: string;
}

export interface WorkspaceNavigationEntry {
  path: string;
  selected: string;
  items: WorkspaceNavigationItem[];
  select: (id: string) => void;
}

export function createWorkspaceNavigation() {
  const entry = shallowRef<WorkspaceNavigationEntry | null>(null);
  let owner: symbol | null = null;
  let dispose: (() => void) | undefined;
  return {
    entry: readonly(entry),
    publish(key: symbol, next: WorkspaceNavigationEntry) {
      // Publishing after render must not schedule another render indefinitely.
      if (owner === key && JSON.stringify(entry.value) === JSON.stringify(next)) return;
      const page = navigationPage(next.path);
      const previousItems = entry.value?.items.map(({ id, label }) => [id, label]);
      const nextItems = next.items.map(({ id, label }) => [id, label]);
      if (entry.value?.path !== next.path || JSON.stringify(previousItems) !== JSON.stringify(nextItems)) {
        dispose?.();
        dispose = page && navigationRegistry.register(page.contributor, {
          sections: next.items.map((item) => ({
            id: `${page.entry.id}.${item.id}`, pageId: page.entry.id, label: item.label,
            route: { path: next.path, query: { section: item.id } },
          })),
        });
      }
      owner = key;
      entry.value = next;
    },
    release(key: symbol) {
      // An old route's teardown must not erase a newly mounted page.
      if (owner !== key) return;
      owner = null;
      dispose?.();
      dispose = undefined;
      entry.value = null;
    },
  };
}

export type WorkspaceNavigation = ReturnType<typeof createWorkspaceNavigation>;
export const workspaceNavigationKey: InjectionKey<WorkspaceNavigation> = Symbol("workspace-navigation");

export function provideWorkspaceNavigation() {
  const navigation = createWorkspaceNavigation();
  provide(workspaceNavigationKey, navigation);
  return navigation;
}

export function useWorkspaceNavigation() {
  return inject(workspaceNavigationKey, null);
}
