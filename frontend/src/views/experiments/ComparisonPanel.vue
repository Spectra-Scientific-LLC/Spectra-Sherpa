<template>
  <div class="comparison-panel">
    <div class="comparison-header">
      <span class="comparison-title">
        <i class="pi pi-chart-bar"></i>
        Comparing {{ runs.length }} checked runs
      </span>
      <Button
        label="Back to History"
        icon="pi pi-arrow-left"
        class="p-button-text p-button-sm"
        @click="$emit('back')"
      />
    </div>

    <div v-if="runs.length === 0" class="comparison-empty">
      <i class="pi pi-info-circle"></i>
      <span>Check runs in History to compare them.</span>
    </div>

    <template v-else>
      <ScientificComparison v-if="scientificComparison" :evidence="scientificComparison">
        <template #validation-controls>
      <details v-if="runs.length === 2" class="evaluation-controls">
        <summary>Optional common evaluation and robustness</summary>
        <p>Select the saved PLS output from each workflow. This creates a new development evaluation and keeps the original runs unchanged.</p>
        <label v-for="run in runs" :key="run.id">{{ run.name }}
          <select v-model="selectedModels[run.id]">
            <option value="">Choose a PLS output</option>
            <option v-for="node in modelNodes(run.id)" :key="node.node_id" :value="node.node_id">{{ scientificNodeLabel(node) }}</option>
          </select>
        </label>
        <PairedEvaluationPanel :recipes="pairedRecipes" />
      </details>
        </template>
      </ScientificComparison>
      <template v-else><ScientificBasisHelp />
      <details v-if="runs.length === 2" class="evaluation-controls">
        <summary>Optional common evaluation and robustness</summary>
        <p>Select the saved PLS output from each workflow. This creates a new development evaluation and keeps the original runs unchanged.</p>
        <label v-for="run in runs" :key="run.id">{{ run.name }}
          <select v-model="selectedModels[run.id]">
            <option value="">Choose a PLS output</option>
            <option v-for="node in modelNodes(run.id)" :key="node.node_id" :value="node.node_id">{{ scientificNodeLabel(node) }}</option>
          </select>
        </label>
        <PairedEvaluationPanel :recipes="pairedRecipes" />
      </details>
      </template>
      <p v-if="scientificComparison" class="qualification-note" role="status">Additional recorded details below; qualified comparisons are shown by evaluation role above.</p>
      <p v-else-if="!rankableMetrics?.length" class="qualification-note" role="status">
        Differences are arithmetic only; ranking requires matching evaluation evidence.
      </p>

      <Panel header="Workflow details and recorded measures" toggleable :collapsed="Boolean(scientificComparison)">
      <div class="matrix-scroll">
        <table class="comparison-matrix" :style="{ minWidth: `${14 + runs.length * 9 + (runs.length === 2 ? 8 : 0)}rem` }">
          <colgroup>
            <col class="comparison-measure-column" />
            <col v-for="run in runs" :key="run.id" class="comparison-run-column" />
            <col v-if="runs.length === 2" class="comparison-delta-column" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th v-for="(run, index) in runs" :key="run.id" scope="col">{{ comparisonLabel(run.name, index) }}</th>
              <th v-if="runs.length === 2" scope="col" title="Second run minus first run">{{ comparisonDeltaLabel() }}</th>
            </tr>
          </thead>
          <tbody v-for="section in comparisonSections" :key="section.title">
            <tr class="matrix-section-row">
              <th :colspan="runs.length + (runs.length === 2 ? 2 : 1)" scope="rowgroup">
                {{ section.title }}
              </th>
            </tr>
            <tr v-for="row in section.rows" :key="`${section.title}:${row.label}`">
              <th scope="row">{{ row.label }}</th>
              <td
                v-for="run in runs"
                :key="run.id"
                :class="matrixCellClass(row, run.id)"
              >
                <code v-if="row.code">{{ row.values[String(run.id)] }}</code>
                <template v-else>{{ row.values[String(run.id)] }}</template>
              </td>
              <td v-if="runs.length === 2" :class="row.metric ? deltaClass(row.metric) : ''">
                {{ row.metric ? displayDelta(row.metric) : formatDelta(row.delta ?? null) }}
              </td>
            </tr>
            <tr v-if="section.rows.length === 0">
              <td :colspan="runs.length + (runs.length === 2 ? 2 : 1)" class="matrix-empty">
                {{ section.empty }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </Panel>
    </template>
  </div>
</template>

<script setup lang="ts">
import { comparisonLabel, comparisonDeltaLabel } from "@/utils/comparisonLabel";
import { formatTimestamp } from "@/utils/format";
import { scientificNumber } from "@/utils/scientificEncoding";
import { computed, ref, watch } from "vue";
import Panel from "primevue/panel";
import Button from "primevue/button";
import api from "@/api/client";
import PairedEvaluationPanel from "@/components/PairedEvaluationPanel.vue";
import ScientificComparison from "@/components/ScientificComparison.vue";
import ScientificBasisHelp from "@/components/ScientificBasisHelp.vue";
import type { EvidenceComparison } from "@/types/scientificComparison";
import type { ExecutionRunDetail } from "@/types";

const props = defineProps<{
  runs: ExecutionRunDetail[];
  metricKeys: string[];
  diff: Record<string, Record<string, unknown>>;
  rankableMetrics?: string[];
  scientificComparison?: EvidenceComparison | null;
}>();

defineEmits<{ back: [] }>();

const HIGHER_IS_BETTER = new Set([
  "accuracy",
  "accuracy_test",
  "balanced_accuracy",
  "cv_accuracy",
  "cv_balanced_accuracy",
  "cv_f1_macro",
  "cv_precision_macro",
  "cv_recall_macro",
  "cv_sensitivity_macro",
  "cv_specificity_macro",
  "explained_variance",
  "explained_variance_ratio",
  "f1",
  "f1_macro",
  "f1_score",
  "precision",
  "precision_macro",
  "q2",
  "r2",
  "r2_cv",
  "r2_test",
  "recall",
  "recall_macro",
  "selection_stability",
  "silhouette_score",
  "sensitivity_macro",
  "specificity_macro",
  "test_accuracy",
  "test_balanced_accuracy",
  "test_f1_macro",
  "test_precision_macro",
  "test_recall_macro",
  "test_sensitivity_macro",
  "test_specificity_macro",
  "train_accuracy",
  "train_balanced_accuracy",
  "train_f1_macro",
  "train_precision_macro",
  "train_recall_macro",
  "train_sensitivity_macro",
  "train_specificity_macro",
]);

const SCIENTIFIC_METRIC_KEYS = new Set([
  "accuracy",
  "accuracy_test",
  "balanced_accuracy",
  "best_interval",
  "best_k",
  "best_rmsecv",
  "cumulative_variance",
  "cv_accuracy",
  "cv_balanced_accuracy",
  "cv_f1_macro",
  "cv_precision_macro",
  "cv_recall_macro",
  "cv_sensitivity_macro",
  "cv_specificity_macro",
  "explained_variance",
  "explained_variance_ratio",
  "f1",
  "f1_macro",
  "f1_score",
  "global_rmsecv",
  "inertia",
  "bias",
  "mae",
  "mean_n_selected",
  "mse",
  "n_classes",
  "n_clusters",
  "n_components",
  "n_iterations_run",
  "n_outliers",
  "n_selected",
  "precision",
  "precision_macro",
  "q2",
  "q_residuals",
  "r2",
  "r2_cv",
  "r2_test",
  "recall",
  "recall_macro",
  "reconstruction_error",
  "rmse",
  "rmsecv",
  "rmse_test",
  "rer",
  "selection_stability",
  "sep",
  "silhouette_score",
  "sensitivity_macro",
  "specificity_macro",
  "test_accuracy",
  "test_balanced_accuracy",
  "test_f1_macro",
  "test_precision_macro",
  "test_recall_macro",
  "test_sensitivity_macro",
  "test_specificity_macro",
  "train_accuracy",
  "train_balanced_accuracy",
  "train_f1_macro",
  "train_precision_macro",
  "train_recall_macro",
  "train_sensitivity_macro",
  "train_specificity_macro",
]);

const METRIC_LABELS: Record<string, string> = {
  accuracy: "Accuracy",
  accuracy_test: "Test Accuracy",
  balanced_accuracy: "Balanced Accuracy",
  best_interval: "Best Interval",
  best_k: "Best k",
  best_rmsecv: "Best RMSECV",
  cumulative_variance: "Cumulative Variance",
  cv_accuracy: "CV Accuracy",
  cv_balanced_accuracy: "CV Balanced Accuracy",
  cv_f1_macro: "CV Macro F1",
  cv_precision_macro: "CV Precision",
  cv_recall_macro: "CV Recall",
  cv_sensitivity_macro: "CV Sensitivity",
  cv_specificity_macro: "CV Specificity",
  cv_error: "CV Error",
  explained_variance: "Explained Variance",
  explained_variance_ratio: "Explained Variance",
  f1: "F1",
  f1_macro: "Macro F1",
  f1_score: "F1",
  global_rmsecv: "Global RMSECV",
  inertia: "Inertia",
  bias: "Bias",
  mae: "MAE",
  mean_n_selected: "Mean Selected Variables",
  mse: "MSE",
  n_classes: "Classes",
  n_clusters: "Clusters",
  n_components: "Components",
  n_iterations_run: "Iterations",
  n_outliers: "Outliers",
  n_selected: "Selected Variables",
  precision: "Precision",
  precision_macro: "Macro Precision",
  q2: "Q2",
  q_residuals: "Q Residuals",
  r2: "R2",
  r2_cv: "R2CV",
  r2_test: "Test R2",
  recall: "Recall",
  recall_macro: "Macro Recall",
  reconstruction_error: "Reconstruction Error",
  rmse: "RMSE",
  rmsecv: "RMSECV",
  rmse_test: "Test RMSE",
  rer: "RER",
  selection_stability: "Selection Stability",
  sep: "SEP",
  silhouette_score: "Silhouette",
  sensitivity_macro: "Macro Sensitivity",
  specificity_macro: "Macro Specificity",
  test_accuracy: "Test Accuracy",
  test_balanced_accuracy: "Test Balanced Accuracy",
  test_error: "Test Error",
  test_f1_macro: "Test Macro F1",
  test_precision_macro: "Test Precision",
  test_recall_macro: "Test Recall",
  test_sensitivity_macro: "Test Sensitivity",
  test_specificity_macro: "Test Specificity",
  train_accuracy: "Training Accuracy",
  train_balanced_accuracy: "Training Balanced Accuracy",
  train_error: "Training Error",
  train_f1_macro: "Training Macro F1",
  train_precision_macro: "Training Precision",
  train_recall_macro: "Training Recall",
  train_sensitivity_macro: "Training Sensitivity",
  train_specificity_macro: "Training Specificity",
};

const METRIC_DISPLAY_ORDER = [
  "test_error",
  "cv_error",
  "train_error",
  "test_accuracy",
  "accuracy_test",
  "test_balanced_accuracy",
  "cv_balanced_accuracy",
  "cv_accuracy",
  "balanced_accuracy",
  "accuracy",
  "train_accuracy",
  "cv_f1_macro",
  "f1_macro",
  "f1",
  "cv_sensitivity_macro",
  "cv_specificity_macro",
  "cv_precision_macro",
  "cv_recall_macro",
  "test_f1_macro",
  "test_sensitivity_macro",
  "test_specificity_macro",
  "train_f1_macro",
  "train_sensitivity_macro",
  "train_specificity_macro",
  "precision",
  "recall",
  "r2_cv",
  "q2",
  "r2_test",
  "r2",
  "rmsecv",
  "rmse_test",
  "rmse",
  "mae",
  "bias",
  "sep",
  "rer",
  "best_rmsecv",
  "global_rmsecv",
  "n_selected",
  "selection_stability",
  "silhouette_score",
  "reconstruction_error",
  "n_outliers",
  "n_components",
];

interface ComparisonRow {
  delta?: number | null;
  label: string;
  values: Record<string, string>;
}

interface MetricRow {
  metric: string;
  values: Record<string, unknown>;
  delta: number | null;
  bestRunId: string | null;
}

interface DataShape {
  samples: number | null;
  features: number | null;
}

interface SavedNode {
  node_id: string;
  node_type: string;
  label?: string;
  parameters?: Record<string, unknown>;
}
interface SavedGraph {
  nodes: SavedNode[];
  edges: Array<{ from_node_id: string; to_node_id: string }>;
}

const savedGraphs = ref<Record<string, SavedGraph | null>>({});
const selectedModels = ref<Record<number, string>>({});
// Serialized compatibility is resolved by the backend's derived projection.
const modelNodes = (id: number) => (savedGraphs.value[String(id)]?.nodes || []).filter(node =>
  node.node_type === 'model.fitted_pls');
const pairedRecipes = computed(() => props.runs.flatMap(run => selectedModels.value[run.id]
  ? [{ run_id: run.id, model_node_id: selectedModels.value[run.id], label: run.name }] : []));
let graphRequest = 0;
watch(
  () => props.runs.map((run) => `${run.id}:${run.project_id}`).join(","),
  async () => {
    const request = ++graphRequest;
    savedGraphs.value = {};
    selectedModels.value = {};
    await Promise.all(props.runs.map(async (run) => {
      const evidence = (run as ExecutionRunDetail & { evidence_completeness?: { outputs?: Record<string, Record<string, { state?: string }>> } }).evidence_completeness;
      if (evidence?.outputs?.__workflow__?.definition?.state !== "exact" || run.project_id == null) return;
      try {
        const retainedWorkflowNode = "__workflow__";
        const retainedWorkflowPort = "definition";
        const response = await api.get(`/runs/${run.id}/outputs/${retainedWorkflowNode}/${retainedWorkflowPort}`, {
          params: { project_id: run.project_id },
        });
        const graph = response.data?.canonical_workflow ?? response.data?.value;
        if (request === graphRequest && Array.isArray(graph?.nodes) && Array.isArray(graph?.edges)) {
          savedGraphs.value = { ...savedGraphs.value, [String(run.id)]: graph as SavedGraph };
          const models = modelNodes(run.id);
          if (models.length === 1) selectedModels.value[run.id] = models[0].node_id;
        }
      } catch {
        if (request === graphRequest)
          savedGraphs.value = { ...savedGraphs.value, [String(run.id)]: null };
      }
    }));
  },
  { immediate: true },
);

function orderedNodes(graph: SavedGraph): SavedNode[] {
  const byId = new Map(graph.nodes.map((node) => [node.node_id, node]));
  const indegree = new Map(graph.nodes.map((node) => [node.node_id, 0]));
  const outgoing = new Map(graph.nodes.map((node) => [node.node_id, [] as string[]]));
  for (const edge of graph.edges) {
    if (!byId.has(edge.from_node_id) || !byId.has(edge.to_node_id)) continue;
    indegree.set(edge.to_node_id, (indegree.get(edge.to_node_id) || 0) + 1);
    outgoing.get(edge.from_node_id)!.push(edge.to_node_id);
  }
  const queue = graph.nodes.filter((node) => indegree.get(node.node_id) === 0).map((node) => node.node_id);
  const ordered: SavedNode[] = [];
  for (const id of queue) {
    ordered.push(byId.get(id)!);
    for (const next of outgoing.get(id) || []) {
      indegree.set(next, indegree.get(next)! - 1);
      if (indegree.get(next) === 0) queue.push(next);
    }
  }
  return ordered.length === graph.nodes.length ? ordered : graph.nodes;
}

function scientificNodeLabel(node: SavedNode): string {
  const authored = node.label?.trim();
  const generic = !authored || /^(?:viz|node|source|output)[_-]?\d+$/i.test(authored);
  const type = node.node_type.split(".").slice(-1)[0]?.replace(/_/g, " ") || "Step";
  return generic ? type.replace(/\b\w/g, (letter: string) => letter.toUpperCase()) : authored;
}

interface MatrixRow extends ComparisonRow {
  changed: boolean;
  code?: boolean;
  metric?: MetricRow;
  workflow?: boolean;
}

interface MatrixSection {
  title: string;
  rows: MatrixRow[];
  empty: string;
}

const runContextRows = computed<ComparisonRow[]>(() => [
  makeRow("Run time", (run) => formatTimestamp(run.executed_at)),
  makeRow("Model version", (run) => formatModelVersion(run)),
  makeRow("Workflow version", (run) => formatWorkflowVersion(run)),
  makeRow("Run kind", (run) => formatRunKind(run.run_kind)),
  makeRow("Batch execution scope", (run) => String(run.source_metadata?.scope_label || "—")),
  makeRow("Batch identifier", (run) => String(run.source_metadata?.batch_id || "—")),
  makeRow("Status", (run) => run.status || "—"),
  makeRow("Produced models", (run) => formatArtifactList(run.produced_artifact_uids)),
]);

const dataPartitionRows = computed<ComparisonRow[]>(() => [
  makeRow("Data source", (run) => inferDataSource(run)),
  makeRow("Data dimensions", (run) => formatDataShape(inferWholeDataShape(run))),
  makeRow("Partition", (run) => inferPartition(run)),
  makeRow("Split settings", (run) => inferSplitSettings(run)),
]);

const metricRows = computed<MetricRow[]>(() => {
  const baseRows = props.metricKeys
    .filter((key) => SCIENTIFIC_METRIC_KEYS.has(metricNameFromKey(key)))
    .map((key) => buildMetricRow(key, props.diff[key] || {}));

  const derivedRows = [
    deriveErrorRow("test_error", ["test_accuracy", "accuracy_test"]),
    deriveErrorRow("cv_error", ["cv_accuracy", "cv_balanced_accuracy"]),
    deriveErrorRow("train_error", ["train_accuracy"]),
  ].filter((row): row is MetricRow => row !== null);

  return [...derivedRows, ...baseRows].sort((a, b) => metricRank(a.metric) - metricRank(b.metric));
});

const paramDiffRows = computed<ComparisonRow[]>(() => {
  if (props.runs.length < 2) return [];

  const allPaths = new Set<string>();
  for (const run of props.runs) {
    for (const [nodeId, params] of Object.entries(run.params_snapshot || {})) {
      if (isRecord(params)) {
        for (const paramKey of Object.keys(params)) {
          allPaths.add(`${nodeId}.${paramKey}`);
        }
      }
    }
  }

  const rows: ComparisonRow[] = [];
  for (const path of [...allPaths].sort()) {
    const [nodeId, paramKey] = path.split(".", 2);
    const rawValues = props.runs.map((run) => {
      const nodeParams = run.params_snapshot?.[nodeId];
      return isRecord(nodeParams) ? nodeParams[paramKey] : undefined;
    });
    const serialized = rawValues.map((value) => JSON.stringify(value));
    if (new Set(serialized).size <= 1) continue;
    rows.push({
      label: formatSettingPath(path),
      delta: numericalDelta(rawValues),
      values: Object.fromEntries(
        props.runs.map((run, idx) => [String(run.id), formatParamValue(rawValues[idx])]),
      ),
    });
  }
  return rows;
});

const workflowRows = computed<ComparisonRow[]>(() => {
  const order: string[] = [];
  const byRun: Record<string, Map<string, string>> = {};
  for (const run of props.runs) {
    const graph = savedGraphs.value[String(run.id)];
    const nodes = graph ? orderedNodes(graph) : [];
    byRun[String(run.id)] = new Map(nodes.map((node) => [node.node_id, scientificNodeLabel(node)]));
    for (const node of nodes) if (!order.includes(node.node_id)) order.push(node.node_id);
  }
  if (!order.length) return [makeRow("Saved workflow", () => "Definition unavailable")];
  return order.map((id, index) => ({
    label: `Step ${index + 1}`,
    values: Object.fromEntries(props.runs.map((run) => [String(run.id), byRun[String(run.id)]?.get(id) || "—"])),
  }));
});

const workflowSection = computed<MatrixSection>(() => {
  const section = matrixSection("Workflow", workflowRows.value, "No workflow nodes captured.");
  return { ...section, rows: section.rows.map((row) => ({ ...row, workflow: true })) };
});

const comparisonSections = computed<MatrixSection[]>(() => [
  matrixSection("Run context", runContextRows.value, "No run context captured."),
  matrixSection("Data & partition", dataPartitionRows.value, "No partition evidence captured."),
  workflowSection.value,
  {
    title: "Results",
    rows: metricRows.value.map((metric) => ({
      label: formatMetricName(metric.metric),
      values: Object.fromEntries(
        props.runs.map((run) => [
          String(run.id),
          formatValue(metric.values[String(run.id)]),
        ]),
      ),
      changed: rowValuesDiffer(metric.values),
      metric,
    })),
    empty: "No comparable scalar results.",
  },
  {
    title: "Changed settings",
    rows: paramDiffRows.value.map((row) => ({ ...row, changed: true, code: true })),
    empty: "No setting differences.",
  },
]);

function matrixSection(
  title: string,
  rows: ComparisonRow[],
  empty: string,
): MatrixSection {
  return {
    title,
    rows: rows.map((row) => ({ ...row, changed: rowValuesDiffer(row.values) })),
    empty,
  };
}

function rowValuesDiffer(values: Record<string, unknown>): boolean {
  return new Set(
    props.runs.map((run) => JSON.stringify(values[String(run.id)])),
  ).size > 1;
}

function matrixCellClass(row: MatrixRow, runId: number): string {
  const value = row.values[String(runId)];
  if (value === "—") return "muted";
  if (row.workflow) {
    const baseline = row.values[String(props.runs[0]?.id)];
    return runId !== props.runs[0]?.id && value !== baseline ? "workflow-difference" : "";
  }
  if (row.metric) {
    const ranked = cellClass(row.metric, runId);
    if (ranked) return ranked;
  }
  return row.changed ? "difference-neutral" : "";
}

function makeRow(label: string, getter: (run: ExecutionRunDetail) => string): ComparisonRow {
  return {
    label,
    values: Object.fromEntries(props.runs.map((run) => [String(run.id), getter(run)])),
  };
}

function buildMetricRow(metric: string, values: Record<string, unknown>): MetricRow {
  const numericValues = props.runs
    .map((run) => ({ runId: String(run.id), val: values[String(run.id)] }))
    .filter((item): item is { runId: string; val: number } => (
      typeof item.val === "number" && Number.isFinite(item.val)
    ));

  let delta: number | null = null;
  if (props.runs.length === 2 && numericValues.length === 2) {
    delta = numericalDelta(numericValues.map(item => item.val));
  }

  let bestRunId: string | null = null;
  if (numericValues.length >= 2) {
    const metricName = metricNameFromKey(metric);
    const higherBetter = HIGHER_IS_BETTER.has(metricName);
    const sorted = [...numericValues].sort((a, b) => (
      higherBetter ? b.val - a.val : a.val - b.val
    ));
    bestRunId = sorted[0].runId;
  }

  return { metric, values, delta, bestRunId };
}

function deriveErrorRow(metric: string, sourceKeys: string[]): MetricRow | null {
  const values: Record<string, number> = {};
  for (const run of props.runs) {
    const runId = String(run.id);
    for (const key of sourceKeys) {
      const value = props.diff[key]?.[runId];
      if (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1) {
        values[runId] = 1 - value;
        break;
      }
    }
  }
  return Object.keys(values).length > 0 ? buildMetricRow(metric, values) : null;
}

function metricRank(metric: string): number {
  const name = metricNameFromKey(metric);
  const index = METRIC_DISPLAY_ORDER.indexOf(name);
  return index === -1 ? METRIC_DISPLAY_ORDER.length : index;
}

function formatMetricName(key: string): string {
  const metricName = metricNameFromKey(key);
  const metricLabel = METRIC_LABELS[metricName] || metricName;
  const parts = key.split(".");
  if (parts.length <= 1) return metricLabel;
  const nodeId = parts.slice(0, -1).join(".");
  if (nodeId === "qualified_cv") return `Bound cross-validation · ${metricLabel}`;
  return `${formatNodeId(nodeId)} · ${metricLabel}`;
}

function metricNameFromKey(key: string): string {
  return key.split(".").pop() || key;
}

function formatValue(val: unknown): string {
  if (val === undefined || val === null) return "—";
  if (typeof val === "number") {
    return Number.isInteger(val) ? String(val) : scientificNumber(val, { decimalPlaces: 4 });
  }
  return String(val);
}

function displayDelta(row: { metric: string; delta: number | null }): string {
  return formatDelta(row.delta);
}

function numericalDelta(values: unknown[]): number | null {
  if (values.length !== 2 || !values.every(value => typeof value === "number" && Number.isFinite(value))) return null;
  const difference = (values[1] as number) - (values[0] as number);
  return Number.isFinite(difference) ? difference : null;
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${Number.isInteger(delta) ? delta : scientificNumber(delta, { decimalPlaces: 4 })}`;
}

function cellClass(row: MetricRow, runId: number): string {
  if (props.scientificComparison || !props.rankableMetrics?.includes(row.metric)) return "";
  if (row.bestRunId === String(runId)) return "metric-best";
  return "";
}

function deltaClass(row: MetricRow): string {
  if (props.scientificComparison || !props.rankableMetrics?.includes(row.metric)) return "";
  if (row.delta === null) return "";
  if (row.delta === 0) return "delta-zero";
  const higherBetter = HIGHER_IS_BETTER.has(metricNameFromKey(row.metric));
  const improvement = higherBetter ? row.delta > 0 : row.delta < 0;
  return improvement ? "delta-positive" : "delta-negative";
}

function formatParamValue(val: unknown): string {
  if (val === undefined) return "—";
  if (val === null) return "null";
  if (typeof val === "string") return val;
  if (typeof val === "number" || typeof val === "boolean") return String(val);
  if (Array.isArray(val)) return `[${val.slice(0, 5).map(formatParamValue).join(", ")}${val.length > 5 ? "..." : ""}]`;
  return JSON.stringify(val);
}

function formatRunKind(kind: string | null | undefined): string {
  switch (kind) {
    case "training": return "Training";
    case "batch_inference": return "Batch inference";
    case "data": return "Data prep";
    case "other": return "Other";
    default: return "Other";
  }
}

function formatModelVersion(run: ExecutionRunDetail): string {
  const ids = [
    ...new Set([
      ...(run.produced_artifact_uids ?? []),
      ...(run.attempted_artifact_uids ?? []),
      ...(run.succeeded_artifact_uids ?? []),
    ]),
  ];
  if (ids.length === 0) return "—";
  if (ids.length === 1) return shortUid(ids[0]);
  return `${ids.length} artifacts: ${ids.slice(0, 2).map(shortUid).join(", ")}${ids.length > 2 ? "..." : ""}`;
}

function formatWorkflowVersion(run: ExecutionRunDetail): string {
  const workflow = run.workflow_id == null ? "workflow —" : `workflow #${run.workflow_id}`;
  const version = run.workflow_version_id == null ? "version —" : `version #${run.workflow_version_id}`;
  return `${workflow}, ${version}`;
}

function formatArtifactList(ids: string[] | null | undefined): string {
  if (!ids || ids.length === 0) return "—";
  return ids.length === 1 ? shortUid(ids[0]) : `${ids.length} artifacts`;
}

function shortUid(uid: string): string {
  return uid.length > 12 ? `${uid.slice(0, 8)}...` : uid;
}

function inferDataSource(run: ExecutionRunDetail): string {
  const dataset = isRecord(run.source_metadata?.dataset) ? run.source_metadata.dataset : null;
  if (dataset) {
    const name = typeof dataset.name === "string" ? dataset.name : `Dataset #${dataset.experiment_id ?? "?"}`;
    const stage = typeof dataset.stage === "string" ? dataset.stage : null;
    return stage ? `${name} (${stage})` : name;
  }
  if (typeof run.source_type === "string" && run.source_type) return run.source_type;
  const sourceParam = findFirstStringByKey(run.params_snapshot, ["source", "source_type", "dataset", "dataset_id"]);
  return sourceParam || "—";
}

function inferWholeDataShape(run: ExecutionRunDetail): DataShape {
  const partition = inferPartitionShape(run);
  if (partition.train.samples != null || partition.test.samples != null) {
    return {
      samples: (partition.train.samples ?? 0) + (partition.test.samples ?? 0) || null,
      features: partition.train.features ?? partition.test.features,
    };
  }
  return findBestShape(run.results_summary) ?? { samples: null, features: null };
}

function inferPartition(run: ExecutionRunDetail): string {
  const partition = inferPartitionShape(run);
  const train = partition.train.samples;
  const test = partition.test.samples;
  if (train == null && test == null) return "—";
  const total = (train ?? 0) + (test ?? 0);
  const percent = total > 0 && test != null ? `, ${(test / total * 100).toFixed(0)}% test` : "";
  return `Train ${train ?? "—"} / Test ${test ?? "—"}${percent}`;
}

function inferSplitSettings(run: ExecutionRunDetail): string {
  const settings = Object.entries(run.params_snapshot ?? {}).flatMap(([nodeId, value]) => {
    if (!isRecord(value) || !("test_size" in value || "split_method" in value)) return [];
    const parts: string[] = [];
    if (value.split_method != null) parts.push(`method ${String(value.split_method)}`);
    if (typeof value.test_size === "number") parts.push(`test_size ${value.test_size}`);
    if (value.random_seed != null) parts.push(`seed ${value.random_seed}`);
    if (value.shuffle != null) parts.push(`shuffle ${String(value.shuffle)}`);
    return [`${nodeId}: ${parts.join(" · ")}`];
  });
  return settings.length ? settings.join("; ") : "Unavailable in recorded node parameters";
}

function inferPartitionShape(run: ExecutionRunDetail): { train: DataShape; test: DataShape } {
  const train = findShapeByLikelyKey(run.results_summary, ["X_train", "train", "cal", "X_cal"]);
  const test = findShapeByLikelyKey(run.results_summary, ["X_test", "test", "validation"]);
  const trainIndexCount = findArrayLengthByLikelyKey(run.results_summary, ["train_indices", "cal_indices"]);
  const testIndexCount = findArrayLengthByLikelyKey(run.results_summary, ["test_indices"]);
  return {
    train: {
      samples: train?.samples ?? trainIndexCount,
      features: train?.features ?? null,
    },
    test: {
      samples: test?.samples ?? testIndexCount,
      features: test?.features ?? null,
    },
  };
}

function formatDataShape(shape: DataShape): string {
  if (shape.samples == null && shape.features == null) return "—";
  if (shape.samples != null && shape.features != null) return `${shape.samples} samples × ${shape.features} features`;
  if (shape.samples != null) return `${shape.samples} samples`;
  return `${shape.features} features`;
}

function formatSettingPath(path: string): string {
  return path.replace(/[_-]+/g, " ");
}

function formatNodeId(nodeId: string): string {
  return nodeId.replace(/[_-]+/g, " ");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function findFirstStringByKey(value: unknown, keys: string[], depth = 0): string | null {
  if (depth > 5 || !isRecord(value)) return null;
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === "string" && candidate.trim()) return candidate;
    if (typeof candidate === "number") return String(candidate);
  }
  for (const child of Object.values(value)) {
    const found = findFirstStringByKey(child, keys, depth + 1);
    if (found) return found;
  }
  return null;
}


function findBestShape(value: unknown, depth = 0): DataShape | null {
  if (depth > 5) return null;
  const direct = shapeFromValue(value);
  if (direct.samples != null || direct.features != null) return direct;
  if (!isRecord(value)) return null;
  for (const child of Object.values(value)) {
    const found = findBestShape(child, depth + 1);
    if (found) return found;
  }
  return null;
}

function findShapeByLikelyKey(value: unknown, keyHints: string[], depth = 0): DataShape | null {
  if (depth > 5 || !isRecord(value)) return null;
  const normalizedHints = new Set(keyHints.map((hint) => hint.toLowerCase()));
  for (const [key, child] of Object.entries(value)) {
    if (normalizedHints.has(key.toLowerCase())) {
      const shape = findBestShape(child);
      if (shape) return shape;
    }
  }
  for (const child of Object.values(value)) {
    const found = findShapeByLikelyKey(child, keyHints, depth + 1);
    if (found) return found;
  }
  return null;
}

function findArrayLengthByLikelyKey(value: unknown, keyHints: string[], depth = 0): number | null {
  if (depth > 5 || !isRecord(value)) return null;
  const normalizedHints = new Set(keyHints.map((hint) => hint.toLowerCase()));
  for (const [key, child] of Object.entries(value)) {
    if (normalizedHints.has(key.toLowerCase()) && Array.isArray(child)) {
      return child.length;
    }
    if (normalizedHints.has(key.toLowerCase()) && isRecord(child)) {
      const length = child.n_samples ?? child.length;
      if (typeof length === "number") return length;
    }
  }
  for (const child of Object.values(value)) {
    const found = findArrayLengthByLikelyKey(child, keyHints, depth + 1);
    if (found != null) return found;
  }
  return null;
}

function shapeFromValue(value: unknown): DataShape {
  if (Array.isArray(value)) {
    if (value.length > 0 && Array.isArray(value[0])) {
      return { samples: value.length, features: value[0].length };
    }
    return { samples: value.length, features: null };
  }
  if (!isRecord(value)) return { samples: null, features: null };
  const nSamples = typeof value.n_samples === "number" ? value.n_samples : null;
  const nFeatures = typeof value.n_features === "number" ? value.n_features : null;
  if (nSamples != null || nFeatures != null) return { samples: nSamples, features: nFeatures };
  if (typeof value.length === "number") return { samples: value.length, features: null };
  if (Array.isArray(value.shape) && value.shape.length >= 2) {
    const samples = typeof value.shape[0] === "number" ? value.shape[0] : null;
    const features = typeof value.shape[1] === "number" ? value.shape[1] : null;
    return { samples, features };
  }
  if (Array.isArray(value.data)) return shapeFromValue(value.data);
  return { samples: null, features: null };
}
</script>

<style scoped>
.comparison-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.comparison-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.comparison-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ss-text-strong);
  font-size: 1rem;
  font-weight: 650;
}

.comparison-title i {
  color: var(--ss-text-secondary);
}

.comparison-empty {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 48px;
  color: var(--ss-text-muted);
  text-align: left;
}

.comparison-empty i {
  font-size: 2rem;
}

.qualification-note {
  margin: 0;
  padding: 0.5rem 0.75rem;
  border-left: 3px solid var(--ss-action-border);
  background: var(--ss-action-tint);
  color: var(--ss-action);
  font-size: 0.8rem;
}


.comparison-empty-inline {
  padding: 1rem;
  color: var(--ss-text-muted);
  text-align: left;
}

.metric-name {
  font-size: 0.82rem;
}

.metric-best {
  color: var(--ss-success);
  font-weight: 650;
}

.difference-neutral {
  background: var(--ss-action-tint);
  color: var(--ss-action);
  font-weight: 550;
}

.workflow-difference {
  background: var(--ss-action-tint);
  color: var(--ss-action);
  font-weight: 550;
}

.delta-positive {
  color: var(--ss-success);
  font-weight: 600;
}

.delta-negative {
  color: var(--ss-danger);
  font-weight: 600;
}

.delta-zero,
.muted {
  color: var(--ss-text-muted);
}

.matrix-scroll {
  overflow-x: auto;
  border: 1px solid var(--ss-border-strong);
  border-radius: 6px;
}

.comparison-matrix {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  color: var(--ss-action-text);
  font-size: 0.8rem;
}

.comparison-measure-column {
  width: 14rem;
}

.comparison-delta-column {
  width: 8rem;
}

.comparison-matrix th,
.comparison-matrix td {
  padding: 0.55rem 0.7rem;
  border-bottom: 1px solid var(--ss-border);
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
  white-space: normal;
}

.comparison-matrix thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--ss-surface-subtle);
  color: var(--ss-action-text);
  font-weight: 650;
}

.comparison-matrix thead th:first-child,
.comparison-matrix tbody th[scope="row"] {
  width: 14rem;
}

.comparison-matrix tbody th[scope="row"] {
  background: var(--ss-surface);
  font-weight: 600;
}

.matrix-section-row th {
  padding-block: 0.45rem;
  border-top: 2px solid var(--ss-border-strong);
  background: var(--ss-border);
  color: var(--ss-text-strong);
  font-size: 0.75rem;
  text-transform: uppercase;
}

.matrix-empty {
  color: var(--ss-text-muted);
  font-style: italic;
}

code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--ss-surface-subtle);
  color: var(--ss-text-secondary);
  font-size: 0.78rem;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

</style>
