<template>
  <TabView class="workspace-tabs" :active-index="activeIndex" @update:active-index="select"
    ><slot
  /></TabView>
</template>
<script setup lang="ts">
import { computed } from "vue";
import TabView from "primevue/tabview";
const props = defineProps<{ modelValue: string; tabIds: readonly string[] }>();
const emit = defineEmits<{ "update:modelValue": [id: string] }>();
// Labels may change without changing saved links or attention identity.
const activeIndex = computed(() => Math.max(0, props.tabIds.indexOf(props.modelValue)));
function select(index: number): void {
  const id = props.tabIds[index];
  if (id !== undefined) emit("update:modelValue", id);
}
</script>
<style scoped>
.workspace-tabs,
.workspace-tabs :deep(.p-tabview-nav-container),
.workspace-tabs :deep(.p-tabview-nav-content),
.workspace-tabs :deep(.p-tabview-panels) {
  background: transparent;
}
.workspace-tabs :deep(.p-tabview-nav) {
  display: flex;
  justify-content: flex-start;
  gap: 0.375rem;
  border: 0;
  border-bottom: 1px solid var(--surface-border);
  background: transparent;
  margin: 0;
  padding: 0;
}
.workspace-tabs :deep(.p-tabview-nav li) {
  margin: 0;
  background: transparent;
}
.workspace-tabs :deep(.p-tabview-nav-link) {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--text-color-secondary) 55%, var(--surface-border));
  border-radius: 6px 6px 0 0;
  margin-bottom: 0;
  color: var(--text-color-secondary);
  padding: 0.6rem 1rem;
  font-size: 0.9375rem;
  font-weight: 500;
}
.workspace-tabs :deep(.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 8%, transparent);
}
.workspace-tabs :deep(.p-tabview-nav-link:focus-visible) {
  outline: 2px solid var(--primary-color);
  outline-offset: -2px;
}
.workspace-tabs :deep(.p-tabview-panels) {
  padding: 1.5rem 0 0;
}
</style>
