<template>
  <div v-if="visibleScopes.length > 0" class="memory-attribution">
    <i class="pi pi-sitemap" aria-hidden="true"></i>
    <span>Using memory from</span>
    <span
      v-for="scope in visibleScopes"
      :key="scope"
      class="memory-attribution__chip"
    >
      {{ scope }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  scopes?: string[] | null;
}>();

const visibleScopes = computed(() =>
  Array.from(
    new Set(
      (props.scopes ?? [])
        .map((scope) => scope.trim())
        .filter(Boolean)
    )
  ).slice(0, 6)
);
</script>

<style scoped>
.memory-attribution {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.4rem;
  color: var(--text-color-secondary);
  font-size: 0.78rem;
}

.memory-attribution__chip {
  border: 1px solid rgba(124, 58, 237, 0.24);
  border-radius: 999px;
  background: rgba(124, 58, 237, 0.08);
  color: #5b21b6;
  padding: 0.12rem 0.45rem;
  line-height: 1.3;
}
</style>
