<template>
  <div v-if="items.length" class="follow-up-chips" aria-label="Suggested follow-up questions">
    <button
      v-for="suggestion in items"
      :key="suggestion"
      class="follow-up-chip"
      type="button"
      @click="$emit('select', suggestion)"
    >
      <span aria-hidden="true">👉</span> {{ suggestion }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  suggestions?: string[];
}>();

defineEmits<{
  (event: "select", suggestion: string): void;
}>();

const items = computed(() =>
  (props.suggestions || [])
    .map((suggestion) => suggestion.trim())
    .filter(Boolean)
    .slice(0, 3),
);
</script>

<style scoped>
.follow-up-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.follow-up-chip {
  border: 1px solid color-mix(in srgb, var(--ss-accent) 28%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--ss-accent) 8%, transparent);
  color: var(--ss-accent);
  cursor: pointer;
  font-size: 0.78rem;
  line-height: 1.25;
  max-width: 100%;
  padding: 5px 9px;
  text-align: left;
}

.follow-up-chip:hover {
  background: color-mix(in srgb, var(--ss-accent) 14%, transparent);
  border-color: color-mix(in srgb, var(--ss-accent) 42%, transparent);
}

.follow-up-chip:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--ss-accent) 55%, transparent);
  outline-offset: 2px;
}
</style>
