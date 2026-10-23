<template>
  <section aria-label="Scientific comparison" class="scientific-comparison">
    <h3>Evaluation evidence <MethodHelp topic="comparison" label="Comparing results" context="Compare matching populations and evaluation roles. Missing evidence in one role does not invalidate another." /></h3>
    <div class="populations">
      <article v-for="item in evidence.items" :key="`${item.reference.provider}:${item.reference.id}`">
        <h4>{{ item.label }}</h4>
        <details><summary>Evidence source</summary>{{ item.reference.kind }} · {{ item.reference.provider }}</details>
        <p>Development: {{ count(item.population.development_count) }} · Held-out: {{ count(item.population.held_out_count) }} · Excluded: {{ count(item.population.excluded_count) }}</p>
        <p>Response: {{ item.population.response || 'Unknown' }} · Units: {{ item.population.units || 'Not recorded' }}</p>
        <p>Population verification: {{ item.population.verification }}</p>
        <details v-if="item.dataset_use"><summary>Recorded dataset use</summary>
          <p>{{ item.dataset_use.notice }}</p>
          <p v-for="(usage, index) in item.dataset_use.populations" :key="index">{{ usage.basis }} · Results revealed: {{ usage.results_revealed === true ? 'Yes' : usage.results_revealed === false ? 'No' : 'Unknown' }} · Influenced development: {{ usage.influenced_development === true ? 'Yes' : usage.influenced_development === false ? 'No' : 'Unknown' }}</p>
        </details>
        <p v-for="limit in item.population.limitations" :key="limit" class="limitation">{{ limit }}</p>
      </article>
    </div>
    <section v-for="role in roles" :key="role" :aria-label="labels[role]" class="role-section">
      <h4>{{ labels[role] }} <MethodHelp topic="comparison" :label="labels[role]" :context="meanings[role]" /></h4>
      <div v-for="pair in evidence.pairs" :key="`${pair.left_index}:${pair.right_index}`" class="pair">
        <template v-for="section in pair.sections.filter(s => s.role === role)" :key="section.role">
          <h5>{{ evidence.items[pair.left_index]?.label }} / {{ evidence.items[pair.right_index]?.label }}</h5>
          <p :class="['state', section.state]">{{ stateLabel(section.state) }}: {{ section.reason }}</p>
          <p v-if="section.state !== 'comparable'" class="next-action">{{ section.next_action }}</p>
          <table v-if="Object.keys(section.metric_values).length">
            <thead><tr><th>Measure</th><th>First</th><th>Second</th><th>Second − first</th></tr></thead>
            <tbody><tr v-for="(value, metric) in section.metric_values" :key="metric">
              <th scope="row">{{ metricLabel(String(metric), role) }}</th>
              <td>{{ number(value.left) }}</td><td>{{ number(value.right) }}</td><td>{{ number(value.right - value.left) }}</td>
            </tr></tbody>
          </table>
          <details v-if="section.state === 'comparable' && traces(role, pair).length" class="plots" open>
            <summary>Predictions and residuals · {{ labels[role] }}</summary>
            <PlotlyChart :data="traces(role, pair)" :layout="plotLayout(role, false)" :selected-point-ids="selection(role, pair)" @selected="selectPoints($event, role, pair)" @deselect="clearSelection(role, pair)" />
            <PlotlyChart :data="traces(role, pair, true)" :layout="plotLayout(role, true)" :selected-point-ids="selection(role, pair)" @selected="selectPoints($event, role, pair)" @deselect="clearSelection(role, pair)" />
            <MethodHelp topic="comparison" label="Linked highlights" context="Lasso highlights the same specimens across plots and table; it does not change fitting or exclusions." />
            <button v-if="selection(role, pair).length" type="button" @click="clearSelection(role, pair)">Clear selected specimens ({{ selection(role, pair).length }})</button>
            <details><summary>Specimen values · up to 50 shown, selected first</summary>
            <table aria-label="Paired specimen results">
              <thead><tr><th>Specimen</th><th>Reference</th><th>First prediction</th><th>Second prediction</th><th>First residual</th><th>Second residual</th></tr></thead>
              <tbody><tr v-for="row in sampleRows(role, pair)" :key="row.id" :class="{ 'selected-row': selection(role, pair).includes(row.id) }">
                <th scope="row"><button type="button" :aria-pressed="selection(role, pair).includes(row.id)" @click="toggleSample(row.id, role, pair)">{{ row.id }}</button></th>
                <td>{{ number(row.observed) }}</td><td>{{ number(row.left) }}</td><td>{{ number(row.right) }}</td><td>{{ number(row.observed - row.left) }}</td><td>{{ number(row.observed - row.right) }}</td>
              </tr></tbody>
            </table>
            <p>Plots retain all qualified points.</p>
            </details>
          </details>
        </template>
      </div>
    </section>
    <ScientificBasisHelp />
  </section>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { ref, watch } from 'vue';
import { selectedSampleIds } from '@/utils/sampleReview';
import PlotlyChart from '@/components/PlotlyChart.vue';
import ScientificBasisHelp from '@/components/ScientificBasisHelp.vue';
import { scientificNumber } from '@/utils/scientificEncoding';
import type { EvidenceComparison, EvaluationRole } from '@/types/scientificComparison';
const props = defineProps<{ evidence: EvidenceComparison }>();
type Pair = EvidenceComparison['pairs'][number];
const selections = ref<Record<string, string[]>>({});
const selectionKey = (role: EvaluationRole, pair: Pair) => `${role}:${pair.left_index}:${pair.right_index}`;
const selection = (role: EvaluationRole, pair: Pair) => selections.value[selectionKey(role, pair)] || [];
function clearSelection(role: EvaluationRole, pair: Pair) { selections.value[selectionKey(role, pair)] = []; }
function selectPoints(event: unknown, role: EvaluationRole, pair: Pair) {
  const allowed = new Set(props.evidence.items[pair.left_index].sections[role].sample_ids);
  selections.value[selectionKey(role, pair)] = selectedSampleIds(event, allowed);
}
function toggleSample(id: string, role: EvaluationRole, pair: Pair) {
  const ids = selection(role, pair);
  selections.value[selectionKey(role, pair)] = ids.includes(id) ? ids.filter(value => value !== id) : [...ids, id];
}
function sampleRows(role: EvaluationRole, pair: Pair) {
  const left = props.evidence.items[pair.left_index].sections[role], right = props.evidence.items[pair.right_index].sections[role];
  const selected = new Set(selection(role, pair));
  return left.sample_ids.map((id, i) => ({ id, observed: left.observations[i], left: left.predictions[i], right: right.predictions[i] }))
    .sort((a, b) => Number(selected.has(b.id)) - Number(selected.has(a.id))).slice(0, 50);
}
watch(() => props.evidence, () => { selections.value = {}; });
const roles: EvaluationRole[] = ['calibration', 'training_cv', 'held_out', 'outlier_challenge'];
const labels: Record<EvaluationRole, string> = { calibration: 'Calibration', training_cv: 'Training CV', held_out: 'Held-out validation', outlier_challenge: 'Outlier challenge' };
const meanings: Record<EvaluationRole, string> = {
  calibration: 'Fit to the calibration samples; not a selection score by itself.',
  training_cv: 'Predictions made with each fold excluded from fitting. Used for development.',
  held_out: 'A frozen fitted model applied to samples excluded from fitting. Recorded use determines the independence claim.',
  outlier_challenge: 'Detection and consequences for declared outliers; separate from ordinary accuracy.',
};
const count = (n: number | null | undefined) => n == null ? 'Unknown' : String(n);
const number = (n: number) => Number.isFinite(n) ? scientificNumber(n, { decimalPlaces: 4 }) : 'Unknown';
const stateLabel = (s: string) => ({ comparable: 'Comparable', descriptive_only: 'Descriptive only', reevaluation_needed: 'Common evaluation needed', unavailable: 'Unavailable' })[s] || s;
function metricLabel(metric: string, role: EvaluationRole) {
  if (metric === 'rmse') return ({ calibration: 'RMSEC', training_cv: 'RMSECV', held_out: 'RMSEP', outlier_challenge: 'Challenge RMSE' })[role];
  if (metric === 'r2') return role === 'training_cv' ? 'Q² (OOF)' : role === 'calibration' ? 'Calibration R²' : 'Predictive R²';
  return metric;
}
function traces(role: EvaluationRole, pair: EvidenceComparison['pairs'][number], residual = false): Record<string, unknown>[] {
  return [pair.left_index, pair.right_index].flatMap(index => {
    const item = props.evidence.items[index];
    if (!item) return [];
    const section = item.sections[role];
    if (!section || section.state === 'unavailable' || !section.observations.length || section.observations.length !== section.predictions.length) return [];
    return [{ type: 'scatter', mode: 'markers', name: item.label,
      x: section.observations,
      y: residual ? section.observations.map((value, i) => value - section.predictions[i]) : section.predictions,
      ids: section.sample_ids, customdata: section.sample_ids,
      text: section.sample_ids, hovertemplate: '%{text}<br>Reference: %{x}<br>Value: %{y}<extra>%{fullData.name}</extra>' }];
  });
}
function plotLayout(role: EvaluationRole, residual: boolean) {
  return { title: `${labels[role]} · ${residual ? 'Residuals' : 'Predicted versus reference'}`, height: 320,
    xaxis: { title: 'Reference' }, yaxis: { title: residual ? 'Reference − prediction' : 'Prediction' },
    margin: { t: 45, b: 55, l: 65, r: 20 }, showlegend: true, dragmode: 'lasso' };
}
</script>

<style scoped>
.scientific-comparison { display: flex; flex-direction: column; gap: .75rem; }
.populations { display: flex; flex-wrap: wrap; gap: 1rem; }
article { flex: 1; min-width: 220px; padding: .75rem; background: var(--ss-surface-subtle); }
.role-section { padding: .75rem; border: 1px solid var(--ss-border-strong); border-radius: 6px; }
h3, h4, h5 { margin: .25rem 0; }
p { font-size: .85rem; margin: .4rem 0; }
.state { font-weight: 600; }
.comparable { color: var(--ss-success); }
.limitation, .next-action { color: var(--ss-text-secondary); }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { padding: .4rem; text-align: left; border-bottom: 1px solid var(--ss-border); }
summary { cursor: pointer; margin: .75rem 0; }
.selected-row { background: var(--ss-action-tint); }
</style>
