/**
 * Menu-extension API for server-provided frontend modules.
 *
 * The OSS Topbar owns the user-menu's layout and rendering. Server
 * modules (loaded dynamically via `import("/ui/auth.js")`) contribute
 * entries through this composable rather than editing the Topbar
 * source. Each contribution is tagged with a `contributorId` so a
 * single caller's items can be removed together (e.g. when a module
 * is swapped or during tests).
 *
 * Singleton semantics: state lives at module scope so the Topbar's
 * render function and every server-module registration share the
 * same backing array. Reactivity is preserved via `ref`.
 *
 * This composable is part of the OSS public contract surface as of
 * v0.4.1. Its shape is mirrored in
 * `packages/spectra-server/frontend/src/types/context.ts` as
 * `HostTopbarMenu`; changes here must update that type too.
 */
import { computed, ref, readonly, type ComputedRef, type Ref } from "vue";

export interface TopbarMenuItem {
  label?: string;
  icon?: string;
  command?: () => void;
  separator?: boolean;
  disabled?: boolean;
  class?: string;
}

interface InternalEntry extends TopbarMenuItem {
  __contributorId: string;
}

const entries: Ref<InternalEntry[]> = ref([]);

function addItems(items: TopbarMenuItem[], contributorId: string = "anonymous"): void {
  if (!Array.isArray(items) || items.length === 0) return;
  const tagged = items.map((it) => ({ ...it, __contributorId: contributorId }));
  entries.value = [...entries.value, ...tagged];
}

function removeItems(contributorId: string): void {
  entries.value = entries.value.filter((e) => e.__contributorId !== contributorId);
}

function clear(): void {
  entries.value = [];
}

const visibleItems: ComputedRef<TopbarMenuItem[]> = computed(() =>
  entries.value.map(({ __contributorId: _id, ...rest }) => rest),
);

export function useTopbarMenu() {
  return {
    /** Read-only list of current contributions (strips internal tags). */
    items: visibleItems,
    /** Append items; passing a `contributorId` enables targeted removal. */
    addItems,
    /** Remove all items contributed under a given id. */
    removeItems,
    /** Test-only: wipe all contributions. */
    clear,
    /** Raw internal entries (read-only) — tests may inspect contributorId. */
    _internal: readonly(entries),
  };
}
