<template>
  <section aria-label="Retained source exclusion map">
    <h3 :title="population ? `Source SHA-256 ${population.source_digest}` : undefined">Exclusions · {{ nodeLabel || nodeId }}
      <MethodHelp topic="workflowExclusions" label="Recorded exclusion map"
        context="Recorded when this run executed. Used means included in the Load Data result, before any branch filter; current workflow edits are not shown." /></h3>
    <p v-if="!population">Exclusion map unavailable.</p>
    <template v-else>
      <div class="retained-map-scroll">
        <table>
          <thead><tr><th>Row</th><th>Sample ID</th><th>Label</th><th title="Included in My Dataset">Dataset</th><th title="Workflow exclusion at execution">Workflow</th><th title="Used in the retained source result">Used</th><th title="Row in the retained source result">Result row</th></tr></thead>
          <tbody><tr v-for="row in pageRows" :key="row.observation_ref">
            <td>{{ row.source_row }}</td><td>{{ row.sample_id ?? '—' }}</td><td>{{ row.sample_label ?? '—' }}</td>
            <td>{{ row.source_included ? 'Included' : 'Excluded' }}</td><td>{{ row.workflow_excluded ? 'Excluded' : '—' }}</td>
            <td :class="{ excluded: !row.included }" :title="row.included ? 'Used' : 'Not used'" :aria-label="row.included ? 'Used' : 'Not used'">{{ row.included ? '○' : '⊗' }}</td><td>{{ row.result_row ?? '—' }}</td>
          </tr></tbody>
        </table>
      </div>
      <button type="button" aria-label="Previous observations" :disabled="page === 0" @click="page--">Previous</button>
      <span> {{ page * 100 + 1 }}–{{ Math.min((page + 1) * 100, population.rows.length) }} of {{ population.rows.length }} </span>
      <button type="button" aria-label="Next observations" :disabled="(page + 1) * 100 >= population.rows.length" @click="page++">Next</button>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import MethodHelp from '@/components/MethodHelp.vue';
import type { WorkflowPopulation } from '@/utils/workflowPopulation';
const props = defineProps<{ value: unknown; nodeId: string; nodeLabel?: string }>();
const page = ref(0);
watch(() => props.value, () => { page.value = 0; });
// A read-only table of the existing canonical fields, never a reconstructed
// population or editable workflow action provider. Render only 100 rows at once.
// Bound matches app/lib/workflow_population.py; alignment follows the retained
// receipt checks in app/services/run_population_summary.py, not current edits.
const MAX_WORKFLOW_OBSERVATIONS = 100_000;
const population = computed(() => {
  const state = props.value as (WorkflowPopulation & { availability?: unknown }) | null;
  if (!state || typeof state !== 'object' || state.schema_version !== 'spectrasherpa-workflow-population/1'
    || state.availability === 'unavailable' || state.source_node_id !== props.nodeId
    || typeof state.source_digest !== 'string' || !/^[a-f0-9]{64}$/.test(state.source_digest)
    || !Array.isArray(state.rows) || state.rows.length === 0 || state.rows.length > MAX_WORKFLOW_OBSERVATIONS
    || !Number.isInteger(state.source_count) || state.rows.length !== state.source_count
    || !Number.isInteger(state.active_count) || !Number.isInteger(state.workflow_excluded_count)) return null;
  let active = 0;
  let excluded = 0;
  for (const [index, row] of state.rows.entries()) {
    if (!row || typeof row !== 'object'
      || row.observation_ref !== `${state.source_node_id}:${state.source_digest}:${index}`
      || row.source_row !== index + 1
      || typeof row.source_included !== 'boolean' || typeof row.workflow_excluded !== 'boolean'
      || typeof row.included !== 'boolean'
      || row.included !== (row.source_included && !row.workflow_excluded)) return null;
    if (row.included) active++;
    if (row.workflow_excluded) excluded++;
    if (row.result_row !== (row.included ? active : null)) return null;
  }
  if (state.active_count !== active || state.workflow_excluded_count !== excluded) return null;
  return state;
});
const pageRows = computed(() => population.value?.rows.slice(page.value * 100, (page.value + 1) * 100) ?? []);
</script>

<style scoped>
.retained-map-scroll { overflow: auto; max-height: 30rem; }
th, td { text-align: left; padding: 0.35rem; }
p { overflow-wrap: anywhere; }
.excluded { color: var(--ss-excluded); }
</style>
