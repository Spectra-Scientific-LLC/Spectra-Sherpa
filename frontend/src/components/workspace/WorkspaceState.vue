<template>
  <div
    class="workspace-state"
    :role="kind === 'error' ? 'alert' : 'status'"
    :aria-busy="kind === 'loading'"
  >
    <i v-if="kind === 'loading'" class="pi pi-spin pi-spinner" aria-hidden="true" />
    <p>{{ message }}</p>
    <slot />
  </div>
</template>
<script setup lang="ts">
defineProps<{ kind: "loading" | "empty" | "error"; message: string }>();
</script>
<style scoped>
.workspace-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 1.5rem;
  color: var(--text-color-secondary);
}
p {
  margin: 0;
}
</style>
