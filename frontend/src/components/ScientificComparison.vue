<template>
  <section aria-label="Scientific comparison" class="scientific-comparison">
    <Panel header="Summary" toggleable>
    <p v-for="statement in pairedPopulationStatements" :key="statement" class="population-summary">{{ statement }}</p>
    <div class="populations">
      <article v-for="(item, index) in evidence.items" :key="`${item.reference.provider}:${item.reference.id}`">
        <h4>{{ itemLabel(index) }}</h4>
        <details><summary>Evidence source</summary>{{ item.reference.kind }} {{ item.reference.id }} · {{ item.reference.provider }}</details>
        <p>Response: {{ item.population.response || 'Not recorded' }} · Units: {{ item.population.units || 'Not recorded' }}</p>
        <p v-if="item.population.verification !== 'verified'" class="limitation">Sample matching {{ item.population.verification === 'partial' ? 'is only partly verified' : 'has not been verified' }}.</p>
        <details><summary>Sample counts and verification</summary>
          <p>Development: {{ count(item.population.development_count) }} · Held-out: {{ count(item.population.held_out_count) }} · Excluded: {{ count(item.population.excluded_count) }}</p>
          <p>Population verification: {{ item.population.verification }}</p>
        </details>
        <details v-if="item.dataset_use"><summary>Recorded dataset use</summary>
          <p>{{ item.dataset_use.notice }}</p>
          <p v-for="(usage, usageIndex) in item.dataset_use.populations" :key="usageIndex">{{ usage.basis }} · Results revealed: {{ usage.results_revealed === true ? 'Yes' : usage.results_revealed === false ? 'No' : 'Unknown' }} · Influenced development: {{ usage.influenced_development === true ? 'Yes' : usage.influenced_development === false ? 'No' : 'Unknown' }}</p>
        </details>
        <p v-for="limit in item.population.limitations" :key="limit" class="limitation">{{ limit }}</p>
      </article>
    </div>
    </Panel>
    <Panel header="Results" toggleable>
    <p v-for="verdict in verdicts" :key="verdict" class="comparison-verdict" role="status">{{ verdict }}</p>
    <p v-if="missingRoles.length" class="muted">Unavailable: {{ missingRoles.map(role => labels[role].toLowerCase()).join(', ') }}.</p>
    <details v-if="missingRoles.length" class="unavailable-reasons"><summary>Why unavailable / next steps</summary>
      <template v-for="role in missingRoles" :key="role">
        <p v-for="(section, index) in evidence.pairs.flatMap(pair => pair.sections.filter(section => section.role === role))" :key="`${role}:${index}`">
          <strong>{{ labels[role] }}:</strong> {{ section.reason }} {{ section.next_action }}
        </p>
      </template>
    </details>
    <section v-for="role in visibleRoles" :key="role" :aria-label="labels[role]" class="role-section">
      <Panel :header="roleHasEvidence(role) ? labels[role] : `${labels[role]} · unavailable`" toggleable :collapsed="!roleHasEvidence(role)">
      <MethodHelp topic="comparison" :label="labels[role]" :context="meanings[role]" />
      <div v-for="pair in evidence.pairs" :key="`${pair.left_index}:${pair.right_index}`" class="pair">
        <template v-for="section in pair.sections.filter(s => s.role === role)" :key="section.role">
          <h5 v-if="evidence.pairs.length > 1">{{ itemLabel(pair.left_index) }} / {{ itemLabel(pair.right_index) }}</h5>
          <p :class="['state', section.state]">{{ stateLabel(section.state) }}: {{ section.reason }}</p>
          <p v-if="section.state !== 'comparable'" class="next-action">{{ section.next_action }}</p>
          <p class="muted">Units: {{ units(role, pair.left_index) }} / {{ units(role, pair.right_index) }}</p>
          <table v-if="metricRows(role, pair).length" :aria-label="`${labels[role]} measures`">
            <thead><tr><th scope="col">Measure</th><th scope="col">{{ itemLabel(pair.left_index) }}</th><th scope="col">{{ itemLabel(pair.right_index) }}</th><th scope="col" title="Second run minus first run; matching evaluation evidence required">{{ comparisonDeltaLabel(pair.left_index, pair.right_index) }}</th></tr></thead>
            <tbody><tr v-for="value in metricRows(role, pair)" :key="value.metric">
              <th scope="row">{{ metricLabel(value.metric, role) }}</th>
              <td>{{ cell(value.left) }}</td><td>{{ cell(value.right) }}</td><td :class="value.preference" :title="value.preference ? `Second run: ${value.preference}${value.metric === 'bias' ? ' (closer to zero is better)' : ''}` : undefined">{{ cell(value.delta) }}<span v-if="value.preference" class="delta-direction"> · {{ value.preference }}</span></td>
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
              <thead><tr><th>Specimen</th><th>Reference</th><th>{{ itemLabel(pair.left_index) }} · prediction</th><th>{{ itemLabel(pair.right_index) }} · prediction</th><th>{{ itemLabel(pair.left_index) }} · residual</th><th>{{ itemLabel(pair.right_index) }} · residual</th></tr></thead>
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
      </Panel>
    </section>
    </Panel>
    <Panel header="Validation" toggleable :collapsed="true">
      <MethodHelp topic="comparison" label="Comparing results" context="Compare matching populations and evaluation roles. Missing evidence in one role does not invalidate another." />
      <slot name="validation-controls" />
      <ScientificBasisHelp />
    </Panel>
  </section>
</template>

<script setup lang="ts">
import Panel from "primevue/panel";
import MethodHelp from "@/components/MethodHelp.vue";
import { computed, ref, watch } from 'vue';
import { comparisonVerdict, metricPreference } from '@/utils/comparisonPresentation';
import { selectedSampleIds } from '@/utils/sampleReview';
import PlotlyChart from '@/components/PlotlyChart.vue';
import ScientificBasisHelp from '@/components/ScientificBasisHelp.vue';
import { comparisonLabel, comparisonDeltaLabel } from '@/utils/comparisonLabel';
import { scientificNumber } from '@/utils/scientificEncoding';
import type { EvidenceComparison, EvaluationRole } from '@/types/scientificComparison';
const props = defineProps<{ evidence: EvidenceComparison }>();
const itemLabel = (index: number) => comparisonLabel(props.evidence.items[index]?.label || 'Unavailable', index);
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
const pairedPopulationStatements = computed(() => props.evidence.pairs.flatMap(pair =>
  pair.sections.filter(section => section.state === 'comparable').flatMap(section => {
    const left = props.evidence.items[pair.left_index]?.sections[section.role];
    const right = props.evidence.items[pair.right_index]?.sections[section.role];
    if (!left?.sample_ids.length || left.sample_ids.length !== right?.sample_ids.length) return [];
    const rightIds = new Set(right.sample_ids);
    if (!left.sample_ids.every(id => rightIds.has(id))) return [];
    return [`Same ${left.sample_ids.length} ${labels[section.role].toLowerCase()} samples in runs ${pair.left_index + 1} and ${pair.right_index + 1}.`];
  }),
));
const visibleRoles = computed(() => roles.filter(roleHasEvidence));
const missingRoles = computed(() => roles.filter(role => !roleHasEvidence(role)));
const verdicts = computed(() => props.evidence.pairs.map(pair => comparisonVerdict(props.evidence, pair)).filter((value): value is string => Boolean(value)));
const labels: Record<EvaluationRole, string> = { calibration: 'Calibration', training_cv: 'Training CV', held_out: 'Held-out validation', outlier_challenge: 'Outlier challenge' };
const meanings: Record<EvaluationRole, string> = {
  calibration: 'Fit to the calibration samples; not a selection score by itself.',
  training_cv: 'Predictions made with each fold excluded from fitting. Used for development.',
  held_out: 'A frozen fitted model applied to samples excluded from fitting. Recorded use determines the independence claim.',
  outlier_challenge: 'Detection and consequences for declared outliers; separate from ordinary accuracy.',
};
function roleHasEvidence(role: EvaluationRole) {
  return props.evidence.items.some(item => item.sections[role] && (item.sections[role].state !== 'unavailable' || Object.keys(item.sections[role].metrics).length > 0));
}
const units = (role: EvaluationRole, index: number) => props.evidence.items[index]?.sections[role]?.population.units || 'Not recorded';
const cell = (value: number | null | undefined) => value == null ? '—' : number(value);
function metricRows(role: EvaluationRole, pair: Pair) {
  const left = props.evidence.items[pair.left_index]?.sections[role]?.metrics || {};
  const right = props.evidence.items[pair.right_index]?.sections[role]?.metrics || {};
  const qualified = pair.sections.find(section => section.role === role);
  // The canonical role projections align measures independently of node names.
  // Never infer a paired delta from matching labels or equal numeric values.
  const names = [...new Set([...Object.keys(left), ...Object.keys(right), ...Object.keys(qualified?.metric_values || {})])];
  return names.map(metric => {
    const paired = qualified?.metric_values[metric];
    return { metric, left: paired?.left ?? left[metric], right: paired?.right ?? right[metric],
      delta: qualified?.state === 'comparable' && paired ? paired.right - paired.left : null,
      preference: qualified?.state === 'comparable' && paired ? metricPreference(metric, paired.left, paired.right) : null };
  });
}
const count = (n: number | null | undefined) => n == null ? 'Unknown' : String(n);
const number = (n: number) => Number.isFinite(n) ? scientificNumber(n) : 'Unknown';
const stateLabel = (s: string) => ({ comparable: 'Comparable', descriptive_only: 'Descriptive only', reevaluation_needed: 'Common evaluation needed', unavailable: 'Unavailable' })[s] || s;
function metricLabel(metric: string, role: EvaluationRole) {
  if (metric === 'rmse') return ({ calibration: 'RMSEC', training_cv: 'RMSECV', held_out: 'RMSEP', outlier_challenge: 'Challenge RMSE' })[role];
  if (metric === 'r2') return role === 'training_cv' ? 'Q² (OOF)' : role === 'calibration' ? 'Calibration R²' : 'Predictive R²';
  return ({ mae: "MAE", bias: "Bias", sep: "SEP", rer: "RER", mse: "MSE" } as Record<string, string>)[metric] || metric;
}
function traces(role: EvaluationRole, pair: EvidenceComparison['pairs'][number], residual = false): Record<string, unknown>[] {
  return [pair.left_index, pair.right_index].flatMap(index => {
    const item = props.evidence.items[index];
    if (!item) return [];
    const section = item.sections[role];
    if (!section || section.state === 'unavailable' || !section.observations.length || section.observations.length !== section.predictions.length) return [];
    return [{ type: 'scatter', mode: 'markers', name: itemLabel(index),
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
.better { color: var(--ss-success); }
.worse { color: var(--ss-warning); }
.delta-direction { font-size: .75rem; }
.comparison-verdict { font-weight: 600; }
.limitation, .next-action { color: var(--ss-text-secondary); }
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th, td { padding: .4rem; text-align: left; border-bottom: 1px solid var(--ss-border); }
summary { cursor: pointer; margin: .75rem 0; }
.selected-row { background: var(--ss-action-tint); }
</style>
