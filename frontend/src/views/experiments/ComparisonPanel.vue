<template>
  <div class="comparison-panel">
    <div class="comparison-header">
      <span class="comparison-title">
        <i class="pi pi-chart-bar"></i>
        Comparing {{ runs.length }} checked runs
      </span>
      <Button
        label="Back to Run History"
        icon="pi pi-arrow-left"
        class="p-button-text p-button-sm"
        @click="$emit('back')"
      />
    </div>

    <div v-if="runs.length === 0" class="comparison-empty">
      <i class="pi pi-info-circle"></i>
      <span>Check runs from Run History to compare them.</span>
    </div>

    <template v-else>
      <section class="comparison-section">
        <div class="section-heading">
          <h3>Run Context</h3>
          <p>Which model version was run, when it ran, and what artifact lineage it produced.</p>
        </div>
        <DataTable :value="runContextRows" stripedRows size="small" class="comparison-table">
          <Column field="label" header="" style="width: 170px; font-weight: 600" />
          <Column v-for="run in runs" :key="run.id" :header="run.name" style="min-width: 160px">
            <template #body="{ data }">
              <span :class="{ muted: data.values[String(run.id)] === '—' }">
                {{ data.values[String(run.id)] }}
              </span>
            </template>
          </Column>
        </DataTable>
      </section>

      <section class="comparison-section">
        <div class="section-heading">
          <h3>Data & Partition</h3>
          <p>Run comparability starts with the same data shape and the same training/test split.</p>
        </div>
        <DataTable :value="dataPartitionRows" stripedRows size="small" class="comparison-table">
          <Column field="label" header="" style="width: 170px; font-weight: 600" />
          <Column v-for="run in runs" :key="run.id" :header="run.name" style="min-width: 160px">
            <template #body="{ data }">
              <span :class="{ muted: data.values[String(run.id)] === '—' }">
                {{ data.values[String(run.id)] }}
              </span>
            </template>
          </Column>
        </DataTable>
      </section>

      <section class="comparison-section">
        <div class="section-heading">
          <h3>Workflow Nodes</h3>
          <p>The active node path for each checked run. Differences here explain most metric changes.</p>
        </div>
        <div class="node-compare-grid">
          <article v-for="run in runs" :key="run.id" class="node-run-card">
            <strong>{{ run.name }}</strong>
            <div class="node-chip-list">
              <span
                v-for="node in nodeSummaries[String(run.id)]"
                :key="node.id"
                class="node-chip"
                :title="node.id"
              >
                {{ node.label }}
              </span>
              <span v-if="nodeSummaries[String(run.id)]?.length === 0" class="muted">No nodes captured</span>
            </div>
          </article>
        </div>
      </section>

      <section class="comparison-section">
        <div class="section-heading">
          <h3>Run Results</h3>
          <p>Scientist-facing performance and diagnostic scalars parsed from the saved run outputs.</p>
        </div>
        <DataTable :value="metricRows" stripedRows size="small" class="comparison-table">
          <template #empty>
            <div class="comparison-empty-inline">
              No comparable scalar result metrics were found for these runs.
            </div>
          </template>
          <Column field="metric" header="Metric" style="width: 180px; font-weight: 600">
            <template #body="{ data }">
              <span class="metric-name">{{ formatMetricName(data.metric) }}</span>
            </template>
          </Column>
          <Column v-for="run in runs" :key="run.id" :header="run.name" style="min-width: 130px">
            <template #body="{ data }">
              <span :class="cellClass(data, run.id)">
                {{ formatValue(data.values[String(run.id)]) }}
              </span>
            </template>
          </Column>
          <Column v-if="runs.length === 2" header="Delta" style="width: 120px">
            <template #body="{ data }">
              <span :class="deltaClass(data)">
                {{ formatDelta(data.delta) }}
              </span>
            </template>
          </Column>
        </DataTable>
      </section>

      <section class="comparison-section">
        <div class="section-heading">
          <h3>Settings Differences</h3>
          <p>Only parameters that differ across checked runs are shown.</p>
        </div>
        <DataTable
          v-if="paramDiffRows.length > 0"
          :value="paramDiffRows"
          stripedRows
          size="small"
          class="comparison-table"
        >
          <Column field="label" header="Setting" style="width: 220px; font-weight: 600" />
          <Column v-for="run in runs" :key="run.id" :header="run.name" style="min-width: 140px">
            <template #body="{ data }">
              <code>{{ data.values[String(run.id)] }}</code>
            </template>
          </Column>
        </DataTable>
        <p v-else class="no-diff">All captured parameters are identical across checked runs.</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import type { ExecutionRunDetail } from "@/types";

const props = defineProps<{
  runs: ExecutionRunDetail[];
  metricKeys: string[];
  diff: Record<string, Record<string, unknown>>;
}>();

defineEmits<{
  back: [];
}>();

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

interface NodeSummary {
  id: string;
  label: string;
}

const runContextRows = computed<ComparisonRow[]>(() => [
  makeRow("Run time", (run) => formatTimestamp(run.executed_at)),
  makeRow("Model version", (run) => formatModelVersion(run)),
  makeRow("Workflow version", (run) => formatWorkflowVersion(run)),
  makeRow("Run kind", (run) => formatRunKind(run.run_kind)),
  makeRow("Status", (run) => run.status || "—"),
  makeRow("Artifacts", (run) => formatArtifactList(run.model_ids)),
]);

const dataPartitionRows = computed<ComparisonRow[]>(() => [
  makeRow("Data source", (run) => inferDataSource(run)),
  makeRow("Data dimensions", (run) => formatDataShape(inferWholeDataShape(run))),
  makeRow("Partition", (run) => inferPartition(run)),
  makeRow("Split settings", (run) => inferSplitSettings(run)),
]);

const nodeSummaries = computed<Record<string, NodeSummary[]>>(() => {
  const byRun: Record<string, NodeSummary[]> = {};
  for (const run of props.runs) {
    const nodeIds = new Set<string>();
    for (const source of [run.params_snapshot, run.results_summary, run.node_statuses ?? {}]) {
      for (const key of Object.keys(source || {})) nodeIds.add(key);
    }
    byRun[String(run.id)] = [...nodeIds].map((id) => ({
      id,
      label: formatNodeLabel(id, run.results_summary?.[id]),
    }));
  }
  return byRun;
});

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
      values: Object.fromEntries(
        props.runs.map((run, idx) => [String(run.id), formatParamValue(rawValues[idx])]),
      ),
    });
  }
  return rows;
});

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
    delta = numericValues[1].val - numericValues[0].val;
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
  return `${formatNodeId(nodeId)} · ${metricLabel}`;
}

function metricNameFromKey(key: string): string {
  return key.split(".").pop() || key;
}

function formatValue(val: unknown): string {
  if (val === undefined || val === null) return "—";
  if (typeof val === "number") {
    return Number.isInteger(val) ? String(val) : val.toFixed(4);
  }
  return String(val);
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${Number.isInteger(delta) ? delta : delta.toFixed(4)}`;
}

function cellClass(row: MetricRow, runId: number): string {
  if (row.bestRunId === String(runId)) return "metric-best";
  return "";
}

function deltaClass(row: MetricRow): string {
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

function formatTimestamp(value: string): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
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
  const ids = [...new Set([...(run.model_ids ?? []), ...(run.applied_artifact_uids ?? [])])];
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
  const values = collectKeysDeep(run.params_snapshot, ["test_size", "split_method", "random_seed", "shuffle"]);
  const parts: string[] = [];
  if (values.split_method != null) parts.push(String(values.split_method));
  if (typeof values.test_size === "number") parts.push(`${(values.test_size * 100).toFixed(0)}% test`);
  if (values.random_seed != null) parts.push(`seed ${values.random_seed}`);
  if (values.shuffle != null) parts.push(`shuffle ${values.shuffle ? "on" : "off"}`);
  return parts.length > 0 ? parts.join(" · ") : "—";
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

function formatNodeLabel(nodeId: string, result: unknown): string {
  const type = findFirstStringByKey(result, ["model_type", "task_type", "type", "output_type"]);
  const cleanId = nodeId
    .replace(/^node[_-]?/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
  return type ? `${cleanId || nodeId} · ${type}` : cleanId || nodeId;
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

function collectKeysDeep(value: unknown, keys: string[], depth = 0, out: Record<string, unknown> = {}): Record<string, unknown> {
  if (depth > 5 || !isRecord(value)) return out;
  for (const key of keys) {
    if (out[key] === undefined && key in value) out[key] = value[key];
  }
  for (const child of Object.values(value)) collectKeysDeep(child, keys, depth + 1, out);
  return out;
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
  for (const [key, child] of Object.entries(value)) {
    if (keyHints.some((hint) => key.toLowerCase().includes(hint.toLowerCase()))) {
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
  for (const [key, child] of Object.entries(value)) {
    if (keyHints.some((hint) => key.toLowerCase().includes(hint.toLowerCase())) && Array.isArray(child)) {
      return child.length;
    }
    if (keyHints.some((hint) => key.toLowerCase().includes(hint.toLowerCase())) && isRecord(child)) {
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
  gap: 22px;
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
  color: #1f2937;
  font-size: 1rem;
  font-weight: 650;
}

.comparison-title i {
  color: #475569;
}

.comparison-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px;
  color: #64748b;
  text-align: center;
}

.comparison-empty i {
  font-size: 2rem;
}

.comparison-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.section-heading h3 {
  margin: 0;
  color: #334155;
  font-size: 0.95rem;
  font-weight: 650;
}

.section-heading p {
  margin: 0;
  color: #64748b;
  font-size: 0.82rem;
}

.comparison-table {
  font-size: 0.84rem;
}

.comparison-empty-inline {
  padding: 1rem;
  color: #64748b;
  text-align: center;
}

.metric-name {
  font-size: 0.82rem;
}

.metric-best {
  color: #15803d;
  font-weight: 650;
}

.delta-positive {
  color: #15803d;
  font-weight: 600;
}

.delta-negative {
  color: #b91c1c;
  font-weight: 600;
}

.delta-zero,
.muted {
  color: #94a3b8;
}

.node-compare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}

.node-run-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}

.node-run-card strong {
  color: #334155;
  font-size: 0.88rem;
}

.node-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.node-chip {
  max-width: 100%;
  padding: 3px 8px;
  overflow: hidden;
  border: 1px solid #dbe4ef;
  border-radius: 999px;
  color: #475569;
  font-size: 0.75rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

code {
  padding: 2px 6px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #475569;
  font-size: 0.78rem;
}

.no-diff {
  margin: 0;
  color: #64748b;
  font-size: 0.85rem;
}
</style>
