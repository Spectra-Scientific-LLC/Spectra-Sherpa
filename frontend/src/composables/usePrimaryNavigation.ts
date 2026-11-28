import { computed } from "vue";
import { navigationRegistry, routePath } from "@/navigation/workspace";

export interface PrimaryNavigationItem {
  label: string;
  to: string;
  icon: string;
  before?: string;
}

const disposers = new Map<string, () => void>();

/** Compatibility adapter for extensions that still supply flat page links. */
function addItems(items: PrimaryNavigationItem[], contributorId = "anonymous"): void {
  if (!Array.isArray(items) || !items.length) return;
  const pages = navigationRegistry.tree();
  const dispose = navigationRegistry.register(contributorId, {
    pages: items.map((item) => ({
      id: legacyNavigationId(item.to), label: item.label, icon: item.icon, route: item.to,
      before: pages.find((page) => routePath(page.entry.route) === item.before)?.entry.id,
    })),
  });
  const previous = disposers.get(contributorId);
  disposers.set(contributorId, () => { dispose(); previous?.(); });
}

function removeItems(contributorId: string): void {
  disposers.get(contributorId)?.();
  disposers.delete(contributorId);
}

function clear(): void {
  for (const contributor of disposers.keys()) removeItems(contributor);
}

function legacyNavigationId(location: string): string {
  return `legacy.${location.replace(/[^\w.-]/g, (character) => `_${character.codePointAt(0)?.toString(16)}_`)}`;
}

const items = computed<PrimaryNavigationItem[]>(() => {
  const pages = navigationRegistry.tree();
  return pages.flatMap(({ contributor, entry }) => {
    const to = typeof entry.route === "string" ? entry.route : routePath(entry.route);
    if (contributor === "host" || !to) return [];
    const before = pages.find((candidate) => candidate.entry.id === entry.before
      && (candidate.contributor === contributor || candidate.contributor === "host"));
    return [{ label: entry.label, to, icon: entry.icon, ...(before ? { before: routePath(before.entry.route) } : {}) }];
  });
});

export function usePrimaryNavigation() {
  return { items, addItems, removeItems, clear };
}
