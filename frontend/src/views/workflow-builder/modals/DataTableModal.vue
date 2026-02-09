<template>
  <Dialog
    v-model:visible="visible"
    :header="title"
    :style="{ width: '90vw', maxWidth: '1400px' }"
    modal
    :draggable="false"
    class="data-table-modal"
  >
    <div class="table-container">
      <!-- Controls -->
      <div class="table-controls">
        <div class="control-group">
          <label>Rows</label>
          <Dropdown
            v-model="rowLimit"
            :options="rowLimitOptions"
            optionLabel="label"
            optionValue="value"
            class="row-limit-dropdown"
          />
        </div>

        <div class="control-group">
          <label>Precision</label>
          <Dropdown
            v-model="precision"
            :options="precisionOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <div class="control-group stats-summary">
          <span class="stat-item">
            <strong>{{ dataShape.rows }}</strong> rows
          </span>
          <span class="stat-item">
            <strong>{{ dataShape.cols }}</strong> columns
          </span>
          <span v-if="dataShape.rows > rowLimit" class="stat-item warning">
            Showing first {{ rowLimit }} rows
          </span>
        </div>

        <Button
          icon="pi pi-download"
          label="Export CSV"
          class="p-button-outlined p-button-sm"
          @click="exportCSV"
        />
      </div>

      <!-- Data Table -->
      <div class="table-wrapper">
        <DataTable
          v-if="tableData.length > 0"
          :value="tableData"
          :scrollable="true"
          scrollHeight="60vh"
          :virtualScrollerOptions="{ itemSize: 40 }"
          class="data-table"
          stripedRows
        >
          <Column
            v-for="col in tableColumns"
            :key="col.field"
            :field="col.field"
            :header="col.header"
            :sortable="true"
            :style="{ minWidth: col.width }"
          >
            <template #body="{ data }">
              <span
                :class="{
                  'numeric-cell': col.isNumeric,
                  'label-cell': col.field === '_label',
                }"
                :title="col.field === '_label' ? (data._label_full || data._label || '') : ''"
              >
                {{ formatValue(data[col.field], col.isNumeric) }}
              </span>
            </template>
          </Column>
        </DataTable>

        <div v-else class="empty-table">
          <i class="pi pi-table" />
          <p>No data to display</p>
          <small>Execute the node first to see results</small>
        </div>
      </div>

      <!-- Metadata Panel -->
      <div v-if="hasMetadata" class="metadata-panel">
        <h4>Metadata</h4>
        <div class="metadata-grid">
          <div v-for="(value, key) in displayMetadata" :key="key" class="metadata-item">
            <span class="metadata-key">{{ key }}:</span>
            <span class="metadata-value">{{ formatMetadataValue(value) }}</span>
          </div>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";

interface Props {
  modelValue: boolean;
  nodeOutput: any;
  nodeType: string;
  nodeLabel: string;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

// Debug: log when modal opens or data changes
watch([visible, () => props.nodeOutput], ([isVisible, output]) => {
  if (isVisible) {
    console.log('[DataTableModal] Modal opened with:', {
      hasOutput: !!output,
      hasData: !!output?.data,
      dataType: output?.data ? (Array.isArray(output.data) ? 'array' : typeof output.data) : 'none',
      dataLength: Array.isArray(output?.data) ? output.data.length : 'N/A',
      firstRowType: Array.isArray(output?.data) && output.data[0] ? (Array.isArray(output.data[0]) ? 'array' : typeof output.data[0]) : 'N/A',
      outputKeys: output ? Object.keys(output) : [],
    });
  }
}, { immediate: true });

const title = computed(() => `${props.nodeLabel} - Data View`);

// Display options
const rowLimit = ref(100);
const precision = ref(6);

const rowLimitOptions = [
  { label: "50 rows", value: 50 },
  { label: "100 rows", value: 100 },
  { label: "500 rows", value: 500 },
  { label: "1000 rows", value: 1000 },
  { label: "All rows", value: 10000 },
];

const precisionOptions = [
  { label: "2 decimals", value: 2 },
  { label: "4 decimals", value: 4 },
  { label: "6 decimals", value: 6 },
  { label: "8 decimals", value: 8 },
];

function normalizeSampleLabel(value: any): string {
  if (value === null || value === undefined) return "";

  if (Array.isArray(value)) {
    const readable = value
      .slice()
      .reverse()
      .find((item) => typeof item === "string" && item.trim().length > 0);
    if (readable) return readable.trim();
    return value.map((item) => normalizeSampleLabel(item)).filter(Boolean).join(" | ");
  }

  if (typeof value === "object") {
    if ("label" in value && typeof value.label === "string" && value.label.trim().length > 0) {
      return value.label.trim();
    }
    if ("name" in value && typeof value.name === "string" && value.name.trim().length > 0) {
      return value.name.trim();
    }
    return String(value);
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    // Handle stringified tuple/list labels like:
    // "[datetime.datetime(...), 'Human Sample Name']"
    if (trimmed.startsWith("[") || trimmed.startsWith("(")) {
      const quoted = [...trimmed.matchAll(/'([^']+)'|\"([^\"]+)\"/g)]
        .map((match) => match[1] || match[2])
        .filter(Boolean);
      if (quoted.length > 0) return quoted[quoted.length - 1];
    }
    return trimmed;
  }

  return String(value);
}

function compactSampleLabel(value: any): string {
  const text = normalizeSampleLabel(value).replace(/\s+/g, " ").trim();
  if (text.length <= 64) return text;
  return `${text.slice(0, 40)}...${text.slice(-18)}`;
}

// Check if data is Plotly visualization format (from CONTOUR_PLOT, PLOT nodes)
const isPlotlyFormat = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return false;

  const data = output.data;
  if (!Array.isArray(data)) return false;

  // Check if data contains Plotly trace objects
  return data.length > 0 && typeof data[0] === 'object' && data[0]?.type;
});

// Extract underlying data from Plotly format for display
const extractedData = computed(() => {
  if (!isPlotlyFormat.value) return null;

  const trace = props.nodeOutput?.data?.[0];
  if (!trace) return null;

  // For heatmap/contour: extract z matrix
  if (trace.z && Array.isArray(trace.z)) {
    return {
      data: trace.z,
      x: trace.x,
      y: trace.y,
    };
  }

  // For scatter/line: zip x and y into rows
  if (trace.x && trace.y) {
    const rows: number[][] = [];
    for (let i = 0; i < trace.x.length; i++) {
      rows.push([trace.x[i], trace.y[i]]);
    }
    return { data: rows, x: null, y: null };
  }

  return null;
});

// Compute data shape
const dataShape = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return { rows: 0, cols: 0 };

  // Handle Plotly format - extract shape from traces
  if (isPlotlyFormat.value && extractedData.value?.data) {
    const data = extractedData.value.data;
    const rows = data.length;
    const cols = Array.isArray(data[0]) ? data[0].length : 1;
    return { rows, cols };
  }

  const data = output.data;
  if (!Array.isArray(data)) return { rows: 0, cols: 0 };

  const rows = data.length;
  const cols = Array.isArray(data[0]) ? data[0].length : 1;

  return { rows, cols };
});

// Build table columns
const tableColumns = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return [];

  // Use extracted data for Plotly format
  const sourceData = isPlotlyFormat.value ? extractedData.value : null;
  const data = sourceData?.data || output.data;
  const metadata = output.metadata || {};

  // Get axis labels from Plotly format or metadata
  const wavenumbers = sourceData?.x || metadata.wavenumbers || metadata.x_axis;

  // Check for decomposition output types (MCR, PCA)
  const isMCR = metadata.type === "MCR_ALS";
  const isPCA = metadata.type === "PCA" || metadata.isPCA;
  const pcLabels = metadata.pc_labels || [];
  const mcrLabels = metadata.labels || [];

  // Check if it's 2D data
  if (Array.isArray(data[0])) {
    const cols = data[0].length;
    const columns: any[] = [];

    // Add row index column
    columns.push({
      field: "_index",
      header: "#",
      width: "60px",
      isNumeric: true,
    });

    // Add label column if available (for spectra names)
    if (metadata.sample_labels && metadata.sample_labels.length > 0) {
      columns.push({
        field: "_label",
        header: "Sample",
        width: "260px",
        isNumeric: false,
      });
    } else if (!isMCR && !isPCA && metadata.labels && metadata.labels.length > 0) {
      columns.push({
        field: "_label",
        header: "Label",
        width: "260px",
        isNumeric: false,
      });
    }

    // Add data columns (limit to reasonable number for display)
    const maxCols = Math.min(cols, 50);
    for (let i = 0; i < maxCols; i++) {
      let header: string;
      if (isPCA) {
        // PCA: use PC labels like "PC1 (45.2%)"
        header = pcLabels[i] || `PC${i + 1}`;
      } else if (isMCR) {
        // MCR: use component labels
        header = mcrLabels[i] || `Component ${i + 1}`;
      } else if (wavenumbers && wavenumbers.length > i && wavenumbers[i] != null) {
        // Spectra: use wavenumber values (only if available and valid)
        header = `${wavenumbers[i]?.toFixed?.(1) || wavenumbers[i]}`;
      } else {
        // Default: use sequential numbers starting from 1
        header = `${i + 1}`;
      }
      columns.push({
        field: `col_${i}`,
        header,
        width: isPCA || isMCR ? "140px" : "100px",
        isNumeric: true,
      });
    }

    if (cols > maxCols) {
      columns.push({
        field: "_truncated",
        header: `... +${cols - maxCols} more`,
        width: "120px",
        isNumeric: false,
      });
    }

    return columns;
  } else {
    // 1D data
    return [
      { field: "_index", header: "#", width: "60px", isNumeric: true },
      { field: "value", header: "Value", width: "150px", isNumeric: true },
    ];
  }
});

// Build table data
const tableData = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return [];

  // Use extracted data for Plotly format
  const sourceData = isPlotlyFormat.value ? extractedData.value : null;
  const data = sourceData?.data || output.data;
  const metadata = output.metadata || {};

  // For MCR/PCA, use sample_labels; for spectra use labels
  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw) ? labelsRaw.map((label: any) => normalizeSampleLabel(label)) : [];
  const limit = rowLimit.value;

  if (!Array.isArray(data)) return [];

  const rows: any[] = [];
  const maxRows = Math.min(data.length, limit);

  if (Array.isArray(data[0])) {
    // 2D data
    for (let i = 0; i < maxRows; i++) {
      const fullLabel = labels[i] || "";
      const row: any = {
        _index: i + 1,
        _label: compactSampleLabel(fullLabel),
        _label_full: fullLabel,
      };

      const maxCols = Math.min(data[i].length, 50);
      for (let j = 0; j < maxCols; j++) {
        row[`col_${j}`] = data[i][j];
      }

      if (data[i].length > 50) {
        row._truncated = "...";
      }

      rows.push(row);
    }
  } else {
    // 1D data
    for (let i = 0; i < maxRows; i++) {
      rows.push({
        _index: i + 1,
        value: data[i],
      });
    }
  }

  return rows;
});

// Metadata handling
const hasMetadata = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  if (!metadata) return false;
  return Object.keys(metadata).some(
    (key) => !["data", "wavenumbers", "x_axis", "labels"].includes(key)
  );
});

const displayMetadata = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  const filtered: Record<string, any> = {};

  // Keys to skip (large arrays and internal fields)
  const skipKeys = [
    "wavenumbers",
    "x_axis",
    "labels",
    "data",
    "loadings",         // PCA loadings matrix
    "St",               // MCR pure spectra
    "St_labels",        // MCR spectra labels
    "sample_labels",    // Sample labels array
    "pc_labels",        // When shown elsewhere
  ];

  for (const [key, value] of Object.entries(metadata)) {
    if (skipKeys.includes(key)) continue;
    if (Array.isArray(value) && value.length > 10) continue;
    filtered[key] = value;
  }

  return filtered;
});

function formatValue(value: any, isNumeric: boolean): string {
  if (value === null || value === undefined) return "-";
  if (isNumeric && typeof value === "number") {
    if (Number.isNaN(value)) return "NaN";
    if (!Number.isFinite(value)) return value > 0 ? "∞" : "-∞";
    return value.toFixed(precision.value);
  }
  return String(value);
}

function formatMetadataValue(value: any): string {
  if (Array.isArray(value)) {
    return `[${value.slice(0, 5).join(", ")}${value.length > 5 ? ", ..." : ""}]`;
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}

// Export functionality
function exportCSV() {
  const output = props.nodeOutput;
  if (!output?.data) return;

  const data = output.data;
  const metadata = output.metadata || {};
  const wavenumbers = metadata.wavenumbers || metadata.x_axis;
  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw) ? labelsRaw.map((label: any) => normalizeSampleLabel(label)) : [];

  const escapeCsv = (value: any): string => {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes("\"") || text.includes("\n")) {
      return `"${text.replace(/\"/g, "\"\"")}"`;
    }
    return text;
  };

  let csv = "";

  if (Array.isArray(data[0])) {
    // 2D data - build header row
    const headers = ["Index"];
    if (labels.length > 0) headers.push("Label");

    if (wavenumbers) {
      headers.push(...wavenumbers.map((w: number) => w.toFixed(2)));
    } else {
      headers.push(...data[0].map((_: any, i: number) => `Col_${i + 1}`));
    }
    csv += headers.map(escapeCsv).join(",") + "\n";

    // Data rows
    for (let i = 0; i < data.length; i++) {
      const row: any[] = [i + 1];
      if (labels.length > 0) row.push(labels[i] || "");
      row.push(...data[i]);
      csv += row.map(escapeCsv).join(",") + "\n";
    }
  } else {
    // 1D data
    csv += "Index,Value\n";
    for (let i = 0; i < data.length; i++) {
      csv += `${escapeCsv(i + 1)},${escapeCsv(data[i])}\n`;
    }
  }

  // Download
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${props.nodeLabel.replace(/\s+/g, "_")}_data.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}
</script>

<style scoped>
.data-table-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
}

.table-container {
  display: flex;
  flex-direction: column;
  height: 75vh;
  min-height: 500px;
}

.table-controls {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 12px 20px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}

.control-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-group label {
  font-size: 0.85rem;
  color: #94a3b8;
  white-space: nowrap;
}

.row-limit-dropdown {
  min-width: 120px;
}

.stats-summary {
  margin-left: auto;
  gap: 16px;
}

.stat-item {
  font-size: 0.85rem;
  color: #94a3b8;
}

.stat-item strong {
  color: #f8fafc;
}

.stat-item.warning {
  color: #fbbf24;
}

.table-wrapper {
  flex: 1;
  overflow: hidden;
  padding: 16px;
}

.data-table {
  font-size: 0.85rem;
}

.data-table :deep(.p-datatable-wrapper) {
  background: #0f172a;
}

.data-table :deep(.p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  padding: 10px 12px;
  font-weight: 600;
}

.data-table :deep(.p-datatable-tbody > tr) {
  background: #0f172a;
  color: #f8fafc;
}

.data-table :deep(.p-datatable-tbody > tr:nth-child(even)) {
  background: #1e293b;
}

.data-table :deep(.p-datatable-tbody > tr > td) {
  border-color: #334155;
  padding: 8px 12px;
}

.data-table :deep(.p-datatable-tbody > tr:hover) {
  background: #334155;
}

.numeric-cell {
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.8rem;
}

.label-cell {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.8rem;
}

.empty-table {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}

.empty-table i {
  font-size: 3rem;
  margin-bottom: 16px;
  color: #475569;
}

.empty-table p {
  font-size: 1.1rem;
  margin: 0 0 8px;
}

.empty-table small {
  font-size: 0.85rem;
  color: #475569;
}

.metadata-panel {
  padding: 16px 20px;
  background: #1e293b;
  border-top: 1px solid #334155;
}

.metadata-panel h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  font-weight: 600;
  color: #f8fafc;
}

.metadata-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.metadata-item {
  font-size: 0.85rem;
}

.metadata-key {
  color: #94a3b8;
  margin-right: 4px;
}

.metadata-value {
  color: #f8fafc;
  font-family: "JetBrains Mono", "Fira Code", monospace;
}

/* PrimeVue overrides for dark theme */
:deep(.p-dropdown) {
  background: #0f172a;
  border-color: #334155;
}

:deep(.p-dropdown:hover) {
  border-color: #475569;
}

:deep(.p-dialog) {
  background: #1e293b;
  border: 1px solid #334155;
}

:deep(.p-dialog-header) {
  background: #1e293b;
  color: #f8fafc;
  border-bottom: 1px solid #334155;
  padding: 16px 20px;
}

:deep(.p-dialog-header-icon) {
  color: #94a3b8;
}

:deep(.p-dialog-header-icon:hover) {
  background: #334155;
  color: #f8fafc;
}

/* Virtual scroller styling */
:deep(.p-virtualscroller) {
  background: #0f172a;
}
</style>
