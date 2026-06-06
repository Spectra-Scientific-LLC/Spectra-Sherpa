<template>
  <div
    ref="rootRef"
    class="header-actions responsive-header-actions"
    :class="{ 'is-collapsed': collapsed }"
  >
    <div ref="fullRef" class="responsive-header-actions__full">
      <slot />
    </div>

    <Button
      v-if="items.length > 0"
      label="Actions"
      icon="pi pi-bars"
      class="p-button-sm responsive-header-actions__trigger"
      :aria-expanded="collapsed ? undefined : 'false'"
      @click="toggleMenu"
    />
    <TieredMenu ref="menuRef" :model="items" :popup="true" />

    <div v-if="$slots.after" ref="afterRef" class="responsive-header-actions__after">
      <slot name="after" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import TieredMenu from "primevue/tieredmenu";

export interface HeaderActionMenuItem {
  label?: string;
  icon?: string;
  disabled?: boolean;
  separator?: boolean;
  items?: HeaderActionMenuItem[];
  command?: (event?: unknown) => void;
}

const props = withDefaults(
  defineProps<{
    items: HeaderActionMenuItem[];
    minTitleWidth?: number;
  }>(),
  {
    minTitleWidth: 220,
  },
);

const rootRef = ref<HTMLElement | null>(null);
const fullRef = ref<HTMLElement | null>(null);
const afterRef = ref<HTMLElement | null>(null);
const menuRef = ref<{ toggle: (event: Event) => void } | null>(null);
const collapsed = ref(false);

let resizeObserver: ResizeObserver | null = null;
let mutationObserver: MutationObserver | null = null;
let frame = 0;

function scheduleMeasure(): void {
  if (frame) cancelAnimationFrame(frame);
  frame = requestAnimationFrame(measure);
}

function measure(): void {
  frame = 0;
  const root = rootRef.value;
  const full = fullRef.value;
  const parent = root?.parentElement;
  if (!root || !full || !parent || props.items.length === 0) {
    collapsed.value = false;
    return;
  }

  const siblingWidth = Array.from(parent.children)
    .filter((child) => child !== root)
    .reduce((total, child) => {
      const el = child as HTMLElement;
      const width = Math.min(el.scrollWidth || el.offsetWidth, parent.clientWidth - props.minTitleWidth);
      return total + Math.max(width, props.minTitleWidth);
    }, 0);

  const afterWidth = afterRef.value?.offsetWidth ?? 0;
  const gapAllowance = 24;
  const available = Math.max(0, parent.clientWidth - siblingWidth - afterWidth - gapAllowance);
  const required = full.scrollWidth;

  collapsed.value = required > available;
}

function toggleMenu(event: Event): void {
  menuRef.value?.toggle(event);
}

onMounted(() => {
  const root = rootRef.value;
  const parent = root?.parentElement;
  const full = fullRef.value;

  if (typeof ResizeObserver !== "undefined") {
    resizeObserver = new ResizeObserver(scheduleMeasure);
    if (root) resizeObserver.observe(root);
    if (parent) resizeObserver.observe(parent);
    if (full) resizeObserver.observe(full);
    if (afterRef.value) resizeObserver.observe(afterRef.value);
  }

  if (typeof MutationObserver !== "undefined" && full) {
    mutationObserver = new MutationObserver(scheduleMeasure);
    mutationObserver.observe(full, {
      attributes: true,
      childList: true,
      subtree: true,
      characterData: true,
    });
  }

  window.addEventListener("resize", scheduleMeasure);
  void nextTick(scheduleMeasure);
});

onBeforeUnmount(() => {
  if (frame) cancelAnimationFrame(frame);
  resizeObserver?.disconnect();
  mutationObserver?.disconnect();
  window.removeEventListener("resize", scheduleMeasure);
});

watch(
  () => props.items,
  () => void nextTick(scheduleMeasure),
  { deep: true },
);
</script>

<style scoped>
.responsive-header-actions {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  justify-content: flex-end;
  max-width: 100%;
  min-width: 0;
  overflow: visible;
}

.responsive-header-actions__full {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  min-width: 0;
  width: max-content;
  max-width: none;
}

.responsive-header-actions__after {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  flex: 0 0 auto;
}

.responsive-header-actions__trigger {
  display: none;
  flex: 0 0 auto;
  white-space: nowrap;
}

.responsive-header-actions.is-collapsed .responsive-header-actions__full {
  position: absolute;
  visibility: hidden;
  pointer-events: none;
}

.responsive-header-actions.is-collapsed .responsive-header-actions__trigger {
  display: inline-flex;
}
</style>
