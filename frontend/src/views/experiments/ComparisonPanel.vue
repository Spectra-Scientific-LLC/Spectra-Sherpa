<template>
  <div class="comparison-panel">
    <div class="comparison-header">
      <span class="comparison-title">
        <i class="pi pi-chart-bar"></i>
        Comparing {{ runs.length }} runs
      </span>
      <Button
        label="Back to Runs"
        icon="pi pi-arrow-left"
        class="p-button-text p-button-sm"
        @click="$emit('back')"
      />
    </div>

    <div v-if="runs.length === 0" class="comparison-empty">
      <i class="pi pi-info-circle"></i>
      <span>Select runs from the history tab to compare</span>
    </div>

    <template v-else>
      <!-- Metrics comparison table -->
      <div class="comparison-section">
        <h3 class="comparison-section-title">Metrics</h3>
        <DataTable
          :value="metricRows"
          stripedRows
          size="small"
          class="comparison-table"
        >
          <Column field="metric" header="Metric" style="width: 180px; font-weight: 500">
            <template #body="{ data }">
              <span class="metric-name">{{ formatMetricName(data.metric) }}</span>
            </template>
          </Column>
          <Column
            v-for="run in runs"
            :key="run.id"
            :header="run.name"
            style="min-width: 120px"
          >
            <template #body="{ data }">
              <span :class="cellClass(data, run.id)">
                {{ formatValue(data.values[String(run.id)]) }}
              </span>
            </template>
          </Column>
          <Column
            v-if="runs.length === 2"
            header="Delta"
            style="width: 120px"
          >
            <template #body="{ data }">
              <span :class="deltaClass(data.delta)">
                {{ formatDelta(data.delta) }}
              </span>
            </template>
          </Column>
        </DataTable>
      </div>

      <!-- Parameter diff -->
      <div v-if="paramDiffs.length > 0" class="comparison-section">
        <h3 class="comparison-section-title">Parameter Differences</h3>
        <div class="param-diff-list">
          <div
            v-for="diff in paramDiffs"
            :key="diff.path"
            class="param-diff-item"
          >
            <span class="param-path">{{ diff.path }}</span>
            <span class="param-values">
              <span
                v-for="(val, idx) in diff.values"
                :key="idx"
              >
                <span v-if="idx > 0" class="param-arrow"> &rarr; </span>
                <code>{{ formatParamValue(val) }}</code>
              </span>
            </span>
          </div>
        </div>
      </div>

      <div v-else class="comparison-section">
        <h3 class="comparison-section-title">Parameter Differences</h3>
        <p class="no-diff">All parameters are identical across compared runs.</p>
      </div>
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

// Higher-is-better metrics (green when higher)
const HIGHER_IS_BETTER = new Set([
  "r2", "accuracy", "explained_variance", "silhouette_score",
]);

interface MetricRow {
  metric: string;
  values: Record<string, unknown>;
  delta: number | null;
  bestRunId: string | null;
}

const metricRows = computed<MetricRow[]>(() => {
  return props.metricKeys.map((key) => {
    const values = props.diff[key] || {};
    const numericValues: { runId: string; val: number }[] = [];

    for (const [runId, val] of Object.entries(values)) {
      if (typeof val === "number" && !isNaN(val)) {
        numericValues.push({ runId, val });
      }
    }

    // For 2-run delta
    let delta: number | null = null;
    if (props.runs.length === 2 && numericValues.length === 2) {
      delta = numericValues[1].val - numericValues[0].val;
    }

    // Find best value
    const metricName = key.split(".").pop() || key;
    const higherBetter = HIGHER_IS_BETTER.has(metricName);
    let bestRunId: string | null = null;
    if (numericValues.length >= 2) {
      const sorted = [...numericValues].sort((a, b) =>
        higherBetter ? b.val - a.val : a.val - b.val
      );
      bestRunId = sorted[0].runId;
    }

    return { metric: key, values, delta, bestRunId };
  });
});

interface ParamDiff {
  path: string;
  values: unknown[];
}

const paramDiffs = computed<ParamDiff[]>(() => {
  if (props.runs.length < 2) return [];

  const allPaths = new Set<string>();
  for (const run of props.runs) {
    for (const [nodeId, params] of Object.entries(run.params_snapshot || {})) {
      if (typeof params === "object" && params) {
        for (const paramKey of Object.keys(params)) {
          allPaths.add(`${nodeId}.${paramKey}`);
        }
      }
    }
  }

  const diffs: ParamDiff[] = [];
  for (const path of [...allPaths].sort()) {
    const [nodeId, paramKey] = path.split(".", 2);
    const values = props.runs.map((run) => {
      const nodeParams = run.params_snapshot?.[nodeId];
      return nodeParams && typeof nodeParams === "object"
        ? (nodeParams as Record<string, unknown>)[paramKey]
        : undefined;
    });

    // Only show if values differ
    const serialized = values.map((v) => JSON.stringify(v));
    if (new Set(serialized).size > 1) {
      diffs.push({ path, values });
    }
  }
  return diffs;
});

function formatMetricName(key: string): string {
  const parts = key.split(".");
  // Show "node_id / metric" for clarity
  if (parts.length >= 2) {
    return `${parts[parts.length - 1]}`;
  }
  return key;
}

function formatValue(val: unknown): string {
  if (val === undefined || val === null) return "—";
  if (typeof val === "number") {
    return Number.isInteger(val) ? String(val) : val.toFixed(4);
  }
  if (Array.isArray(val)) {
    return `[${val.slice(0, 3).map((v) => (typeof v === "number" ? v.toFixed(2) : v)).join(", ")}${val.length > 3 ? "..." : ""}]`;
  }
  return String(val);
}

function formatDelta(delta: number | null): string {
  if (delta === null) return "—";
  const sign = delta > 0 ? "+" : "";
  return `${sign}${Number.isInteger(delta) ? delta : delta.toFixed(4)}`;
}

function formatParamValue(val: unknown): string {
  if (val === undefined) return "—";
  if (val === null) return "null";
  if (typeof val === "string") return `"${val}"`;
  return JSON.stringify(val);
}

function cellClass(row: MetricRow, runId: number): string {
  if (row.bestRunId === String(runId)) return "metric-best";
  return "";
}

function deltaClass(delta: number | null): string {
  if (delta === null) return "";
  if (delta > 0) return "delta-positive";
  if (delta < 0) return "delta-negative";
  return "delta-zero";
}
</script>

<style scoped>
.comparison-panel {
  display: flex;
  flex-direction: column;
  gap: 20px;
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
  font-weight: 600;
  font-size: 1rem;
  color: #1e293b;
}

.comparison-title i {
  color: #3b82f6;
}

.comparison-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px;
  color: #94a3b8;
  text-align: center;
}

.comparison-empty i {
  font-size: 2rem;
}

.comparison-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.comparison-section-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: #475569;
  margin: 0;
}

.comparison-table {
  font-size: 0.85rem;
}

.metric-name {
  font-family: monospace;
  font-size: 0.8rem;
}

.metric-best {
  color: #16a34a;
  font-weight: 600;
}

.delta-positive {
  color: #2563eb;
  font-weight: 500;
}

.delta-negative {
  color: #dc2626;
  font-weight: 500;
}

.delta-zero {
  color: #94a3b8;
}

.param-diff-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px 16px;
}

.param-diff-item {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.85rem;
}

.param-path {
  font-family: monospace;
  color: #475569;
  min-width: 180px;
  font-size: 0.8rem;
}

.param-values code {
  background: #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.8rem;
}

.param-arrow {
  color: #94a3b8;
  margin: 0 2px;
}

.no-diff {
  color: #94a3b8;
  font-size: 0.85rem;
  font-style: italic;
  margin: 0;
}
</style>
