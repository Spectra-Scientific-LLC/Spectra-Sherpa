<template>
  <div
    class="workspace-state"
    :class="{ 'workspace-state--page': variant === 'page' }"
    :role="kind === 'error' ? 'alert' : 'status'"
    :aria-busy="kind === 'loading'"
  >
    <i v-if="kind === 'loading'" class="pi pi-spin pi-spinner" aria-hidden="true" />
    <i v-else-if="icon" :class="['workspace-state__icon', icon]" aria-hidden="true" />
    <p class="workspace-state__message">{{ message }}</p>
    <slot />
  </div>
</template>
<script setup lang="ts">
// ``inline`` sits beside other content (a message and its retry action on one
// line). ``page`` replaces a whole panel's content: left-aligned like the rest
// of the page, with an optional icon, and any hint or action stacked beneath
// the message. Long sentences use the full width rather than a narrow column.
withDefaults(
  defineProps<{ kind: "loading" | "empty" | "error"; message: string; icon?: string; variant?: "inline" | "page" }>(),
  { icon: undefined, variant: "inline" },
);
</script>
<style scoped>
.workspace-state {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-start;
  gap: 0.75rem;
  padding: 1.5rem;
  color: var(--text-color-secondary);
}
p {
  margin: 0;
}
.workspace-state--page {
  flex-direction: column;
  flex-wrap: nowrap;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 2rem 0;
  text-align: left;
}
.workspace-state--page .workspace-state__message {
  color: var(--text-color);
  font-size: 1rem;
  font-weight: 500;
}
.workspace-state__icon {
  font-size: 1.25rem;
}
.workspace-state--page .pi-spinner,
.workspace-state--page .workspace-state__icon {
  font-size: 2rem;
  margin-bottom: 0.25rem;
}
.workspace-state--page :slotted(p) {
  margin: 0;
  font-size: 0.875rem;
  line-height: 1.5;
}
</style>
