<template>
  <section aria-label="Paired training CV results">
    <h3>Paired training CV results</h3>
    <p>Development: {{ record.population.development_count }} · Held-out excluded: {{ record.population.held_out_count }}</p>
    <table><thead><tr><th>Repetition</th><th>{{ labels[0] }} RMSECV</th><th>{{ labels[1] }} RMSECV</th><th>Right minus left</th></tr></thead>
      <tbody><tr v-for="(difference, index) in record.paired_rmsecv_differences" :key="index"><th>{{ index + 1 }}</th><td>{{ number(record.results[index * 2]?.execution.metrics.rmse) }}</td><td>{{ number(record.results[index * 2 + 1]?.execution.metrics.rmse) }}</td><td>{{ number(difference) }}</td></tr></tbody></table>
    <p>{{ record.interpretation }}</p>
    <p>Right meaningfully better: {{ record.summary.right_meaningfully_better }}; left: {{ record.summary.left_meaningfully_better }}; within declared margin: {{ record.summary.within_margin }}.</p>
    <p>Inspect the saved evaluation for separate calibration, training CV and held-out results. Each recipe has one frozen full-development fit; changing the CV repetition does not refit its calibration or held-out predictions. Only training CV contributes to the paired robustness summary.</p>
    <details><summary>Exact protocol and provenance</summary><p>Protocol: {{ record.protocol_digest }}</p><p v-for="(split, index) in record.splits" :key="index">Partition {{ index + 1 }}: {{ split.digest }}</p></details>
    <button type="button" @click="downloadJson(record, `paired-evaluation-${runId}.json`)">Download exact evaluation record</button>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue';
import { downloadJson } from '@/utils/download';
import type { PairedEvaluationRecord } from '@/types/pairedEvaluation';
const props = defineProps<{ record: PairedEvaluationRecord; runId: number }>();
const labels = computed(() => props.record.protocol.recipes.map(recipe => `Run #${recipe.run_id} · ${recipe.model_node_id}`));
function number(value: number | undefined) { return value == null ? 'Unavailable' : value.toPrecision(5); }
</script>
<style scoped>
table { width: 100%; border-collapse: collapse; } th, td { text-align: left; padding: .5rem; border-bottom: 1px solid var(--surface-border); }
</style>
