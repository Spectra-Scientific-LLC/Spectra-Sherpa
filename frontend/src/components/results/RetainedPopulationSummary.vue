<template>
  <section id="retained-observation-exclusions" aria-label="Retained workflow observation exclusions" class="retained-population-summary">
    <span v-if="!summary?.sources.length" title="No verified source map for this run. Current exclusions are not substituted.">Exclusions unavailable</span>
    <div v-for="source in summary?.sources ?? []" :key="source.nodeId" class="retained-population-source">
      <strong :title="source.nodeId">{{ labels?.[source.nodeId] || source.nodeId }}</strong>
      <template v-if="source.available">
        <span title="Observations in the source">n = {{ source.sourceCount }}</span>
        <span title="Used in the retained source result. Downstream use may differ.">used {{ source.usedCount }}</span>
        <span title="Excluded from the retained source result, not the current workflow.">excluded {{ source.excludedCount }}</span>
      </template>
      <span v-else title="Retained map unavailable, unsupported or outside the summary budget; not zero exclusions.">unavailable</span>
      <button type="button" :aria-label="`Inspect retained source map ${source.nodeId}`" title="Inspect individual retained decisions" @click="$emit('inspect', source.nodeId)">Map</button>
      <button v-if="source.available" type="button" :aria-label="`Download retained row map ${source.nodeId}`" title="Download the complete retained map" @click="$emit('download', source.nodeId)">JSON</button>
    </div>
    <MethodHelp v-if="summary?.sources.length" topic="workflowExclusions" label="Recorded exclusions"
      context="Counts recorded when this run executed, per Load Data source and before any branch filter. Current workflow edits are not shown." />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import MethodHelp from '@/components/MethodHelp.vue';
import { retainedPopulationView } from '@/utils/retainedPopulationSummary';
const props = defineProps<{ value: unknown; runId: number; labels?: Record<string, string> }>();
defineEmits<{ inspect: [nodeId: string]; download: [nodeId: string] }>();
const summary = computed(() => retainedPopulationView(props.value, props.runId));
</script>

<style scoped>
.retained-population-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-block: 0.5rem; }
.retained-population-source { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
</style>
