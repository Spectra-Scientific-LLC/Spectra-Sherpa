<template>
  <div class="workspace-context-item">
    <span>{{ label }}</span
    ><strong :title="detail || value">{{ value }}</strong
    ><small v-if="$slots.default"><slot /></small>
  </div>
</template>
<script setup lang="ts">
defineProps<{ label: string; value: string; detail?: string }>();
</script>
<style scoped>
.workspace-context-item {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
span {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
strong {
  color: var(--text-color);
  font-size: 1rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
small {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  overflow-wrap: anywhere;
}
</style>
