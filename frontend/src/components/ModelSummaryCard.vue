<template>
  <section v-if="summary && (summary.model || hasStatistics)" class="model-summary" :class="{ 'model-summary--details': display === 'details' }" aria-label="Model summary">
    <template v-if="display !== 'details'">
    <header class="model-summary__header">
      <div>
        <h3>{{ summary.model?.method ?? "Model summary" }}</h3>
        <p v-if="summary.model?.settings.length" class="model-summary__settings">
          <span v-for="[label, value] in summary.model.settings" :key="label" :title="label">{{ value }}</span>
        </p>
      </div>
      <p class="model-summary__populations">
        <span v-for="item in populations" :key="item.role"><strong>{{ item.n }}</strong> {{ item.label.toLowerCase() }}</span>
      </p>
    </header>
    <p v-if="summary.preprocessing.length" class="model-summary__pretreatment">
      <span class="model-summary__label">Upstream pretreatment</span>
      {{ summary.preprocessing.join(" → ") }}
    </p>

    <p v-if="calibrationOnly" class="model-summary__caution" role="note">
      Calibration fit only; no retained CV or test predictions.
    </p>
    <p v-if="summary.componentSelection || summary.plsdaComponentSelection || heldOutCount != null"
      class="model-summary__design" role="note">
      Held-out evaluation:
      <template v-if="heldOutCount != null">{{ heldOutCount }} held-out samples with retained evaluation.</template>
      <template v-else-if="evidenceSubset">Open the source run for any retained independent test evaluation.</template>
      <template v-else>Not retained.</template>
    </p>

    <ul v-if="compact && compactWarnings.length" class="model-summary__caution" aria-label="Model limitations">
      <li v-for="warning in compactWarnings" :key="warning">{{ warning }}</li>
    </ul>
    </template>
    <component :is="display === 'details' ? 'div' : 'details'" v-if="display !== 'context'" :open="display !== 'details' && !compact ? true : undefined" class="model-summary__details">
      <summary v-if="display !== 'details'">Model and validation details</summary>
    <section v-if="summary.componentSelection" class="model-summary__components" aria-label="PLS component selection">
      <h4>Latent variables <MethodHelp topic="componentSelection" label="Component selection" /></h4>
      <p>Selected: <strong>{{ summary.componentSelection.selectedComponents }} LV</strong> ·
        {{ summary.componentSelection.nCalibration }} calibration samples · {{ summary.componentSelection.scaling.replace(/_/g, ' ') }}.</p>
      <details><summary>Component choice</summary>
        {{ summary.componentSelection.selectionRule.replace(/_/g, ' ') }} · {{ summary.componentSelection.selectionRuleStatus.replace(/_/g, ' ') }}
        <span v-if="summary.componentSelection.splitDigest"> · Split {{ summary.componentSelection.splitDigest }}</span>
      </details>
      <p v-if="summary.componentSelection.requestedComponents !== summary.componentSelection.selectedComponents" class="model-summary__caution" role="note">
        {{ summary.componentSelection.requestedComponents }} LV were requested; the fitted model reached
        {{ summary.componentSelection.selectedComponents }} identifiable LV. The marker shows the effective fit.
      </p>
      <p v-if="summary.componentSelection.cvStatus === 'available'" class="model-summary__design">
        {{ summary.componentSelection.cvFolds }}-fold {{ summary.componentSelection.cvMethod?.replace(/_/g, ' ') }}
        <template v-if="summary.componentSelection.cvGroups != null"> across {{ summary.componentSelection.cvGroups }} independent groups</template>.

      </p>
      <p v-else class="model-summary__caution" role="note">Cross-validation unavailable: {{ summary.componentSelection.cvReason }}</p>
      <p v-if="!summary.componentSelection.selectedInCurve" class="model-summary__caution" role="note">The effective LV is not plotted in this bounded curve.</p>
      <div v-for="response in summary.componentSelection.responses" :key="response.name" class="model-summary__component-response">
        <h5>{{ response.name }}<template v-if="response.unit"> ({{ response.unit }})</template></h5>
        <figure v-if="componentPlot(response)" class="model-summary__curve">

          <svg viewBox="0 0 400 125" role="img" :aria-label="`${response.name} error versus latent variables`">
            <path d="M30 5 V100 H390" class="axis" />
            <path :d="componentPlot(response)?.calibration ?? undefined" class="calibration" />
            <path v-if="componentPlot(response)?.validation" :d="componentPlot(response)?.validation ?? undefined" class="validation" />
            <path v-if="componentPlot(response)?.selectedX != null" :d="`M${componentPlot(response)?.selectedX} 5 V100`" class="selected" />
            <text x="32" y="118">1 LV</text><text x="350" y="118">{{ response.rows.length }} LV</text>
          </svg>
          <p class="model-summary__legend">Calibration RMSEC · Cross-validation RMSECV · Selected LV</p>
        </figure>
        <div class="model-summary__table">
          <table>
            <thead><tr><th scope="col">LV</th><th scope="col">RMSEC</th><th scope="col">RMSECV</th><th scope="col">R²X cumulative</th><th scope="col">R²Y cumulative</th><th scope="col">Q²</th></tr></thead>
            <tbody><tr v-for="row in response.rows" :key="row.components" :class="{ 'model-summary__selected-row': row.components === summary.componentSelection.selectedComponents }">
              <th scope="row">{{ row.components }}<span v-if="row.components === summary.componentSelection.selectedComponents"> selected</span></th>
              <td>{{ show(row.rmsec) }}</td><td>{{ show(row.rmsecv) }}</td><td>{{ show(row.r2x) }}</td><td>{{ show(row.r2y) }}</td><td>{{ show(row.q2) }}</td>
            </tr></tbody>
          </table>
        </div>
        <p v-if="response.minimumMeanFoldRmse != null" class="model-summary__design">Minimum mean fold error: {{ response.minimumMeanFoldRmse }} LV;
          one-standard-error suggestion: {{ response.oneStandardError }} LV.</p>
      </div>
    </section>

    <section v-if="summary.pcaComponentSelection" class="model-summary__components" aria-label="PCA component selection">
      <h4>Principal components <MethodHelp topic="componentSelection" label="Component selection" /></h4>
      <p>Selected: <strong>{{ summary.pcaComponentSelection.selectedComponents }} PC</strong> ·
        {{ summary.pcaComponentSelection.nCalibration }} calibration samples.</p>
      <p v-if="!summary.pcaComponentSelection.selectedInCurve" class="model-summary__caution" role="note">
        The selected PC is not plotted in this bounded curve; the fitted model still uses the saved selection.
      </p>
      <p v-if="summary.pcaComponentSelection.cvMethod" class="model-summary__design">
        {{ summary.pcaComponentSelection.cvFolds }}-fold {{ summary.pcaComponentSelection.cvMethod.replace(/_/g, ' ') }};
        reconstruction error in {{ summary.pcaComponentSelection.reconstructionSpace.replace(/_/g, ' ') }}.
      </p>
      <p v-else class="model-summary__caution" role="note">Reconstruction CV unavailable: {{ summary.pcaComponentSelection.cvReason }}</p>
      <div class="model-summary__table">
        <table>
          <thead><tr><th scope="col">PC</th><th scope="col">Explained X, incremental</th><th scope="col">Explained X, cumulative</th><th scope="col">Calibration reconstruction RMSE</th><th scope="col">CV reconstruction RMSE</th></tr></thead>
          <tbody><tr v-for="row in summary.pcaComponentSelection.rows" :key="row.components" :class="{ 'model-summary__selected-row': row.components === summary.pcaComponentSelection.selectedComponents }">
            <th scope="row">{{ row.components }}<span v-if="row.components === summary.pcaComponentSelection.selectedComponents"> selected</span></th>
            <td>{{ show(row.explainedIncremental) }}</td><td>{{ show(row.explainedCumulative) }}</td>
            <td>{{ show(row.calibrationReconstruction) }}</td><td>{{ show(row.cvReconstruction) }}</td>
          </tr></tbody>
        </table>
      </div>
    </section>

    <section v-if="summary.plsdaComponentSelection" class="model-summary__components" aria-label="PLS-DA component selection">
      <h4>Classification latent variables <MethodHelp topic="componentSelection" label="Component selection" /></h4>
      <p>Selected: <strong>{{ summary.plsdaComponentSelection.selectedComponents }} LV</strong> ·
        {{ summary.plsdaComponentSelection.nCalibration }} calibration samples ·
        {{ summary.plsdaComponentSelection.classes.length }} classes.</p>
      <p v-if="summary.plsdaComponentSelection.requestedComponents !== summary.plsdaComponentSelection.selectedComponents" class="model-summary__caution" role="note">
        {{ summary.plsdaComponentSelection.requestedComponents }} LV were requested; the classifier fitted
        {{ summary.plsdaComponentSelection.selectedComponents }} identifiable LV. The table marks the effective fit.
      </p>
      <p v-if="summary.plsdaComponentSelection.cvMethod" class="model-summary__design">
        {{ summary.plsdaComponentSelection.cvFolds }}-fold {{ summary.plsdaComponentSelection.cvMethod.replace(/_/g, ' ') }}.
      </p>
      <p v-else class="model-summary__caution" role="note">{{ classificationCvMessage(summary.plsdaComponentSelection.cvReason) }} Calibration fit cannot rank component choices. Reduce folds or add independent specimens before comparing latent variables.</p>
      <div v-if="summary.plsdaComponentSelection.cvMethod" class="model-summary__table">
        <table>
          <thead><tr><th scope="col">LV</th><th scope="col">Calibration balanced accuracy</th><th scope="col">CV balanced accuracy</th><th scope="col">CV accuracy</th><th scope="col">CV macro F1</th></tr></thead>
          <tbody><tr v-for="row in summary.plsdaComponentSelection.rows" :key="row.components" :class="{ 'model-summary__selected-row': row.components === summary.plsdaComponentSelection.selectedComponents }">
            <th scope="row">{{ row.components }}<span v-if="row.components === summary.plsdaComponentSelection.selectedComponents"> selected</span></th>
            <td>{{ percent(row.calibrationBalancedAccuracy) }}</td><td>{{ percent(row.cvBalancedAccuracy) }}</td>
            <td>{{ percent(row.cvAccuracy) }}</td><td>{{ percent(row.cvMacroF1) }}</td>
          </tr></tbody>
        </table>
      </div>
      <p v-if="summary.plsdaComponentSelection.suggestedComponents != null" class="model-summary__design">
        Maximum out-of-fold balanced accuracy suggests {{ summary.plsdaComponentSelection.suggestedComponents }} LV;
        the fitted model retains the intentional {{ summary.plsdaComponentSelection.selectedComponents }} LV selection.
      </p>
    </section>
    <button v-if="canEditSelection && (summary.componentSelection || summary.pcaComponentSelection || summary.plsdaComponentSelection)"
      type="button" class="model-summary__edit" @click="emit('edit-selection')">
      Edit components in Workflow
    </button>

    <div v-for="block in regressionTables" :key="block.target" class="model-summary__table">
      <table>
        <caption v-if="regressionTables.length > 1">{{ block.target }}</caption>
        <thead>
          <tr><th scope="col">Statistic</th><th v-for="column in block.columns" :key="column.role" scope="col">{{ scientificProtocolLabel(column) }}</th></tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Samples</th>
            <td v-for="column in block.columns" :key="column.role">{{ show(column.n) }}</td>
          </tr>
          <tr>
            <th scope="row">RMSE</th>
            <td v-for="column in block.columns" :key="column.role" :title="column.source">
              <span class="model-summary__name">{{ scientificErrorMetricLabel('rmse', column, rmseName(column.role)) }}</span> {{ show(column.rmse) }}
            </td>
          </tr>
          <tr>
            <th scope="row">R²</th>
            <td v-for="column in block.columns" :key="column.role" :title="r2Name(column.role)">
              <span class="model-summary__name">{{ column.role === "cross_validation" ? "Q²" : "R²" }}</span> {{ show(column.r2) }}
            </td>
          </tr>
          <tr><th scope="row">Bias</th><td v-for="column in block.columns" :key="column.role">{{ scientificErrorMetricLabel('bias', column) }}: {{ show(column.bias) }}</td></tr>
          <tr><th scope="row">SEP</th><td v-for="column in block.columns" :key="column.role">{{ scientificErrorMetricLabel('sep', column) }}: {{ show(column.sep) }}</td></tr>
          <tr><th scope="row">Slope</th><td v-for="column in block.columns" :key="column.role">{{ show(column.slope) }}</td></tr>
        </tbody>
      </table>
    </div>

    <div v-if="classificationColumns.length" class="model-summary__table">
      <table>
        <thead>
          <tr><th scope="col">Statistic</th><th v-for="column in classificationColumns" :key="column.role" scope="col">{{ evaluationRoleLabel(column.role) }}</th></tr>
        </thead>
        <tbody>
          <tr><th scope="row">Samples</th><td v-for="column in classificationColumns" :key="column.role">{{ show(column.n) }}</td></tr>
          <tr><th scope="row">Accuracy</th><td v-for="column in classificationColumns" :key="column.role" :title="column.source">{{ percent(column.accuracy) }}</td></tr>
          <tr><th scope="row">Balanced accuracy</th><td v-for="column in classificationColumns" :key="column.role">{{ percent(column.balancedAccuracy) }}</td></tr>
        </tbody>
      </table>
      <figure v-if="headlineConfusion?.confusion && headlineConfusion.labels.length" class="model-summary__confusion">
        <figcaption>Confusion matrix · {{ evaluationRoleLabel(headlineConfusion.role).toLowerCase() }} (rows: reference, columns: predicted)</figcaption>
        <table>
          <thead><tr><th scope="col"></th><th v-for="label in headlineConfusion.labels" :key="label" scope="col">{{ label }}</th></tr></thead>
          <tbody>
            <tr v-for="(row, rowIndex) in headlineConfusion.confusion" :key="rowIndex">
              <th scope="row">{{ headlineConfusion.labels[rowIndex] ?? rowIndex + 1 }}</th>
              <td v-for="(count, columnIndex) in row" :key="columnIndex" :class="{ diagonal: rowIndex === columnIndex, off: rowIndex !== columnIndex && count > 0 }">{{ count }}</td>
            </tr>
          </tbody>
        </table>
      </figure>
    </div>
    </component>
  </section>
</template>

<script setup lang="ts">
import MethodHelp from "@/components/MethodHelp.vue";
import { computed } from "vue";
import { evaluationRoleLabel, scientificScalar, scientificErrorMetricLabel, scientificProtocolLabel } from "@/utils/scientificDisplay";
import { r2Name, rmseName, SUMMARY_ROLES, type ClassificationStatistics, type ComponentSelectionResponse, type ModelSummary, type RegressionStatistics, type SummaryRole } from "@/utils/modelSummary";

const props = withDefaults(defineProps<{ summary: ModelSummary | null; canEditSelection?: boolean; evidenceSubset?: boolean; compact?: boolean; display?: 'full' | 'context' | 'details' }>(), { display: 'full' });
const emit = defineEmits<{ 'edit-selection': [] }>();

const compactWarnings = computed(() => {
  const summary = props.summary;
  const warnings: string[] = [];
  for (const selection of [summary?.componentSelection, summary?.plsdaComponentSelection]) {
    if (selection && selection.requestedComponents !== selection.selectedComponents) {
      warnings.push(`${selection.requestedComponents} LV requested; ${selection.selectedComponents} fitted.`);
    }
  }
  const pls = summary?.componentSelection;
  if (pls?.cvStatus === "unavailable") warnings.push(`CV unavailable: ${pls.cvReason}`);
  for (const selection of [summary?.pcaComponentSelection, summary?.plsdaComponentSelection]) {
    if (selection && !selection.cvMethod) warnings.push(`CV unavailable: ${selection.cvReason}`);
  }
  return warnings;
});

const hasStatistics = computed(() => Boolean(props.summary?.regression.length || props.summary?.classification.length));
const byRole = <T extends { role: SummaryRole }>(items: T[]): T[] =>
  SUMMARY_ROLES.flatMap((role) => items.filter((item) => item.role === role).slice(0, 1));

const regressionTables = computed(() => {
  const rows = props.summary?.regression ?? [];
  const targets = [...new Set(rows.map((row) => row.target))];
  // Calibration statistics from the model node can name the response
  // generically ("Target 1") while evaluators carry its name; a single
  // response is one table either way.
  if (targets.length > 1 && new Set(rows.map((row) => row.role)).size === rows.length) {
    return [{ target: targets.find((name) => !/^Target \d+$/.test(name)) ?? targets[0], columns: byRole<RegressionStatistics>(rows) }];
  }
  return targets.map((target) => ({ target, columns: byRole(rows.filter((row) => row.target === target)) }));
});
const classificationColumns = computed(() => byRole<ClassificationStatistics>(props.summary?.classification ?? []));
// The most independent population carries the headline confusion matrix.
const headlineConfusion = computed(() => [...classificationColumns.value].reverse().find((column) => column.confusion));

const populations = computed(() => {
  const all = [...(props.summary?.regression ?? []), ...(props.summary?.classification ?? [])];
  return SUMMARY_ROLES.flatMap((role) => {
    const selection = props.summary?.componentSelection ?? props.summary?.pcaComponentSelection ?? props.summary?.plsdaComponentSelection;
    const n = all.find((item) => item.role === role && item.n != null)?.n
      ?? (role === "calibration" ? selection?.nCalibration : null);
    return n == null ? [] : [{ role, n, label: role === 'calibration' && props.summary?.model?.method === 'PCA' ? 'Fitted samples' : evaluationRoleLabel(role) }];
  });
});
const heldOutCount = computed(() => {
  const records = [...(props.summary?.regression ?? []), ...(props.summary?.classification ?? [])];
  return records.find((item) => item.role === "held_out_test" && item.n != null)?.n ?? null;
});
const calibrationOnly = computed(() => {
  if (props.summary?.componentSelection?.cvStatus === "available") return false;
  if (props.summary?.pcaComponentSelection?.cvMethod || props.summary?.plsdaComponentSelection?.cvMethod) return false;
  const roles = new Set([...(props.summary?.regression ?? []), ...(props.summary?.classification ?? [])].map((item) => item.role));
  return roles.size === 1 && roles.has("calibration");
});

function componentPlot(response: ComponentSelectionResponse): { calibration: string; validation: string | null; selectedX: number | null } | null {
  const all = response.rows.flatMap((row) => [row.rmsec, row.rmsecv]).filter((value): value is number => value != null);
  if (!all.length || !response.rows.length) return null;
  const top = Math.max(...all, 1e-12);
  const x = (index: number) => 30 + index * 360 / Math.max(1, response.rows.length - 1);
  const y = (value: number) => 100 - 90 * value / top;
  const path = (key: "rmsec" | "rmsecv") => response.rows
    .map((row, index) => row[key] == null ? null : `${index === 0 ? "M" : "L"}${x(index)},${y(row[key]!)}`)
    .filter(Boolean).join(" ");
  const selected = props.summary?.componentSelection;
  const selectedX = selected && selected.selectedInCurve ? x(selected.selectedComponents - 1) : null;
  return { calibration: path("rmsec"), validation: response.rows.some((row) => row.rmsecv != null) ? path("rmsecv") : null, selectedX };
}

const show = (value: number | null) => (value == null ? "—" : scientificScalar(value));
const percent = (value: number | null) => (value == null ? "—" : `${Number((value * 100).toPrecision(4))}%`);
function classificationCvMessage(reason: string | null): string {
  if (!reason) return 'Classification cross-validation is unavailable.';
  if (reason.includes('every classification class must contain at least n_splits samples')) {
    return 'Cross-validation needs at least one independent specimen from each class in every fold.';
  }
  const detail = reason.replace(/^Classification CV is unavailable:\s*/i, '').trim();
  return `Classification cross-validation is unavailable: ${detail}`;
}
</script>

<style scoped>
.model-summary { margin: 0 0 1.25rem; padding: 1rem 1.25rem; border: 1px solid var(--surface-border); border-radius: 10px; background: var(--surface-card); }
.model-summary--details { margin: 0; padding: 0; border: 0; background: none; }
.model-summary__header { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .5rem 1.5rem; align-items: baseline; }
.model-summary h3 { margin: 0; font-size: 1.1rem; }
.model-summary__settings { display: flex; flex-wrap: wrap; gap: .35rem; margin: .4rem 0 0; }
.model-summary__settings span { padding: .1rem .5rem; border-radius: 999px; background: var(--surface-ground); font-size: .85rem; }
.model-summary__populations { display: flex; gap: 1rem; margin: 0; color: var(--text-color-secondary); font-size: .9rem; }
.model-summary__populations strong { color: var(--text-color); }
.model-summary__pretreatment { margin: .6rem 0 0; font-size: .9rem; }
.model-summary__label { margin-right: .5rem; color: var(--text-color-secondary); }
.model-summary__caution { margin: .75rem 0 0; padding: .5rem .75rem; border-left: 3px solid var(--ss-warning); background: var(--surface-ground); font-size: .875rem; }
.model-summary__table { margin-top: .9rem; overflow-x: auto; }
.model-summary table { border-collapse: collapse; font-size: .9rem; min-width: 22rem; }
.model-summary caption { text-align: left; font-weight: 600; padding-bottom: .25rem; }
.model-summary th, .model-summary td { padding: .35rem .75rem; border-bottom: 1px solid var(--surface-border); text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.model-summary th[scope="row"], .model-summary thead th:first-child { text-align: left; font-weight: 500; color: var(--text-color-secondary); }
.model-summary thead th { font-weight: 600; }
.model-summary__name { color: var(--text-color-secondary); font-size: .8rem; margin-right: .25rem; }
.model-summary__confusion { margin: .9rem 0 0; }
.model-summary__confusion figcaption { font-size: .85rem; color: var(--text-color-secondary); margin-bottom: .25rem; }
.model-summary__confusion table { min-width: 0; }
.model-summary__confusion td.diagonal { font-weight: 600; }
.model-summary__confusion td.off { color: var(--ss-danger); font-weight: 600; }
.model-summary__components { margin-top: 1rem; border-top: 1px solid var(--surface-border); padding-top: .75rem; }
.model-summary__components h4, .model-summary__components h5 { margin: .5rem 0; }
.model-summary__component-response { margin-top: .75rem; }
.model-summary__edit { margin-top: .75rem; color: var(--primary-color); background: transparent; border: 0; text-decoration: underline; cursor: pointer; }
.model-summary__design, .model-summary__legend { color: var(--text-color-secondary); font-size: .85rem; }
.model-summary__curve { margin: .5rem 0; max-width: 42rem; }
.model-summary__curve figcaption { font-size: .85rem; }
.model-summary__curve svg { width: 100%; height: auto; }
.model-summary__curve .axis { stroke: var(--text-color-secondary); fill: none; }
.model-summary__curve .calibration { stroke: var(--ss-action); fill: none; stroke-width: 2; }
.model-summary__curve .validation { stroke: var(--ss-warning); fill: none; stroke-width: 2; }
.model-summary__curve .selected { stroke: var(--ss-danger); stroke-dasharray: 4 4; fill: none; }
.model-summary__curve text { fill: var(--text-color-secondary); font-size: 10px; }
.model-summary__selected-row { background: var(--surface-ground); font-weight: 600; }
</style>
