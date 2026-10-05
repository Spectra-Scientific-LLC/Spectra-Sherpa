import { computed, readonly, ref, type ComputedRef, type Ref } from "vue";

export interface PrimaryNavigationItem {
  label: string;
  to: string;
  icon: string;
  before?: string;
}

interface InternalEntry extends PrimaryNavigationItem {
  __contributorId: string;
}

const entries: Ref<InternalEntry[]> = ref([]);

function addItems(
  items: PrimaryNavigationItem[],
  contributorId: string = "anonymous",
): void {
  if (!Array.isArray(items) || items.length === 0) return;
  entries.value = [
    ...entries.value,
    ...items.map((item) => ({ ...item, __contributorId: contributorId })),
  ];
}

function removeItems(contributorId: string): void {
  entries.value = entries.value.filter(
    (entry) => entry.__contributorId !== contributorId,
  );
}

function clear(): void {
  entries.value = [];
}

const visibleItems: ComputedRef<PrimaryNavigationItem[]> = computed(() =>
  entries.value.map(({ __contributorId: _id, ...item }) => item),
);

export function usePrimaryNavigation() {
  return {
    items: visibleItems,
    addItems,
    removeItems,
    clear,
    _internal: readonly(entries),
  };
}
