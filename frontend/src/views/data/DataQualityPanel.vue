<template>
  <div class="dq-panel">
    <div class="dq-header">
      <span v-if="priorityLabel" class="dq-priority-label">{{ priorityLabel }}</span>
      <i v-else class="pi pi-check-circle"></i>
      <span>Data Quality Summary</span>
    </div>

    <div v-if="loading" class="dq-loading">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <span>Analyzing file...</span>
    </div>

    <div v-else-if="!datasetDict" class="dq-empty">
      <i class="pi pi-info-circle"></i>
      <span>Select a file to view quality metrics</span>
    </div>

    <div v-else class="dq-content">
      <div v-if="targetLabels.length > 0" class="dq-labels">
        <span class="dq-range-label">
          Target labels ({{ targetLabels.length }})
          <span v-if="targetUnits"> · {{ targetUnits }}</span>
        </span>
        <div class="dq-label-list">
          <Tag
            v-for="label in targetLabels"
            :key="label"
            :value="label"
            severity="success"
            class="dq-label-tag"
          />
        </div>
      </div>

      <div v-if="classLabels.length" class="dq-labels">
        <span class="dq-range-label">Class labels ({{ classLabels.length }})</span>
        <div class="dq-label-list">
          <Tag v-for="label in classLabels" :key="label" :value="label" severity="success" />
        </div>
      </div>
      <div v-if="targetQuality" class="dq-target-quality">
        <span class="dq-range-label">Reference Values</span>
        <div
          class="dq-target-card"
          :class="{
            'dq-target-card--warning': targetQuality.partialRows > 0 || targetQuality.emptyRows > 0,
          }"
        >
          <div class="dq-target-main">
            <strong>
              {{ targetQuality.anyRows.toLocaleString() }} /
              {{ targetQuality.rowCount.toLocaleString() }}
            </strong>
            <span>samples have at least one reference value</span>
          </div>
          <div v-if="targetQuality.nTargets > 1" class="dq-target-main">
            <strong>
              {{ targetQuality.allRows.toLocaleString() }} /
              {{ targetQuality.rowCount.toLocaleString() }}
            </strong>
            <span>samples have all {{ targetQuality.nTargets }} target properties</span>
          </div>
          <p
            v-if="
              targetQuality.partialRows > 0 &&
              datasetDict?.target_context?.target_type !== 'categorical'
            "
            class="dq-target-warning"
          >
            Multi-target regression will use only complete rows unless you choose a single target
            property.
          </p>
          <div v-if="targetQuality.perTarget.length > 1" class="dq-target-list">
            <span v-for="item in targetQuality.perTarget" :key="item.name" class="dq-target-count">
              {{ item.name }}: {{ item.count.toLocaleString() }}
            </span>
          </div>
        </div>
      </div>

      <!-- QC flags -->
      <div class="dq-flags">
        <span class="dq-range-label">QC Checks</span>
        <div class="dq-flag-list">
          <div v-for="flag in qcFlags" :key="flag.message" class="dq-flag">
            <Tag
              :severity="flag.severity"
              :value="
                flag.severity === 'success' ? 'OK' : flag.severity === 'warning' ? 'WARN' : 'INFO'
              "
              class="dq-flag-badge"
            />
            <span class="dq-flag-message">{{ flag.message }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import Tag from "primevue/tag";
import ProgressSpinner from "primevue/progressspinner";
import type { SherpaDatasetDict } from "@/types";

const props = withDefaults(
  defineProps<{
    datasetDict: SherpaDatasetDict | null;
    loading?: boolean;
    priorityLabel?: string;
    selectedRowIndexes?: number[] | null;
  }>(),
  { loading: false, priorityLabel: "", selectedRowIndexes: null },
);

function selectedRows<T>(rows: T[]): T[] {
  return props.selectedRowIndexes
    ? props.selectedRowIndexes
        .filter((index) => index >= 0 && index < rows.length)
        .map((index) => rows[index])
    : rows;
}

// Scan the loaded matrix once. Checkbox changes aggregate these small row
// summaries, not the spectral matrix again.
const rowQuality = computed(() =>
  (props.datasetDict?.data ?? []).map((row) => {
    const values = Array.isArray(row) ? row : [];
    return {
      total: values.length,
      missing: values.filter((value) => value == null || !Number.isFinite(value)).length,
    };
  }),
);

const meta = computed(() => {
  const m = props.datasetDict?.metadata as Record<string, unknown> | undefined;
  const targetContext = props.datasetDict?.target_context;
  return {
    labels: (m?.labels ?? m?.sample_labels ?? []) as string[],
    wavenumbers: (m?.wavenumbers ?? []) as number[],
    is_spectra: (m?.is_spectra ?? false) as boolean,
    data_role: (m?.data_role ?? m?.["sherpa.data_role"] ?? null) as string | null,
    spectral_technique: (m?.spectral_technique ?? null) as string | null,
    target_class_names: (targetContext?.class_names ?? m?.class_names ?? []) as string[],
  };
});

const targetUnits = computed(() => props.datasetDict?.target_context?.target_units ?? "");
const sampleLabels = computed(() => {
  if (meta.value.labels.length) return selectedRows(meta.value.labels);
  const yLabels = props.datasetDict?.y_axis?.labels;
  return Array.isArray(yLabels) ? selectedRows(yLabels).map((label) => String(label)) : [];
});
const targetLabels = computed(() => {
  const context = props.datasetDict?.target_context;
  const labels = context?.target_names ?? (context?.target_name ? [context.target_name] : []);
  return Array.isArray(labels) ? labels.map((label) => String(label)).filter(Boolean) : [];
});

const classLabels = computed(() => {
  const labels = props.datasetDict?.target_context?.class_names ?? meta.value.target_class_names;
  return Array.isArray(labels) ? labels.map(String) : [];
});

function targetRows(target: SherpaDatasetDict["target"]): unknown[][] {
  if (!Array.isArray(target) || target.length === 0) return [];
  const first = target[0];
  if (Array.isArray(first)) return target.map((row) => (Array.isArray(row) ? row : [row]));
  return target.map((value) => [value]);
}

function hasTargetValue(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (props.datasetDict?.target_context?.target_type === "categorical") return trimmed.length > 0;
    return trimmed.length > 0 && Number.isFinite(Number(trimmed));
  }
  return false;
}

const targetQuality = computed(() => {
  const rows = selectedRows(targetRows(props.datasetDict?.target ?? null));
  if (!rows.length) return null;
  const nTargets = Math.max(targetLabels.value.length, ...rows.map((row) => row.length));
  if (nTargets <= 0) return null;

  let anyRows = 0;
  let allRows = 0;
  let partialRows = 0;
  let emptyRows = 0;
  const perTarget = Array.from({ length: nTargets }, (_, index) => ({
    name: targetLabels.value[index] || `Target ${index + 1}`,
    count: 0,
  }));

  for (const row of rows) {
    const present = Array.from({ length: nTargets }, (_, index) => hasTargetValue(row[index]));
    const rowAny = present.some(Boolean);
    const rowAll = present.every(Boolean);
    if (rowAny) anyRows += 1;
    if (rowAll) allRows += 1;
    if (rowAny && !rowAll) partialRows += 1;
    if (!rowAny) emptyRows += 1;
    present.forEach((ok, index) => {
      if (ok) perTarget[index].count += 1;
    });
  }

  return {
    rowCount: rows.length,
    nTargets,
    anyRows,
    allRows,
    partialRows,
    emptyRows,
    perTarget,
  };
});

const isSpectralDataset = computed(() => {
  const role = meta.value.data_role;
  if (role === "X_spectra") return true;
  if (role === "X_features") return false;
  return meta.value.is_spectra || meta.value.wavenumbers.length > 1;
});

interface QcFlag {
  severity: "success" | "warning" | "info";
  message: string;
}

const qcFlags = computed<QcFlag[]>(() => {
  const sd = props.datasetDict;
  if (!sd) return [];
  const flags: QcFlag[] = [];

  const sampleLabel = isSpectralDataset.value ? "spectra" : "samples";
  const featureLabel = isSpectralDataset.value ? "spectral variables" : "features";

  // Sample count
  const sampleCount = props.selectedRowIndexes?.length ?? sd.n_samples;
  if (sampleCount >= 3) {
    flags.push({ severity: "success", message: `Multiple ${sampleLabel} loaded` });
  } else {
    flags.push({
      severity: "warning",
      message: `Very few ${sampleLabel} — statistical methods may be unreliable`,
    });
  }

  // Feature count
  if (sd.n_features >= 2) {
    flags.push({
      severity: "success",
      message: `${sd.n_features.toLocaleString()} ${featureLabel} detected`,
    });
  } else {
    flags.push({ severity: "warning", message: "Only one feature detected" });
  }

  // Missing/non-finite values
  let total = 0;
  let missing = 0;
  const selectedQuality = selectedRows(rowQuality.value);
  for (const row of selectedQuality) {
    if (!row) continue;
    total += row.total;
    missing += row.missing;
  }
  if (total > 0) {
    const previewRows = selectedQuality.length;
    const previewCols = Array.isArray(sd.data?.[0]) ? sd.data[0].length : 0;
    const previewOnly = previewRows < sampleCount || previewCols < sd.n_features;
    const scope = previewOnly ? " in displayed preview rows" : "";
    if (missing === 0) {
      flags.push({ severity: "success", message: `No missing values detected${scope}` });
    } else {
      const pct = ((missing / total) * 100).toFixed(2);
      flags.push({
        severity: "warning",
        message: `${missing.toLocaleString()} missing values${scope} (${pct}%)`,
      });
    }
  }

  if (targetQuality.value) {
    const tq = targetQuality.value;
    if (tq.nTargets > 1 && tq.partialRows > 0) {
      flags.push({
        severity: "warning",
        message: `Reference targets are incomplete: ${tq.allRows.toLocaleString()} samples have all ${tq.nTargets} targets`,
      });
    } else if (tq.emptyRows > 0) {
      flags.push({
        severity: "warning",
        message: `${tq.emptyRows.toLocaleString()} samples have no reference value`,
      });
    } else {
      flags.push({ severity: "success", message: "Reference values detected" });
    }
  }

  // Spectral range (only if numeric spectral axis)
  const wn = meta.value.wavenumbers;
  if (isSpectralDataset.value && wn.length > 1) {
    const range = Math.abs(wn[wn.length - 1] - wn[0]);
    if (range > 100) {
      flags.push({ severity: "success", message: "Adequate spectral range" });
    } else {
      flags.push({ severity: "warning", message: "Narrow spectral range" });
    }
  }

  // Labels
  if (sampleLabels.value.length === 0) {
    flags.push({
      severity: "info",
      message:
        targetLabels.value.length || classLabels.value.length
          ? "No sample IDs detected; target labels are available"
          : "No sample IDs detected",
    });
  }

  return flags;
});
</script>

<style scoped>
.dq-panel {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 20px;
}

.dq-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 0.95rem;
  color: #1e293b;
  margin-bottom: 16px;
}

.dq-header i {
  color: #3b82f6;
}

.dq-priority-label {
  align-items: center;
  background: #2563eb;
  border-radius: 999px;
  color: #ffffff;
  display: inline-flex;
  font-size: 0.75rem;
  height: 1.5rem;
  justify-content: center;
  width: 1.5rem;
}

.dq-loading,
.dq-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: #94a3b8;
  text-align: center;
  font-size: 0.9rem;
}

.dq-empty i {
  font-size: 1.5rem;
}

.dq-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.dq-range-label {
  font-size: 0.8rem;
  color: #64748b;
  font-weight: 500;
}

.dq-labels {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dq-label-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.dq-label-list--expanded {
  max-height: 160px;
  overflow-y: auto;
}

.dq-label-tag {
  font-size: 0.75rem;
}

.dq-label-toggle {
  font-size: 0.75rem;
  color: #3b82f6;
  cursor: pointer;
  font-weight: 500;
  padding: 2px 6px;
}

.dq-label-toggle:hover {
  text-decoration: underline;
}

.dq-flags {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dq-target-quality {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dq-target-card {
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: #eff6ff;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dq-target-card--warning {
  border-color: #fed7aa;
  background: #fff7ed;
}

.dq-target-main {
  display: flex;
  gap: 6px;
  align-items: baseline;
  font-size: 0.84rem;
  color: #334155;
}

.dq-target-main strong {
  color: #0f172a;
}

.dq-target-warning {
  margin: 0;
  color: #9a3412;
  font-size: 0.8rem;
  line-height: 1.35;
}

.dq-target-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  max-height: 96px;
  overflow-y: auto;
}

.dq-target-count {
  font-size: 0.72rem;
  color: #475569;
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(148, 163, 184, 0.38);
  border-radius: 999px;
  padding: 2px 7px;
}

.dq-flag-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.dq-flag {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dq-flag-badge {
  font-size: 0.65rem;
  min-width: 40px;
  text-align: center;
}

.dq-flag-message {
  font-size: 0.85rem;
  color: #475569;
}
</style>
