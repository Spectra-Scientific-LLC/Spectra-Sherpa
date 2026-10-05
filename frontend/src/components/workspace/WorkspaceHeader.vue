<template>
  <header class="workspace-header">
    <div class="workspace-header__title">
      <h1>{{ title }}</h1>
      <slot name="badge" />
    </div>
    <ResponsiveHeaderActions v-if="$slots.default || $slots.after" :items="actions">
      <slot />
      <template v-if="$slots.after" #after><slot name="after" /></template>
    </ResponsiveHeaderActions>
  </header>
</template>
<script setup lang="ts">
import ResponsiveHeaderActions, {
  type HeaderActionMenuItem,
} from "@/components/ResponsiveHeaderActions.vue";
withDefaults(defineProps<{ title: string; actions?: HeaderActionMenuItem[] }>(), {
  actions: () => [],
});
</script>
<style scoped>
.workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  min-width: 0;
  padding-bottom: 1rem;
}
.workspace-header__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}
h1 {
  margin: 0;
  color: var(--text-color);
  font-size: 1.5rem;
  font-weight: 600;
}
.workspace-header :deep(.p-button) {
  min-height: 2.25rem;
}
@media (max-width: 480px) {
  .workspace-header {
    flex-wrap: wrap;
  }
}
</style>
