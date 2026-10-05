<template>
  <div
    class="workspace-context"
    :class="{ 'workspace-context--workflow': layout === 'workflow' }"
    :aria-label="label"
  >
    <slot />
  </div>
</template>
<script setup lang="ts">
withDefaults(defineProps<{ label: string; layout?: "default" | "workflow" }>(), {
  layout: "default",
});
</script>
<style scoped>
.workspace-context {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  gap: 1rem;
  padding-bottom: 0.75rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid var(--surface-border);
}
.workspace-context--workflow {
  grid-template-columns: minmax(0, 2fr) minmax(0, 2fr) minmax(0, 1fr);
}
.workspace-context--workflow :deep(.workspace-context-item:last-child) {
  text-align: right;
}
.workspace-context--workflow :deep(.workspace-context-item:last-child strong) {
  white-space: normal;
}
@media (max-width: 600px) {
  .workspace-context {
    grid-auto-flow: row;
    grid-template-columns: minmax(0, 1fr);
  }
  .workspace-context--workflow :deep(.workspace-context-item:last-child) {
    text-align: left;
  }
}
</style>
