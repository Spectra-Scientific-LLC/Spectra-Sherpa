<template>
  <section id="retained-observation-exclusions" aria-label="Samples used in this run" class="retained-population-summary"
    :class="{ 'retained-population-summary--empty': !availableSources.length }">
    <div v-for="source in availableSources" :key="source.nodeId" class="retained-population-source">
      <strong :title="source.nodeId">{{ labels?.[source.nodeId] || source.nodeId }}</strong>
      <span>{{ source.sourceCount }} samples · {{ source.usedCount }} used · {{ source.excludedCount }} excluded</span>
      <button type="button" :aria-label="`Review excluded samples for ${labels?.[source.nodeId] || source.nodeId}`" @click="$emit('inspect', source.nodeId)">Review</button>
      <button type="button" :aria-label="`Download the sample map for ${labels?.[source.nodeId] || source.nodeId}`" @click="$emit('download', source.nodeId)">Download</button>
    </div>
    <!-- A source without a recorded sample map is named, so its count is never read as zero exclusions. -->
    <span v-if="unavailableSources.length" class="retained-population-gap">
      Sample counts not recorded for {{ unavailableSources.map((source) => labels?.[source.nodeId] || source.nodeId).join(", ") }}.
    </span>
    <MethodHelp v-if="availableSources.length" topic="workflowExclusions" label="Samples used"
      context="Counts recorded when this run executed, per data source and before any branch filter. Later workflow edits are not shown." />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import MethodHelp from '@/components/MethodHelp.vue';
import { retainedPopulationView } from '@/utils/retainedPopulationSummary';
const props = defineProps<{ value: unknown; runId: number; labels?: Record<string, string> }>();
defineEmits<{ inspect: [nodeId: string]; download: [nodeId: string] }>();
const summary = computed(() => retainedPopulationView(props.value, props.runId));
// Sources with a recorded sample map show their counts; an unknown count is not a result.
const availableSources = computed(() => (summary.value?.sources ?? []).filter((source) => source.available));
// Named only beside recorded sources: a run with no map at all says nothing here.
const unavailableSources = computed(() => availableSources.value.length
  ? (summary.value?.sources ?? []).filter((source) => !source.available) : []);
</script>

<style scoped>
.retained-population-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; margin-block: 0.5rem; }
.retained-population-summary--empty { margin: 0; }
.retained-population-gap { color: var(--text-color-secondary); font-size: .875rem; }
.retained-population-source { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
</style>
