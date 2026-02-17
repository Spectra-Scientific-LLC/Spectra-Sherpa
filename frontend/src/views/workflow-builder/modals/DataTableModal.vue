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

        <div class="control-group search-group">
          <label>Search</label>
          <InputText
            v-model="searchQuery"
            placeholder="Filter visible rows"
            class="search-input"
          />
        </div>

        <div class="control-group">
          <label>Scope</label>
          <Dropdown
            v-model="searchScope"
            :options="searchScopeOptions"
            optionLabel="label"
            optionValue="value"
            class="filter-dropdown"
          />
        </div>

        <div class="control-group stats-summary">
          <span class="stat-item">
            <strong>{{ dataShape.rows }}</strong> rows
          </span>
          <span class="stat-item">
            <strong>{{ dataShape.cols }}</strong> columns
          </span>
          <span v-if="hasActiveFilter" class="stat-item">
            <strong>{{ filteredRowCount }}</strong> matched
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
                  'label-cell': col.field.startsWith('_label'),
                }"
                :title="col.field.startsWith('_label') ? (data._label_full || data[col.field] || '') : ''"
              >
                {{ formatValue(data[col.field], col.isNumeric) }}
              </span>
            </template>
          </Column>
        </DataTable>

        <div v-else class="empty-table">
          <i class="pi pi-table" />
          <p>{{ hasActiveFilter ? "No rows match the current filter" : "No data to display" }}</p>
          <small>
            {{ hasActiveFilter ? "Try a broader search or switch scope to All fields." : "Execute the node first to see results" }}
          </small>
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
import { ref, computed } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import {
  compactSampleLabel,
  detectLabelDelimiter,
  normalizeSampleLabel,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";

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

const title = computed(() => `${props.nodeLabel} - Data View`);

// Display options
const rowLimit = ref(100);
const precision = ref(6);
const searchQuery = ref("");
const searchScope = ref<"all" | "label">("all");

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

const searchScopeOptions = [
  { label: "All fields", value: "all" },
  { label: "Labels only", value: "label" },
];

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

function getLabelInfo(metadata: Record<string, any>) {
  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw)
    ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
    : [];
  const delimiter = detectLabelDelimiter(labels);
  const splitLabels = delimiter
    ? labels.map((label: string) => splitLabelByDelimiter(label, delimiter))
    : [];
  const maxParts = splitLabels.length > 0
    ? Math.max(...splitLabels.map((parts: string[]) => parts.length))
    : 0;

  return {
    labels,
    delimiter,
    splitLabels,
    maxParts,
    useSplitColumns: !!delimiter && maxParts > 1,
  };
}

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
  const labelInfo = getLabelInfo(metadata);

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

    // Add label columns if available
    if (labelInfo.labels.length > 0) {
      if (labelInfo.useSplitColumns) {
        for (let i = 0; i < labelInfo.maxParts; i += 1) {
          columns.push({
            field: `_label_${i}`,
            header: `Field ${i + 1}`,
            width: "220px",
            isNumeric: false,
          });
        }
      } else {
        const labelHeader = metadata.sample_labels?.length > 0
          ? "Sample"
          : (!isMCR && !isPCA ? "Label" : "Sample");
        columns.push({
          field: "_label",
          header: labelHeader,
          width: "280px",
          isNumeric: false,
        });
      }
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
    const columns: any[] = [
      { field: "_index", header: "#", width: "60px", isNumeric: true },
    ];
    if (labelInfo.labels.length > 0) {
      if (labelInfo.useSplitColumns) {
        for (let i = 0; i < labelInfo.maxParts; i += 1) {
          columns.push({
            field: `_label_${i}`,
            header: `Field ${i + 1}`,
            width: "220px",
            isNumeric: false,
          });
        }
      } else {
        columns.push({
          field: "_label",
          header: "Label",
          width: "280px",
          isNumeric: false,
        });
      }
    }
    columns.push({ field: "value", header: "Value", width: "150px", isNumeric: true });
    return columns;
  }
});

// Build table data
const previewTableData = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return [];

  // Use extracted data for Plotly format
  const sourceData = isPlotlyFormat.value ? extractedData.value : null;
  const data = sourceData?.data || output.data;
  const metadata = output.metadata || {};
  const labelInfo = getLabelInfo(metadata);
  const limit = rowLimit.value;

  if (!Array.isArray(data)) return [];

  const rows: any[] = [];
  const maxRows = Math.min(data.length, limit);

  if (Array.isArray(data[0])) {
    // 2D data
    for (let i = 0; i < maxRows; i++) {
      const fullLabel = labelInfo.labels[i] || "";
      const row: any = { _index: i + 1, _label_full: fullLabel };
      if (labelInfo.labels.length > 0) {
        if (labelInfo.useSplitColumns) {
          const parts = labelInfo.splitLabels[i] || [];
          for (let labelIdx = 0; labelIdx < labelInfo.maxParts; labelIdx += 1) {
            row[`_label_${labelIdx}`] = compactSampleLabel(parts[labelIdx] || "", {
              maxLength: 56,
              headLength: 36,
              tailLength: 16,
            });
          }
        } else {
          row._label = compactSampleLabel(fullLabel, {
            maxLength: 64,
            headLength: 40,
            tailLength: 18,
          });
        }
      }

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
      const row: any = {
        _index: i + 1,
        value: data[i],
        _label_full: labelInfo.labels[i] || "",
      };
      if (labelInfo.labels.length > 0) {
        if (labelInfo.useSplitColumns) {
          const parts = labelInfo.splitLabels[i] || [];
          for (let labelIdx = 0; labelIdx < labelInfo.maxParts; labelIdx += 1) {
            row[`_label_${labelIdx}`] = compactSampleLabel(parts[labelIdx] || "", {
              maxLength: 56,
              headLength: 36,
              tailLength: 16,
            });
          }
        } else {
          row._label = compactSampleLabel(labelInfo.labels[i] || "", {
            maxLength: 64,
            headLength: 40,
            tailLength: 18,
          });
        }
      }
      rows.push(row);
    }
  }

  return rows;
});

const hasActiveFilter = computed(() => searchQuery.value.trim().length > 0);

const tableData = computed(() => {
  if (!hasActiveFilter.value) return previewTableData.value;

  const tokens = searchQuery.value
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (tokens.length === 0) return previewTableData.value;

  return previewTableData.value.filter((row: Record<string, any>) => {
    const fields = searchScope.value === "label"
      ? [row._label_full ?? row._label ?? ""]
      : Object.values(row);
    const haystack = fields.map((value) => String(value ?? "").toLowerCase()).join(" ");
    return tokens.every((token) => haystack.includes(token));
  });
});

const filteredRowCount = computed(() => tableData.value.length);

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
  const labelInfo = getLabelInfo(metadata);

  const escapeCsv = (value: any): string => {
    const text = String(value ?? "");
    if (text.includes(",") || text.includes('"') || text.includes("\n")) {
      return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  };

  let csv = "";

  if (Array.isArray(data[0])) {
    // 2D data - build header row
    const headers = ["Index"];
    if (labelInfo.labels.length > 0) {
      if (labelInfo.useSplitColumns) {
        headers.push(...Array.from({ length: labelInfo.maxParts }, (_, idx) => `Field ${idx + 1}`));
      } else {
        headers.push("Label");
      }
    }

    if (wavenumbers) {
      headers.push(...wavenumbers.map((w: number) => w.toFixed(2)));
    } else {
      headers.push(...data[0].map((_: any, i: number) => `Col_${i + 1}`));
    }
    csv += headers.map(escapeCsv).join(",") + "\n";

    // Data rows
    for (let i = 0; i < data.length; i++) {
      const row: any[] = [i + 1];
      if (labelInfo.labels.length > 0) {
        if (labelInfo.useSplitColumns) {
          const parts = labelInfo.splitLabels[i] || [];
          for (let labelIdx = 0; labelIdx < labelInfo.maxParts; labelIdx += 1) {
            row.push(parts[labelIdx] || "");
          }
        } else {
          row.push(labelInfo.labels[i] || "");
        }
      }
      row.push(...data[i]);
      csv += row.map(escapeCsv).join(",") + "\n";
    }
  } else {
    // 1D data
    const headers = ["Index"];
    if (labelInfo.labels.length > 0) {
      if (labelInfo.useSplitColumns) {
        headers.push(...Array.from({ length: labelInfo.maxParts }, (_, idx) => `Field ${idx + 1}`));
      } else {
        headers.push("Label");
      }
    }
    headers.push("Value");
    csv += headers.map(escapeCsv).join(",") + "\n";
    for (let i = 0; i < data.length; i++) {
      const row: any[] = [i + 1];
      if (labelInfo.labels.length > 0) {
        if (labelInfo.useSplitColumns) {
          const parts = labelInfo.splitLabels[i] || [];
          for (let labelIdx = 0; labelIdx < labelInfo.maxParts; labelIdx += 1) {
            row.push(parts[labelIdx] || "");
          }
        } else {
          row.push(labelInfo.labels[i] || "");
        }
      }
      row.push(data[i]);
      csv += row.map(escapeCsv).join(",") + "\n";
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

.search-group {
  min-width: 260px;
}

.search-input {
  min-width: 220px;
}

.filter-dropdown {
  min-width: 140px;
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

@media (max-width: 1200px) {
  .table-controls {
    flex-wrap: wrap;
    gap: 12px 16px;
  }

  .stats-summary {
    width: 100%;
    margin-left: 0;
    justify-content: flex-start;
  }
}
</style>
