<template>
  <section id="retained-observation-exclusions" aria-label="Retained workflow observation exclusions" class="retained-population-summary">
    <span v-if="!summary?.sources.length" title="No verified source map for this run. Current exclusions are not substituted.">Retained exclusions unavailable</span>
    <div v-for="source in summary?.sources ?? []" :key="source.nodeId" class="retained-population-source">
      <strong title="Retained source membership before branch filtering. Current edits are not shown.">Retained · {{ source.nodeId }}</strong>
      <template v-if="source.available">
        <span>Source {{ source.sourceCount }}</span>
        <span title="Used in the retained source result. Downstream use may differ.">Used {{ source.usedCount }}</span>
        <span title="Excluded from the retained source result, not the current workflow.">Excluded {{ source.excludedCount }}</span>
      </template>
      <span v-else title="Retained map unavailable, unsupported or outside the summary budget; not zero exclusions.">Unavailable</span>
      <button type="button" :aria-label="`Inspect retained source map ${source.nodeId}`" title="Inspect individual retained decisions" @click="$emit('inspect', source.nodeId)">Map</button>
      <button v-if="source.available" type="button" :aria-label="`Download retained row map ${source.nodeId}`" title="Download the complete retained map" @click="$emit('download', source.nodeId)">JSON</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { retainedPopulationView } from '@/utils/retainedPopulationSummary';
const props = defineProps<{ value: unknown; runId: number }>();
defineEmits<{ inspect: [nodeId: string]; download: [nodeId: string] }>();
const summary = computed(() => retainedPopulationView(props.value, props.runId));
</script>

<style scoped>
.retained-population-summary { margin-block: 0.5rem; }
.retained-population-source { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
</style>
