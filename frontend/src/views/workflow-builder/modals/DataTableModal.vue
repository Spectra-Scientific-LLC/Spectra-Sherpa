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
        <div v-if="columnPageOptions.length > 1" class="control-group">
          <label>Columns</label>
          <Dropdown
            v-model="columnPage"
            :options="columnPageOptions"
            optionLabel="label"
            optionValue="value"
            aria-label="Column range"
          />
        </div>
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

        <div v-if="sampleFilterOptions.length > 1" class="control-group">
          <label>{{ sampleFilterLabel }}</label>
          <Dropdown
            v-model="selectedSampleFilter"
            :options="sampleFilterOptions"
            optionLabel="label"
            optionValue="value"
            class="sample-filter-dropdown"
          />
        </div>

        <div class="control-group search-group">
          <label>Search</label>
          <InputText v-model="searchQuery" placeholder="Filter visible rows" class="search-input" />
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
          <span v-if="previewTableData.length < dataShape.rows" class="stat-item warning">
            Showing first {{ previewTableData.length }} of {{ dataShape.rows }} rows; filters apply
            to this preview
          </span>
        </div>

        <Button
          icon="pi pi-download"
          label="Export all rows CSV"
          :disabled="!!tableProjectionError || dataShape.rows === 0"
          class="p-button-outlined p-button-sm"
          @click="exportCSV"
        />
      </div>

      <p class="export-scope" role="status">
        CSV carries cells and labels only; units, roles and run/model context remain in this view.
        CSV is a visual data extract of all {{ dataShape.rows }} rows and columns in this result,
        regardless of preview limits or search filters. It is not a dataset or model replay package;
        use Prepare Export for supported dataset roundtrips.
      </p>
      <p v-if="cohort.population" role="status">Active cohort: {{ cohort.population.total }} of {{ cohort.population.available }} retained rows; {{ cohort.population.excluded }} excluded. {{ cohort.population.shown_features }} of {{ cohort.population.available_features }} features; {{ cohort.population.excluded_features }} excluded. Table and CSV contain active rows/features; row numbers refer to retained source positions.</p>
      <p v-if="exportError" role="alert">{{ exportError }}</p>
      <p v-if="tableProjectionError" role="alert">{{ tableProjectionError }}</p>
      <!-- Data Table -->
      <div class="table-wrapper">
        <DataTable
          v-if="tableData.length > 0"
          :value="tableData"
          :scrollable="true"
          scrollHeight="360px"
          :paginator="tableData.length > 100"
          :rows="100"
          paginatorTemplate="FirstPageLink PrevPageLink CurrentPageReport NextPageLink LastPageLink"
          currentPageReportTemplate="{first}–{last} of {totalRecords} preview rows"
          class="data-table"
          size="small"
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
                :title="
                  col.field.startsWith('_label') ? data._label_full || data[col.field] || '' :
                    typeof data[col.field] === 'object' ? JSON.stringify(data[col.field]) : ''
                "
              >
                {{ formatValue(data[col.field], col.isNumeric) }}
              </span>
            </template>
          </Column>
        </DataTable>

        <div v-else class="empty-table">
          <i class="pi pi-table" />
          <p>{{ tableProjectionError || (hasActiveFilter ? "No rows match the current filter" : "No data to display") }}</p>
          <small v-if="!tableProjectionError">
            {{
              hasActiveFilter
                ? "Try a broader search or switch scope to All fields."
                : "Execute the node first to see results"
            }}
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
import { scientificNumber } from "@/utils/scientificEncoding";
import { projectActiveSpectralCohort } from "@/utils/scientificCohort";
/* eslint-disable @typescript-eslint/no-explicit-any -- table modal accepts generic node outputs and loose Plotly-shaped metadata. */
import { ref, computed, watch } from "vue";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import { isProjectedScientificKind } from "@/utils/scientificPresentation";
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
const cohort = computed(() => projectActiveSpectralCohort(props.nodeOutput));
const inspectedOutput = computed(() => cohort.value.output);
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
const columnPage = ref(0);
const columnPageOptions = computed(() => !Array.isArray(displayedData.value?.[0]) ? [] : Array.from(
  { length: Math.ceil(dataShape.value.cols / 50) },
  (_, page) => ({ label: `${page * 50 + 1}–${Math.min((page + 1) * 50, dataShape.value.cols)}`, value: page }),
));
const columnStart = computed(() => Math.min(Number(columnPage.value), Math.max(0, columnPageOptions.value.length - 1)) * 50);
const precision = ref(6);
const searchQuery = ref("");
const searchScope = ref<"all" | "label">("all");
const selectedSampleFilter = ref("__all__");

const rowLimitOptions = [
  { label: "50 rows", value: 50 },
  { label: "100 rows", value: 100 },
  { label: "500 rows", value: 500 },
  { label: "1000 rows", value: 1000 },
  { label: "All rows", value: 0 },
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

const isLibraryCompareOutput = computed(() => props.nodeType === "analysis.compare_library");
const sampleFilterLabel = computed(() => (isLibraryCompareOutput.value ? "Spectrum" : "Sample"));

// Check if data is Plotly visualization format (from CONTOUR_PLOT, PLOT nodes)
const isPlotlyFormat = computed(() => {
  const output = inspectedOutput.value;
  if (!output?.data) return false;

  const data = output.data;
  if (!Array.isArray(data)) return false;

  // Check if data contains Plotly trace objects
  return Boolean(data.length > 0 && typeof data[0] === "object" && data[0]?.type);
});

const plotlyRegressionComparisonRows = computed(() => {
  if (
    !isPlotlyFormat.value ||
    inspectedOutput.value?.metadata?.source_schema !== "spectrasherpa-regression-comparison/1"
  ) {
    return null;
  }

  const rows: Record<string, unknown>[] = [];
  for (const trace of inspectedOutput.value.data) {
    if (
      trace?.type !== "scatter" ||
      !String(trace.mode ?? "").includes("markers") ||
      !Array.isArray(trace.x) ||
      !Array.isArray(trace.y) ||
      trace.x.length !== trace.y.length
    ) {
      continue;
    }
    for (let index = 0; index < trace.x.length; index += 1) {
      const custom = Array.isArray(trace.customdata?.[index]) ? trace.customdata[index] : [];
      rows.push({
        sample: Array.isArray(trace.text)
          ? String(trace.text[index] ?? index + 1)
          : String(index + 1),
        target: String(trace.name ?? "Target"),
        reference: trace.x[index],
        predicted: trace.y[index],
        residual: custom[0] ?? null,
        role: custom[1] ?? inspectedOutput.value.metadata?.role ?? "",
      });
    }
  }
  return rows.length > 0 ? rows : null;
});

// This adapter projects declared visualization coordinates, not scientific sample roles.
// Every trace and point retains its positional identity, including duplicate names.
const traceProjection = computed(() => {
  const rows: Record<string, unknown>[] = [];
  if (!isPlotlyFormat.value || plotlyRegressionComparisonRows.value) return { rows, error: "" };
  for (const [traceIndex, trace] of inspectedOutput.value.data.entries()) {
    const identity = {
      trace_index: traceIndex + 1,
      trace: trace.name ?? `Trace ${traceIndex + 1}`,
    };
    if (["heatmap", "contour"].includes(trace.type) && Array.isArray(trace.z)) {
      if (
        !Array.isArray(trace.x) ||
        !Array.isArray(trace.y) ||
        trace.y.length !== trace.z.length ||
        trace.z.some((row: unknown) => !Array.isArray(row) || row.length !== trace.x.length)
      ) {
        return {
          rows: [],
          error: "Table unavailable: grid coordinates are missing or do not align with values.",
        };
      }
      trace.z.forEach((row: unknown[], rowIndex: number) =>
        row.forEach((z, columnIndex) => {
          rows.push({
            ...identity,
            row_index: rowIndex + 1,
            column_index: columnIndex + 1,
            x: trace.x[columnIndex],
            y: trace.y[rowIndex],
            z,
          });
        }),
      );
    } else if (
      ["scatter", "scattergl", "bar"].includes(trace.type) &&
      Array.isArray(trace.x) &&
      Array.isArray(trace.y) &&
      trace.x.length === trace.y.length
    ) {
      trace.x.forEach((x: unknown, index: number) =>
        rows.push({
          ...identity,
          point_index: index + 1,
          x,
          y: trace.y[index],
          ...(Array.isArray(trace.text) ? { label: trace.text[index] ?? null } : {}),
        }),
      );
    } else {
      return {
        rows: [],
        error: `Table unavailable: trace ${traceIndex + 1} has unsupported or mismatched coordinates.`,
      };
    }
  }
  return { rows, error: "" };
});
const tableProjectionError = computed(() => cohort.value.error || traceProjection.value.error);
const extractedData = computed(() =>
  isPlotlyFormat.value ? { data: traceProjection.value.rows, x: null, y: null } : null,
);

const structuredRecordRows = computed(() => {
  const value = inspectedOutput.value?.presentation_value;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;

  const record = value as Record<string, unknown>;
  if (
    Array.isArray(record.data) &&
    record.data.length > 0 &&
    record.data.every((row) => row && typeof row === "object" && !Array.isArray(row))
  ) {
    return record.data as Record<string, unknown>[];
  }
  if (
    Array.isArray(record.per_class) &&
    record.per_class.length > 0 &&
    record.per_class.every((row) => row && typeof row === "object" && !Array.isArray(row))
  ) {
    return record.per_class as Record<string, unknown>[];
  }

  const scalarRecord = Object.fromEntries(
    Object.entries(record).filter(([, candidate]) =>
      ["string", "number", "boolean"].includes(typeof candidate),
    ),
  );
  return Object.keys(scalarRecord).length > 0 ? [scalarRecord] : null;
});

const displayedData = computed(() => {
  if (cohort.value.error) return [];
  if (plotlyRegressionComparisonRows.value) return plotlyRegressionComparisonRows.value;
  if (isPlotlyFormat.value) return extractedData.value?.data ?? [];
  const direct = inspectedOutput.value?.data;
  if (Array.isArray(direct) && direct.length > 0) return direct;
  return structuredRecordRows.value ?? direct ?? [];
});

const isPlsExplainedVariance = computed(() =>
  isProjectedScientificKind(inspectedOutput.value, "pls_explained_variance"),
);
const isTargetMatrix = computed(() => isProjectedScientificKind(inspectedOutput.value, "target_matrix"));

// Compute data shape
/** True when ``data`` is a list of row dicts (e.g. HoldoutEvaluation
 * metrics: ``[{target: "Moisture", RMSEP: 0.1, R2: 0.9, ...}, ...]``).
 * In that case column headers are pulled from the dict keys (or from
 * ``metadata.column_names`` for an explicit order) and each row renders
 * one cell per key. */
const isRowDictFormat = computed(() => {
  const data = displayedData.value;
  return (
    Array.isArray(data) &&
    data.length > 0 &&
    typeof data[0] === "object" &&
    data[0] !== null &&
    !Array.isArray(data[0])
  );
});

const dataShape = computed(() => {
  const output = inspectedOutput.value;
  if (!output?.data) return { rows: 0, cols: 0 };

  const data = displayedData.value;
  if (!Array.isArray(data)) return { rows: 0, cols: 0 };

  const rows = data.length;

  if (isRowDictFormat.value) {
    // Column count = union of keys across all rows, or explicit column_names from metadata.
    const metadata = output.metadata || {};
    const explicitCols = !isPlotlyFormat.value && Array.isArray(metadata.column_names) ? metadata.column_names.length : 0;
    if (explicitCols > 0) return { rows, cols: explicitCols };
    const keys = new Set<string>();
    for (const row of data) {
      if (row && typeof row === "object" && !Array.isArray(row)) {
        for (const key of Object.keys(row)) keys.add(key);
      }
    }
    return { rows, cols: keys.size };
  }

  const cols = Array.isArray(data[0]) ? data[0].length : 1;

  return { rows, cols };
});

function getLabelInfo(metadata: Record<string, any>) {
  const labelsRaw =
    metadata.sample_labels || metadata.labels || metadata.diagnostics?.sample_labels || [];
  const labels = Array.isArray(labelsRaw)
    ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
    : [];
  const delimiter = detectLabelDelimiter(labels);
  const splitLabels = delimiter
    ? labels.map((label: string) => splitLabelByDelimiter(label, delimiter))
    : [];
  const maxParts =
    splitLabels.length > 0 ? Math.max(...splitLabels.map((parts: string[]) => parts.length)) : 0;

  return {
    labels,
    delimiter,
    splitLabels,
    maxParts,
    useSplitColumns: !!delimiter && maxParts > 1,
  };
}

function exactStringLabels(value: unknown, expectedLength: number): string[] {
  if (!Array.isArray(value) || value.length !== expectedLength) return [];
  const labels = value.map((item) => normalizeSampleLabel(item));
  return labels.every((label) => label.length > 0) ? labels : [];
}

function relatedFeatureLabels(output: any, expectedLength: number): string[] {
  const loadings = output?.ports?.loadings ?? output?.ports?.x_loadings;
  const payload = loadings?.value ?? loadings ?? {};
  const axis = payload.x_axis ?? payload.feature_axis ?? {};
  const candidates = [
    output?.metadata?.feature_names,
    output?.presentation_value?.x_axis?.labels,
    axis.labels,
    axis.data,
    loadings?.metadata?.feature_names,
    payload?.metadata?.feature_names,
  ];
  for (const candidate of candidates) {
    const labels = exactStringLabels(candidate, expectedLength);
    if (labels.length > 0) return labels;
  }
  return [];
}

function semanticLabelInfo(output: any, data: any[]) {
  const metadata = output?.metadata ?? {};
  const dimensions = output?.descriptor?.dimensions ?? [];
  const rowRole = String(dimensions[0]?.role ?? "").toLowerCase();
  const variableRows = ["feature", "spectral_variable", "variable"].includes(rowRole);
  const labels = variableRows ? relatedFeatureLabels(output, data.length) : [];
  if (labels.length === 0) return getLabelInfo(metadata);
  return getLabelInfo({ sample_labels: labels });
}

// One column-authority resolver serves the table and its CSV; formatting is separate.
const matrixColumnLabels = computed(() => {
  const output = inspectedOutput.value;
  const data = displayedData.value;
  const width = Array.isArray(data?.[0]) ? data[0].length : 1;
  const metadata = output?.metadata ?? {};
  const dimensions = output?.descriptor?.dimensions ?? [];
  const column = dimensions[dimensions.length - 1] ?? {};
  const response =
    isTargetMatrix.value ||
    ["target", "class", "response_class", "actual_predicted_value"].includes(column.role);
  const axis = output?.presentation_value?.feature_axis ?? output?.presentation_value?.x_axis;
  const responseNames = [
    column.labels,
    metadata.target_names,
    metadata.classes,
    metadata.label_categories,
    metadata.diagnostics?.target_names,
    metadata.diagnostics?.classes,
    metadata.diagnostics?.label_categories,
    metadata.column_names,
  ];
  const featureNames = [column.labels, metadata.feature_names, metadata.column_names, axis?.labels];
  const coords = [
    metadata.wavenumbers,
    Array.isArray(metadata.x_axis) ? metadata.x_axis : metadata.x_axis?.data,
    axis?.data,
  ];
  const candidates = response
    ? responseNames
    : metadata.data_role === "X_features"
      ? featureNames
      : [...featureNames, ...coords];
  const declared = candidates.find((value) => Array.isArray(value) && value.length === width);
  if (declared) return declared.map(String);
  if (isPlsExplainedVariance.value)
    return Array.from({ length: width }, (_, i) =>
      i === 0 ? "X variance" : i === 1 ? "Y variance" : `Domain ${i + 1}`,
    );
  return Array.from({ length: width }, (_, i) => (width === 1 ? "Value" : `Col_${i + 1}`));
});

// Build table columns
const tableColumns = computed(() => {
  const output = inspectedOutput.value;
  if (!output?.data) return [];

  // Use the exact plotted points rather than Plotly trace containers.
  const data = displayedData.value;
  const metadata = output.metadata || {};
  const descriptorDimensions = output.descriptor?.dimensions ?? [];
  // Check for decomposition output types (MCR, PCA)
  const isMCR = metadata.type === "MCR_ALS";
  const isPCA = metadata.type === "PCA" || metadata.isPCA;
  const pcLabels = metadata.pc_labels || [];
  const mcrLabels = metadata.labels || [];
  const labelInfo = isPlsExplainedVariance.value
    ? {
        labels: data.map((_: unknown, index: number) => `LV ${index + 1}`),
        delimiter: null,
        splitLabels: [],
        maxParts: 0,
        useSplitColumns: false,
      }
    : semanticLabelInfo(output, data);
  const descriptorRowRole = String(descriptorDimensions[0]?.role ?? "").toLowerCase();
  const variableRows = ["feature", "spectral_variable", "variable"].includes(
    descriptorRowRole,
  );

  // Row-dict format (metrics payloads): one field per dict key, ordered
  // by metadata.column_names if present, else by first-seen order across rows.
  if (isRowDictFormat.value) {
    const columns: any[] = [{ field: "_index", header: "#", width: "60px", isNumeric: true }];

    let orderedKeys: string[] = [];
    if (!isPlotlyFormat.value && Array.isArray(metadata.column_names) && metadata.column_names.length > 0) {
      orderedKeys = metadata.column_names.map((k: any) => String(k));
    } else {
      const seen = new Set<string>();
      for (const row of data) {
        if (row && typeof row === "object" && !Array.isArray(row)) {
          for (const key of Object.keys(row)) {
            if (!seen.has(key)) {
              seen.add(key);
              orderedKeys.push(key);
            }
          }
        }
      }
    }

    for (const key of orderedKeys) {
      // Guess numeric vs string by inspecting the first few rows.
      let isNumeric = false;
      for (let i = 0; i < Math.min(data.length, 5); i += 1) {
        const row = data[i];
        if (row && typeof row === "object" && typeof row[key] === "number") {
          isNumeric = true;
          break;
        }
      }
      columns.push({
        field: key,
        header: key,
        width: isNumeric ? "120px" : "160px",
        isNumeric,
      });
    }
    return columns;
  }

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
        const labelHeader = isPlsExplainedVariance.value
          ? "Latent Variable"
          : variableRows
            ? "Variable"
          : metadata.sample_labels?.length > 0
            ? "Sample"
            : !isMCR && !isPCA
              ? "Label"
              : "Sample";
        columns.push({
          field: "_label",
          header: labelHeader,
          width: "280px",
          isNumeric: false,
        });
      }
    }

    // Page columns without discarding appended engineered features.
    const maxCols = Math.min(cols, columnStart.value + 50);
    for (let i = columnStart.value; i < maxCols; i++) {
      let header: string;
      if (isPlsExplainedVariance.value) {
        header = i === 0 ? "X variance" : i === 1 ? "Y variance" : `Domain ${i + 1}`;
      } else if (isPCA) {
        // PCA: use PC labels like "PC1 (45.2%)"
        header = pcLabels[i] || `PC${i + 1}`;
      } else if (isMCR) {
        // MCR: use component labels
        header = mcrLabels[i] || `Component ${i + 1}`;
      } else {
        header = matrixColumnLabels.value[i];
      }
      columns.push({
        field: `col_${i}`,
        header,
        width: isPCA || isMCR ? "140px" : "100px",
        isNumeric: true,
      });
    }

    return columns;
  } else {
    // 1D data
    const columns: any[] = [{ field: "_index", header: "#", width: "60px", isNumeric: true }];
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
  const output = inspectedOutput.value;
  if (!output?.data) return [];

  const data = displayedData.value;
  const labelInfo = isPlsExplainedVariance.value
    ? {
        labels: data.map((_: unknown, index: number) => `LV ${index + 1}`),
        delimiter: null,
        splitLabels: [],
        maxParts: 0,
        useSplitColumns: false,
      }
    : semanticLabelInfo(output, data);
  const limit = rowLimit.value === 0 ? data.length : rowLimit.value;

  if (!Array.isArray(data)) return [];

  const rows: any[] = [];
  const maxRows = Math.min(data.length, limit);

  // Row-dict format (metrics payloads): spread each dict's keys onto
  // the row object directly, keyed by the column field name that
  // ``tableColumns`` emits.  ``_label_full`` stays empty — there's no
  // sample label concept for per-target metrics tables.
  if (isRowDictFormat.value) {
    for (let i = 0; i < maxRows; i += 1) {
      const src = data[i];
      if (!src || typeof src !== "object" || Array.isArray(src)) continue;
      const row: any = { _index: i + 1, _label_full: "" };
      for (const [key, value] of Object.entries(src)) {
        row[key] = value;
      }
      rows.push(row);
    }
    return rows;
  }

  if (Array.isArray(data[0])) {
    // 2D data
    for (let i = 0; i < maxRows; i++) {
      const fullLabel = labelInfo.labels[i] || "";
      const row: any = { _index: (cohort.value.population?.source_row_indices?.[i] ?? i) + 1, _label_full: fullLabel };
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

      const maxCols = Math.min(data[i].length, columnStart.value + 50);
      for (let j = columnStart.value; j < maxCols; j++) {
        row[`col_${j}`] = data[i][j];
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

const sampleFilterOptions = computed(() => {
  if (!isRowDictFormat.value) return [];
  const seen = new Set<string>();
  const options = isLibraryCompareOutput.value ? [] : [{ label: "All samples", value: "__all__" }];
  for (const row of previewTableData.value) {
    const sample = row?.sample;
    if (sample === null || sample === undefined || sample === "") continue;
    const label = String(sample);
    if (seen.has(label)) continue;
    seen.add(label);
    options.push({ label, value: label });
  }
  return options;
});

watch(
  sampleFilterOptions,
  (options) => {
    if (!options.some((option) => option.value === selectedSampleFilter.value)) {
      selectedSampleFilter.value =
        isLibraryCompareOutput.value && options.length > 0 ? options[0].value : "__all__";
    }
  },
  { immediate: true },
);

const hasActiveFilter = computed(
  () => searchQuery.value.trim().length > 0 || selectedSampleFilter.value !== "__all__",
);

const filteredTableRows = computed(() => {
  const sampleFiltered =
    selectedSampleFilter.value === "__all__"
      ? previewTableData.value
      : previewTableData.value.filter(
          (row: Record<string, any>) => String(row.sample ?? "") === selectedSampleFilter.value,
        );

  if (!hasActiveFilter.value) return sampleFiltered;

  const tokens = searchQuery.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return sampleFiltered;

  return sampleFiltered.filter((row: Record<string, any>) => {
    const fields =
      searchScope.value === "label" ? [row._label_full ?? row._label ?? ""] : Object.values(row);
    const haystack = fields.map((value) => String(value ?? "").toLowerCase()).join(" ");
    return tokens.every((token) => haystack.includes(token));
  });
});

const tableData = computed(() => filteredTableRows.value);

const filteredRowCount = computed(() => filteredTableRows.value.length);

// Metadata handling
const hasMetadata = computed(() => {
  const metadata = inspectedOutput.value?.metadata;
  if (!metadata) return false;
  return Object.keys(metadata).some(
    (key) => !["data", "wavenumbers", "x_axis", "labels"].includes(key),
  );
});

const displayMetadata = computed(() => {
  const metadata = inspectedOutput.value?.metadata || {};
  const filtered: Record<string, any> = {};

  // Keys to skip (large arrays and internal fields)
  const skipKeys = [
    "wavenumbers",
    "x_axis",
    "labels",
    "data",
    "loadings", // PCA loadings matrix
    "St", // MCR pure spectra
    "St_labels", // MCR spectra labels
    "sample_labels", // Sample labels array
    "pc_labels", // When shown elsewhere
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
  if (typeof value === "object") {
    if (Array.isArray(value) && value.some(item => item !== null && typeof item === "object")) {
      return `${value.length} records (hover for details)`;
    }
    const text = JSON.stringify(value);
    return text.length > 100 ? `${text.slice(0, 100)}…` : text;
  }
  if (isNumeric && typeof value === "number") {
    if (Number.isNaN(value)) return "NaN";
    if (!Number.isFinite(value)) return value > 0 ? "∞" : "-∞";
    const fixed = value.toFixed(precision.value);
    return value !== 0 && Number(fixed) === 0 ? scientificNumber(value) : fixed;
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

// Export identity is independent of lossy display normalization.
const exportError = ref("");
watch(
  () => inspectedOutput.value,
  () => {
    exportError.value = "";
    columnPage.value = 0;
  },
);
function exportRowLabels(output: any, count: number): unknown[] {
  const meta = output?.metadata ?? {};
  const row = output?.descriptor?.dimensions?.[0];
  const variableRows = ["feature", "spectral_variable", "variable"].includes(row?.role);
  const loading = output?.ports?.loadings ?? output?.ports?.x_loadings;
  const payload = loading?.value ?? loading;
  const candidates = variableRows
    ? [
        row?.labels,
        meta.feature_names,
        output?.presentation_value?.x_axis?.labels,
        payload?.x_axis?.labels,
        payload?.feature_axis?.labels,
        payload?.x_axis?.data,
        payload?.feature_axis?.data,
        loading?.metadata?.feature_names,
        payload?.metadata?.feature_names,
      ]
    : [
        row?.labels,
        output?.presentation_value?.sample_axis?.labels,
        output?.presentation_value?.y_axis?.labels,
        meta.sample_labels,
        meta.labels,
        meta.diagnostics?.sample_labels,
      ];
  const labels = candidates.find((value) => value != null);
  if (labels == null) return [];
  if (
    !Array.isArray(labels) ||
    labels.length !== count ||
    labels.some(
      (value) =>
        typeof value !== "string" && !(typeof value === "number" && Number.isFinite(value)),
    )
  ) {
    throw new Error(
      "CSV unavailable: declared row labels must be scalar strings or finite numbers and match every result row.",
    );
  }
  return labels;
}

// CSV deliberately exports a visual extract, not a lossless scientific replay package.
function exportCSV() {
  const output = inspectedOutput.value;
  const data = displayedData.value;
  if (!Array.isArray(data) || !data.length || tableProjectionError.value) return;
  exportError.value = "";
  const escapeCsv = (value: unknown): string => {
    const text = value !== null && typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
    return /[,"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  let headers: unknown[];
  let rows: unknown[][];
  if (isRowDictFormat.value) {
    // Never let stale metadata hide actual trace/record fields.
    const keys = [
      ...new Set<string>(data.flatMap((row: Record<string, unknown>) => Object.keys(row))),
    ];
    headers = ["Index", ...keys];
    rows = data.map((row: Record<string, unknown>, i: number) => [
      (cohort.value.population?.source_row_indices?.[i] ?? i) + 1,
      ...keys.map((key) => row[key]),
    ]);
  } else {
    const width = Array.isArray(data[0]) ? data[0].length : 1;
    const names = matrixColumnLabels.value;
    let labels: unknown[];
    try {
      labels = isPlsExplainedVariance.value
        ? data.map((_: unknown, i: number) => `LV ${i + 1}`)
        : exportRowLabels(output, data.length);
    } catch (error) {
      exportError.value = (error as Error).message;
      return;
    }
    headers = [
      "Index",
      ...(labels.length ? ["Label"] : []),
      ...(names ??
        Array.from({ length: width }, (_, i) => (width === 1 ? "Value" : `Col_${i + 1}`))),
    ];
    rows = data.map((row: unknown, i: number) => [
      (cohort.value.population?.source_row_indices?.[i] ?? i) + 1,
      ...(labels.length ? [labels[i] ?? ""] : []),
      ...(Array.isArray(row) ? row : [row]),
    ]);
  }
  const csv = [headers, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n") + "\n";
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${props.nodeLabel.replace(/\s+/g, "_")}_view.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}
</script>

<style scoped>
.data-table-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
  max-height: calc(100vh - 120px);
  overflow: hidden;
}

.table-container {
  display: flex;
  flex-direction: column;
  height: min(75vh, calc(100vh - 120px));
  min-height: 500px;
  overflow: auto;
}

.table-controls {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
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

.sample-filter-dropdown {
  min-width: 180px;
  max-width: 280px;
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
  flex: 0 0 auto;
  min-height: 360px;
  overflow: hidden;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.data-table {
  flex: 1;
  min-height: 0;
  font-size: 0.8rem;
}

.data-table :deep(.p-datatable-wrapper) {
  background: #0f172a;
  min-height: 0;
}

.data-table :deep(.p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  padding: 6px 10px;
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
  padding: 5px 10px;
  line-height: 1.25;
}

.data-table :deep(.p-datatable-tbody > tr:hover) {
  background: #334155;
}

.numeric-cell {
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.76rem;
}

.label-cell {
  display: inline-block;
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.76rem;
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
  flex: 0 0 auto;
  max-height: 22vh;
  overflow: auto;
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
