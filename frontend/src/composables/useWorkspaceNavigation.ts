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
  return {
    entry: readonly(entry),
    publish(key: symbol, next: WorkspaceNavigationEntry) {
      // Publishing after render must not schedule another render indefinitely.
      if (owner === key && JSON.stringify(entry.value) === JSON.stringify(next)) return;
      owner = key;
      entry.value = next;
    },
    release(key: symbol) {
      // An old route's teardown must not erase a newly mounted page.
      if (owner !== key) return;
      owner = null;
      entry.value = null;
    },
  };
}

type WorkspaceNavigation = ReturnType<typeof createWorkspaceNavigation>;
export const workspaceNavigationKey: InjectionKey<WorkspaceNavigation> = Symbol("workspace-navigation");

export function provideWorkspaceNavigation() {
  const navigation = createWorkspaceNavigation();
  provide(workspaceNavigationKey, navigation);
  return navigation;
}

export function useWorkspaceNavigation() {
  return inject(workspaceNavigationKey, null);
}
