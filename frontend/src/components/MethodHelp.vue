<template>
  <details v-if="url && context" ref="details" class="method-context" @keydown.esc.stop="close">
    <summary class="method-help" :aria-label="label" :title="label">?</summary>
    <div class="method-context-text">
      <p>{{ context }}</p>
      <a :href="url" target="_blank" rel="noopener noreferrer">Documentation</a>
    </div>
  </details>
  <a
    v-else-if="url" class="method-help" :href="url"
    target="_blank" rel="noopener noreferrer" :title="label"
    :aria-label="`${label} (opens documentation in a new tab)`">?</a>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { resolveMethodHelpUrl, type MethodTopic } from "@/utils/documentation";
const props = defineProps<{ topic: MethodTopic; label: string; context?: string }>();
const url = computed(() => resolveMethodHelpUrl(props.topic));
const details = ref<HTMLDetailsElement>();
function close() {
  if (details.value) details.value.open = false;
  details.value?.querySelector("summary")?.focus();
}
</script>

<style scoped>
.method-help { display: inline-flex; align-items: center; justify-content: center;
  width: 1.25rem; height: 1.25rem; margin-inline-start: .4rem; border: 1px solid currentColor;
  border-radius: 50%; font-size: .8rem; font-weight: 600; line-height: 1;
  color: inherit; text-decoration: none; vertical-align: middle; flex-shrink: 0; }
.method-help:focus-visible { outline: 2px solid var(--ss-accent-border); outline-offset: 3px; }
.method-context { font-size: .8125rem; color: var(--ss-text-secondary); }
.method-context summary { cursor: pointer; list-style: none; }
.method-context summary::-webkit-details-marker { display: none; }
.method-context-text { margin: .4rem; max-width: 50rem; line-height: 1.45; }
.method-context-text p { margin: 0 0 .3rem; }
.method-context-text a { color: var(--ss-action); }
</style>
