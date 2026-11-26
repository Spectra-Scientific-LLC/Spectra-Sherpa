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
      <!-- The headline answers "how good is it": the error for each recorded population. -->
      <p v-if="headline.length" class="model-summary__headline" aria-label="Headline statistics">
        <span v-for="item in headline" :key="item.role">
          <span class="model-summary__name">{{ item.rmseName }}</span> <strong>{{ item.rmse }}</strong>
          <template v-if="item.r2 != null"> · <span class="model-summary__name">{{ item.r2Name }}</span> {{ item.r2 }}</template>
        </span>
        <small v-if="headlineUnit">{{ headlineUnit }}</small>
      </p>
    </header>
    <p v-if="summary.preprocessing.length" class="model-summary__pretreatment">
      <span class="model-summary__label">Upstream pretreatment</span>
      {{ summary.preprocessing.join(" → ") }}
    </p>

    <p v-if="calibrationOnly" class="model-summary__caution" role="note">
      Calibration fit only; no saved CV or test predictions.
    </p>
    <p v-if="summary.componentSelection || summary.plsdaComponentSelection || heldOutCount != null"
      class="model-summary__design" role="note">
      <template v-if="heldOutCount != null">Evaluated on {{ heldOutCount }} held-out samples.</template>
      <template v-else-if="evidenceSubset">Open the source run for its held-out evaluation, if any.</template>
      <template v-else>No held-out evaluation in this run.</template>
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
      <p v-if="summary.componentSelection.automaticFit">Selected by training-fold CV (one-standard-error); refitted on training samples.</p>
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
          <!-- Error versus latent variables: both axes scaled and labelled, every LV ticked. -->
          <svg :viewBox="`0 0 ${PLOT.width} ${PLOT.height}`" role="img" :aria-label="`${response.name} RMSEC and RMSECV versus latent variables`">
            <g v-for="tick in componentPlot(response)!.yTicks" :key="`y${tick.y}`">
              <path :d="`M${PLOT.left} ${tick.y} H${PLOT.right}`" class="grid" />
              <text :x="PLOT.left - 6" :y="tick.y + 3" text-anchor="end">{{ tick.label }}</text>
            </g>
            <g v-for="tick in componentPlot(response)!.xTicks" :key="`x${tick.x}`">
              <path :d="`M${tick.x} ${PLOT.bottom} v4`" class="axis" />
              <text :x="tick.x" :y="PLOT.bottom + 15" text-anchor="middle">{{ tick.label }}</text>
            </g>
            <path :d="`M${PLOT.left} ${PLOT.top} V${PLOT.bottom} H${PLOT.right}`" class="axis" />
            <text :x="(PLOT.left + PLOT.right) / 2" :y="PLOT.height - 2" text-anchor="middle" class="axis-title">Latent variables</text>
            <text :x="12" :y="(PLOT.top + PLOT.bottom) / 2" text-anchor="middle" class="axis-title"
              :transform="`rotate(-90 12 ${(PLOT.top + PLOT.bottom) / 2})`">RMSE{{ response.unit ? ` (${response.unit})` : '' }}</text>
            <path :d="componentPlot(response)!.calibration" class="calibration" />
            <path v-if="componentPlot(response)!.validation" :d="componentPlot(response)!.validation ?? undefined" class="validation" />
            <path v-if="componentPlot(response)!.selectedX != null" :d="`M${componentPlot(response)!.selectedX} ${PLOT.top} V${PLOT.bottom}`" class="selected" />
            <circle v-if="componentPlot(response)!.minimum" :cx="componentPlot(response)!.minimum!.x" :cy="componentPlot(response)!.minimum!.y" r="4" class="minimum" />
          </svg>
          <figcaption class="model-summary__legend">
            <span><i class="swatch calibration" />RMSEC (calibration)</span>
            <span v-if="componentPlot(response)!.validation"><i class="swatch validation" />RMSECV (cross-validation)</span>
            <span v-if="componentPlot(response)!.selectedX != null"><i class="swatch selected" />Selected LV</span>
            <span v-if="componentPlot(response)!.minimum"><i class="swatch minimum" />Minimum mean fold error</span>
          </figcaption>
        </figure>
        <div class="model-summary__table">
          <table>
            <thead><tr><th scope="col">LV</th><th scope="col">RMSEC</th><th scope="col">RMSECV</th><th scope="col">R²X cumulative</th><th scope="col">R²Y cumulative</th><th scope="col">Q²</th></tr></thead>
            <tbody><tr v-for="row in response.rows" :key="row.components" :class="{ 'model-summary__selected-row': row.components === summary.componentSelection.selectedComponents }">
              <th scope="row">{{ row.components }}<span v-if="row.components === summary.componentSelection.selectedComponents"> selected</span></th>
              <td>{{ inColumn(row.rmsec, response.rows.map((item) => item.rmsec)) }}</td><td>{{ inColumn(row.rmsecv, response.rows.map((item) => item.rmsecv)) }}</td>
              <td>{{ fraction(row.r2x) }}</td><td>{{ fraction(row.r2y) }}</td><td>{{ fraction(row.q2) }}</td>
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
          <tr><th scope="col">Statistic</th><th v-for="column in block.columns" :key="column.role" scope="col">{{ scientificProtocolLabel(column).replace(/^Protocol: /, '') }}</th></tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Samples</th>
            <td v-for="column in block.columns" :key="column.role">{{ show(column.n) }}</td>
          </tr>
          <!-- Units are stated once per row; each column header already names the population. -->
          <tr>
            <th scope="row">{{ unitLabel('RMSE', block.columns) }}</th>
            <td v-for="column in block.columns" :key="column.role" :title="`${rmseName(column.role)} · ${column.source}`">{{ show(column.rmse) }}</td>
          </tr>
          <tr>
            <th scope="row">R² <small>(Q² for cross-validation)</small></th>
            <td v-for="column in block.columns" :key="column.role" :title="r2Name(column.role)">{{ fraction(column.r2) }}</td>
          </tr>
          <tr><th scope="row">{{ unitLabel('Bias', block.columns) }}</th><td v-for="column in block.columns" :key="column.role" :title="column.bias == null ? undefined : String(column.bias)">{{ bias(column.bias, column.rmse) }}</td></tr>
          <tr><th scope="row">{{ unitLabel('SEP', block.columns) }}</th><td v-for="column in block.columns" :key="column.role">{{ show(column.sep) }}</td></tr>
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
import { columnDecimals, evaluationRoleLabel, formatMeasurement, scientificScalar, scientificErrorMetricLabel, scientificProtocolLabel } from "@/utils/scientificDisplay";
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
  const pca = summary?.pcaComponentSelection;
  if (pca && !pca.cvMethod) warnings.push(`CV unavailable: ${pca.cvReason}`);
  const plsda = summary?.plsdaComponentSelection;
  if (plsda && !plsda.cvMethod) warnings.push(classificationCvMessage(plsda.cvReason));
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

const PLOT = { width: 440, height: 170, left: 56, right: 430, top: 8, bottom: 132 } as const;
type Tick = { label: string };
function componentPlot(response: ComponentSelectionResponse): {
  calibration: string; validation: string | null; selectedX: number | null;
  minimum: { x: number; y: number } | null;
  xTicks: Array<Tick & { x: number }>; yTicks: Array<Tick & { y: number }>;
} | null {
  const all = response.rows.flatMap((row) => [row.rmsec, row.rmsecv]).filter((value): value is number => value != null);
  if (!all.length || !response.rows.length) return null;
  const top = Math.max(...all, 1e-12);
  const span = PLOT.right - PLOT.left;
  const height = PLOT.bottom - PLOT.top;
  const x = (index: number) => PLOT.left + index * span / Math.max(1, response.rows.length - 1);
  const y = (value: number) => PLOT.bottom - height * value / top;
  const path = (key: "rmsec" | "rmsecv") => response.rows
    .map((row, index) => row[key] == null ? null : `${index === 0 ? "M" : "L"}${x(index)},${y(row[key]!)}`)
    .filter(Boolean).join(" ");
  const selected = props.summary?.componentSelection;
  const selectedX = selected && selected.selectedInCurve ? x(selected.selectedComponents - 1) : null;
  const minimumIndex = response.minimumMeanFoldRmse == null ? -1
    : response.rows.findIndex((row) => row.components === response.minimumMeanFoldRmse);
  const minimumRow = minimumIndex >= 0 ? response.rows[minimumIndex] : null;
  // Label every LV up to 15; beyond that every other one so the labels stay readable.
  const every = response.rows.length > 15 ? 2 : 1;
  return {
    calibration: path("rmsec"),
    validation: response.rows.some((row) => row.rmsecv != null) ? path("rmsecv") : null,
    selectedX,
    minimum: minimumRow?.rmsecv != null ? { x: x(minimumIndex), y: y(minimumRow.rmsecv) } : null,
    xTicks: response.rows.map((row, index) => ({ x: x(index), label: String(row.components) }))
      .filter((_, index) => index % every === 0 || index === response.rows.length - 1),
    yTicks: [0, top / 2, top].map((value) => ({ y: y(value), label: value === 0 ? "0" : show(value) })),
  };
}

const show = (value: number | null) => (value == null ? "—" : scientificScalar(value));
/** R², Q² and explained-variance fractions always to four decimals, so 0.99996 reads 1.0000, never "1". */
const fraction = (value: number | null) => (value == null ? "—" : value.toFixed(4));
/** One precision for a whole column of errors, set by its largest value. */
const inColumn = (value: number | null, column: Array<number | null>) =>
  value == null ? "—" : formatMeasurement(value, columnDecimals(column));
/** A bias at floating-point noise (for example 1e-14 on a calibration fit) is zero, shown at the RMSE's precision. */
function bias(value: number | null, rmse: number | null): string {
  if (value == null) return "—";
  if (Math.abs(value) <= 1e-9 * Math.max(1, Math.abs(rmse ?? 0))) {
    return (0).toFixed(rmse == null ? 3 : columnDecimals([rmse]));
  }
  return show(value);
}
/** "RMSE (% w/w)" when every population declares the same unit, else "(units not recorded)". */
function unitLabel(name: string, columns: RegressionStatistics[]): string {
  const label = scientificErrorMetricLabel("rmse", { target_units: columns.map((column) => column.target_units) }, name);
  return label.replace("(units not declared)", "(units not recorded)");
}
// One headline entry per recorded population, in order calibration → CV → held-out.
const headline = computed(() => (regressionTables.value[0]?.columns ?? [])
  .filter((column) => column.rmse != null)
  .map((column) => ({
    role: column.role,
    rmseName: rmseName(column.role),
    rmse: show(column.rmse),
    r2Name: column.role === "cross_validation" ? "Q²" : "R²",
    r2: column.r2 == null ? null : fraction(column.r2),
  })));
// Shown only when recorded; the statistics table says when units are missing.
const headlineUnit = computed(() => {
  const columns = regressionTables.value[0]?.columns ?? [];
  const unit = unitLabel("", columns).trim().replace(/^\(|\)$/g, "");
  return columns.length && unit !== "units not recorded" ? unit : "";
});
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
.model-summary__headline { display: flex; flex-wrap: wrap; align-items: baseline; gap: .25rem 1.25rem; margin: .5rem 0 0; flex-basis: 100%; font-variant-numeric: tabular-nums; }
.model-summary__headline strong { font-size: 1.05rem; }
.model-summary__headline small { color: var(--text-color-secondary); }
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
.model-summary__curve .grid { stroke: var(--surface-border); fill: none; }
.model-summary__curve .axis-title { fill: var(--text-color); font-size: 10.5px; }
.model-summary__curve .minimum { fill: var(--ss-warning); stroke: var(--surface-card); stroke-width: 1.5; }
.model-summary__curve .model-summary__legend { display: flex; flex-wrap: wrap; gap: .25rem 1rem; margin-top: .25rem; }
.model-summary__curve .swatch { display: inline-block; width: 1.25rem; height: 0; margin-right: .35rem; vertical-align: middle; border-top: 2px solid; }
.model-summary__curve .swatch.calibration { border-color: var(--ss-action); }
.model-summary__curve .swatch.validation { border-color: var(--ss-warning); }
.model-summary__curve .swatch.selected { border-color: var(--ss-danger); border-top-style: dashed; }
.model-summary__curve .swatch.minimum { width: .5rem; height: .5rem; border: 0; border-radius: 50%; background: var(--ss-warning); }
.model-summary__selected-row { background: var(--surface-ground); font-weight: 600; }
</style>
