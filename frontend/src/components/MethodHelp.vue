<template>
  <a
    v-if="url" class="method-help" :href="url"
    target="_blank" rel="noopener noreferrer" :title="label"
    :aria-label="`${label} (opens documentation in a new tab)`">?</a>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { resolveMethodHelpUrl, type MethodTopic } from "@/utils/documentation";
const props = defineProps<{ topic: MethodTopic; label: string }>();
const url = computed(() => resolveMethodHelpUrl(props.topic));
</script>

<style scoped>
.method-help { display: inline-flex; align-items: center; justify-content: center;
  width: 1.25rem; height: 1.25rem; margin-inline-start: .4rem; border: 1px solid currentColor;
  border-radius: 50%; font-size: .8rem; font-weight: 600; line-height: 1;
  color: inherit; text-decoration: none; vertical-align: middle; flex-shrink: 0; }
.method-help:focus-visible { outline: 2px solid var(--ss-accent-border); outline-offset: 3px; }
</style>
