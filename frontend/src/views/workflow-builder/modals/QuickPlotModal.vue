<template>
  <Dialog
    v-model:visible="visible"
    :header="title"
    :style="{ width: '85vw', maxWidth: '1200px' }"
    modal
    :draggable="false"
    class="quick-plot-modal"
  >
    <div class="plot-container">
      <!-- Plot type selector -->
      <div class="plot-controls">
        <!-- PCA specific controls -->
        <div v-if="isPCAOutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="pcaDisplayMode"
            :options="pcaDisplayOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <!-- MCR-ALS specific controls -->
        <div v-else-if="isMCROutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="mcrDisplayMode"
            :options="mcrDisplayOptions"
            optionLabel="label"
            optionValue="value"
            class="mcr-mode-dropdown"
          />
        </div>

        <!-- PLS specific controls -->
        <div v-else-if="isPLSOutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="plsDisplayMode"
            :options="plsDisplayOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <!-- PLS-DA specific controls -->
        <div v-else-if="isPLSDAOutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="plsdaDisplayMode"
            :options="plsdaDisplayOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <!-- HCA specific controls -->
        <div v-else-if="isHCAOutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="hcaDisplayMode"
            :options="hcaDisplayOptions"
            optionLabel="label"
            optionValue="value"
            :disabled="true"
          />
        </div>

        <!-- Generic dataset controls (Load Data with non-spectral data like Iris) -->
        <div v-else-if="isGenericDatasetOutput" class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="genericDisplayMode"
            :options="genericDisplayOptions"
            optionLabel="label"
            optionValue="value"
            class="generic-mode-dropdown"
          />
        </div>

        <!-- Generic plot type for other nodes -->
        <div v-else class="control-group">
          <label>Plot Type</label>
          <Dropdown
            v-model="plotType"
            :options="plotTypeOptions"
            optionLabel="label"
            optionValue="value"
            class="plot-type-dropdown"
          />
        </div>

        <div v-if="plotType === 'line' && !isMCROutput && !isPCAOutput && !isHCAOutput && !isGenericDatasetOutput" class="control-group">
          <label>Display</label>
          <Dropdown
            v-model="lineDisplayMode"
            :options="lineDisplayOptions"
            optionLabel="label"
            optionValue="value"
          />
        </div>

        <!-- PCA axis selectors (only for scores plot) -->
        <div v-if="isPCAOutput && pcaDisplayMode === 'scores'" class="control-group">
          <label>X Axis</label>
          <Dropdown
            v-model="pcaXAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>
        <div v-if="isPCAOutput && pcaDisplayMode === 'scores'" class="control-group">
          <label>Y Axis</label>
          <Dropdown
            v-model="pcaYAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>

        <!-- PLS axis selectors (only for scores plot) -->
        <div v-if="isPLSOutput && plsDisplayMode === 'scores'" class="control-group">
          <label>X Axis</label>
          <Dropdown
            v-model="pcaXAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>
        <div v-if="isPLSOutput && plsDisplayMode === 'scores'" class="control-group">
          <label>Y Axis</label>
          <Dropdown
            v-model="pcaYAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>

        <!-- Classification axis selectors -->
        <div v-if="isClassificationOutput" class="control-group">
          <label>X Axis</label>
          <Dropdown
            v-model="pcaXAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>
        <div v-if="isClassificationOutput" class="control-group">
          <label>Y Axis</label>
          <Dropdown
            v-model="pcaYAxis"
            :options="pcaAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="pca-axis-dropdown"
          />
        </div>

        <!-- Generic dataset feature axis selectors (for scatter plot mode) -->
        <div v-if="isGenericDatasetOutput && genericDisplayMode === 'scatter_features'" class="control-group">
          <label>X Feature</label>
          <Dropdown
            v-model="featureXAxis"
            :options="featureAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="feature-axis-dropdown"
          />
        </div>
        <div v-if="isGenericDatasetOutput && genericDisplayMode === 'scatter_features'" class="control-group">
          <label>Y Feature</label>
          <Dropdown
            v-model="featureYAxis"
            :options="featureAxisOptions"
            optionLabel="label"
            optionValue="value"
            class="feature-axis-dropdown"
          />
        </div>

        <div class="control-group stats-summary">
          <span class="stat-item">
            <strong>{{ dataShape.rows }}</strong> {{ dataShape.rowLabel }}
          </span>
          <span class="stat-item">
            <strong>{{ dataShape.cols }}</strong> {{ dataShape.colLabel }}
          </span>
          <span v-if="dataShape.range" class="stat-item">
            Range: <strong>{{ dataShape.range[0].toFixed(2) }}</strong> - <strong>{{ dataShape.range[1].toFixed(2) }}</strong>
          </span>
        </div>

        <!-- View toggle: Plot vs Data Table -->
        <div class="control-group view-toggle">
          <Button
            :icon="viewMode === 'plot' ? 'pi pi-chart-line' : 'pi pi-table'"
            :label="viewMode === 'plot' ? 'Plot' : 'Data'"
            :class="['p-button-outlined', 'p-button-sm', viewMode === 'plot' ? 'p-button-primary' : 'p-button-secondary']"
            @click="toggleViewMode"
            :title="viewMode === 'plot' ? 'Switch to Data Table' : 'Switch to Plot'"
          />
        </div>

        <Button
          v-if="viewMode === 'plot'"
          icon="pi pi-download"
          label="Download"
          class="p-button-outlined p-button-sm"
          @click="downloadPlot"
        />
      </div>

      <!-- Plotly chart (when viewMode === 'plot') -->
      <div v-if="viewMode === 'plot'" ref="plotContainer" class="plotly-container">
        <PlotlyChart
          v-if="plotData.length > 0"
          :data="plotData"
          :layout="plotLayout"
          :config="plotConfig"
        />
        <div v-else class="empty-plot">
          <i class="pi pi-chart-line" />
          <p>No data to display</p>
          <small>Execute the node first to see results</small>
        </div>
      </div>

      <!-- Data Table (when viewMode === 'data') -->
      <div v-else class="data-table-container">
        <DataTable
          v-if="dataPreview.length > 0"
          :value="dataPreview"
          :scrollable="true"
          scrollHeight="calc(70vh - 120px)"
          class="preview-datatable"
          size="small"
          stripedRows
        >
          <Column
            v-for="col in dataPreviewColumns"
            :key="col.field"
            :field="col.field"
            :header="col.header"
            :style="{ minWidth: '80px', maxWidth: '150px' }"
          />
        </DataTable>
        <div v-else class="empty-plot">
          <i class="pi pi-table" />
          <p>No data to display</p>
          <small>Execute the node first to see results</small>
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
import PlotlyChart from "@/components/PlotlyChart.vue";
import { createCategoryColorMap } from "@/utils/colors";
import { getYAxisLabel, getXAxisLabel, isSpectralData } from "@/utils/plotLabels";

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

const title = computed(() => `${props.nodeLabel} - Output Visualization`);

// View mode: plot or data table (DRY with NodeDetailView)
const viewMode = ref<"plot" | "data">("plot");
const previewRowLimit = 100; // Same as NodeDetailView

function toggleViewMode() {
  viewMode.value = viewMode.value === "plot" ? "data" : "plot";
}

// Plot configuration
const plotType = ref<"line" | "heatmap" | "scatter">("line");
const lineDisplayMode = ref<"overlay" | "stacked">("overlay");

const plotTypeOptions = [
  { label: "Line Plot", value: "line" },
  { label: "Heatmap (2D)", value: "heatmap" },
  { label: "Scatter", value: "scatter" },
];

const lineDisplayOptions = [
  { label: "Overlay", value: "overlay" },
  { label: "Stacked", value: "stacked" },
];

// Check if this is MCR-ALS or similar decomposition output
const isMCROutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "MCR_ALS" || metadata?.type === "SIMPLISMA" ||
         metadata?.type === "NMF" || metadata?.type === "FastICA";
});

// Check if this is PCA output
const isPCAOutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "PCA" || metadata?.isPCA === true;
});

// Check if this is PLS output (regression with scores)
const isPLSOutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "PLS";
});

// Check if this is classification output (PLS-DA, SIMCA, KNN)
const isClassificationOutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "PLS_DA" || metadata?.type === "SIMCA" || metadata?.type === "KNN";
});

// Check if this is PLS-DA output specifically (has plots field)
const isPLSDAOutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "PLS_DA";
});

// Check if this is HCA output (dendrogram plots)
const isHCAOutput = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type === "HCA";
});

// Check if this is generic dataset output (Load Data with non-spectral data like Iris)
const isGenericDatasetOutput = computed(() => {
  const output = props.nodeOutput;
  if (!output) return false;
  const metadata = output.metadata || {};

  // Has feature names (key indicator of tabular/generic data)
  const hasFeatures = metadata.feature_names && metadata.feature_names.length > 0;
  if (!hasFeatures) return false;

  // Check if it's NOT spectral data (more lenient check)
  // is_spectra can be false, undefined, or data_type can be "generic"
  const isSpectral = metadata.is_spectra === true || metadata.data_type === "spectra";
  if (isSpectral) return false;

  // Check it's not a specialized output type
  const notSpecialized = !isPCAOutput.value && !isMCROutput.value && !isPLSOutput.value &&
                         !isPLSDAOutput.value && !isClassificationOutput.value && !isHCAOutput.value;

  return notSpecialized;
});

// Generic dataset display options
const genericDisplayMode = ref<"boxplot" | "scatter_features">("boxplot");
const genericDisplayOptions = [
  { label: "Box Plot by Label", value: "boxplot" },
  { label: "Feature Scatter Plot", value: "scatter_features" },
];

// Feature axis selectors for generic scatter plot
const featureXAxis = ref(0);
const featureYAxis = ref(1);

// Build feature axis options from feature names
const featureAxisOptions = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  const featureNames = metadata.feature_names || [];
  if (featureNames.length === 0) {
    // Fallback to column indices
    const n = props.nodeOutput?.data?.[0]?.length || 4;
    return Array.from({ length: n }, (_, i) => ({
      label: `Feature ${i + 1}`,
      value: i,
    }));
  }
  return featureNames.map((name: string, i: number) => ({
    label: name,
    value: i,
  }));
});

// MCR/Decomposition display options (works for MCR-ALS, SIMPLISMA, NMF, FastICA)
const mcrDisplayMode = ref<"C" | "St">("C");
const mcrDisplayOptions = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  if (metadata?.type === "NMF") {
    return [
      { label: "Concentrations (W)", value: "C" },
      { label: "Basis Spectra (H)", value: "St" },
    ];
  } else if (metadata?.type === "FastICA") {
    return [
      { label: "Sources (S)", value: "C" },
      { label: "Spectral Profiles (Sᵀ)", value: "St" },
    ];
  } else {
    return [
      { label: "Concentrations (C)", value: "C" },
      { label: "Pure Spectra (Sᵀ)", value: "St" },
    ];
  }
});

// PCA display options
const pcaDisplayMode = ref<"scores" | "loadings" | "scree" | "diagnostics">("scores");
const pcaDisplayOptions = [
  { label: "Scores Plot", value: "scores" },
  { label: "Loadings Plot", value: "loadings" },
  { label: "Scree Plot", value: "scree" },
  { label: "Diagnostics Plot", value: "diagnostics" },
];

// PCA axis selection for scatter plot
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);

// PLS display options
const plsDisplayMode = ref<"scores" | "loadings">("scores");
const plsDisplayOptions = [
  { label: "Scores Plot", value: "scores" },
  { label: "Loadings Plot", value: "loadings" },
];

// PLS-DA display options (includes VIP plot, both loadings visualizations, and confusion matrices)
const plsdaDisplayMode = ref<"scores" | "loadings" | "loadings_biplot" | "vip" | "cm_train" | "cm_cv">("scores");
const plsdaDisplayOptions = [
  { label: "Scores Plot (with ellipses)", value: "scores" },
  { label: "Loadings (Lines)", value: "loadings" },
  { label: "Loadings (Biplot)", value: "loadings_biplot" },
  { label: "VIP Scores", value: "vip" },
  { label: "Confusion Matrix (Training)", value: "cm_train" },
  { label: "Confusion Matrix (CV)", value: "cm_cv" },
];

// HCA display options
const hcaDisplayMode = ref<"dendrogram">("dendrogram");
const hcaDisplayOptions = [
  { label: "Dendrogram", value: "dendrogram" },
];

// Watch for changes in PCA component count and clamp axis indices
watch(
  () => props.nodeOutput?.metadata?.n_components,
  (n_components) => {
    if (isPCAOutput.value && typeof n_components === "number") {
      const maxIndex = Math.max(0, n_components - 1);
      // Clamp X axis
      if (pcaXAxis.value > maxIndex) {
        pcaXAxis.value = Math.min(pcaXAxis.value, maxIndex);
      }
      // Clamp Y axis
      if (pcaYAxis.value > maxIndex) {
        pcaYAxis.value = Math.min(pcaYAxis.value, maxIndex);
      }
      // Special case: if only 1 component, both should be 0
      if (n_components === 1) {
        pcaXAxis.value = 0;
        pcaYAxis.value = 0;
      } else if (pcaXAxis.value === pcaYAxis.value && n_components > 1) {
        // If they're the same and we have >1 components, offset Y axis
        pcaYAxis.value = (pcaXAxis.value + 1) % n_components;
      }
    }
  },
  { immediate: true }
);

// Track current node type to detect changes
const currentNodeType = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  return metadata?.type || null;
});

// Reset axes when switching between different node types
watch(
  currentNodeType,
  (newType, oldType) => {
    // Only reset if the type actually changed and we're switching between nodes that use axes
    if (oldType && newType !== oldType) {
      const axisNodeTypes = ["PCA", "PLS", "PLS_DA", "SIMCA", "KNN"];
      if (axisNodeTypes.includes(newType as string)) {
        // Reset axes to default values when switching node types
        pcaXAxis.value = 0;
        pcaYAxis.value = 1;

        // Also reset display modes to default
        if (newType === "PCA") {
          pcaDisplayMode.value = "scores";
        } else if (newType === "PLS") {
          plsDisplayMode.value = "scores";
        }
      }
    }
  }
);

// Build PCA axis options based on number of components
const pcaAxisOptions = computed(() => {
  const metadata = props.nodeOutput?.metadata;
  const pcLabels = metadata?.pc_labels || [];
  const n = pcLabels.length || metadata?.n_components || 5;

  return Array.from({ length: n }, (_, i) => ({
    label: pcLabels[i] || `PC${i + 1}`,
    value: i,
  }));
});

// Auto-detect best plot type based on data
watch(
  () => props.nodeOutput,
  (output) => {
    if (!output?.data) return;

    const data = output.data;
    const metadata = output.metadata || {};

    // MCR-ALS output: always use line plot
    if (metadata.type === "MCR_ALS") {
      plotType.value = "line";
      return;
    }

    // PCA output: handled by pcaDisplayMode, no need to set plotType
    if (metadata.type === "PCA" || metadata.isPCA) {
      return;
    }

    // If data is 2D matrix with many rows, suggest heatmap
    if (Array.isArray(data) && data.length > 20 && Array.isArray(data[0])) {
      plotType.value = "heatmap";
    } else if (metadata.isScatter) {
      plotType.value = "scatter";
    } else {
      plotType.value = "line";
    }
  },
  { immediate: true }
);

// Update plot type when PCA display mode changes
watch(pcaDisplayMode, (mode) => {
  if (isPCAOutput.value) {
    plotType.value = mode === "scores" ? "scatter" : "line";
  }
});

// Compute data shape
const dataShape = computed(() => {
  const output = props.nodeOutput;
  const metadata = output?.metadata || {};

  // Detect if data is spectral type for appropriate labels
  const xTitle = (metadata.x_title || "").toLowerCase();
  const spectralKeywords = ['wavenumber', 'wavelength', 'raman', 'cm-1', 'cm⁻¹', 'nm', 'shift'];
  const isSpectral = metadata.is_spectra ?? spectralKeywords.some(kw => xTitle.includes(kw));

  // Use dynamic labels (DRY: rows are "spectra" for spectral data, "rows" otherwise)
  const defaultRowLabel = isSpectral ? "spectra" : "rows";
  const defaultColLabel = isSpectral ? "points" : "features";
  const defaultShape = { rows: 0, cols: 0, range: null, rowLabel: defaultRowLabel, colLabel: defaultColLabel };

  if (!output?.data) return defaultShape;

  const data = output.data;
  if (!Array.isArray(data)) return defaultShape;

  // Determine appropriate labels based on output type
  let rowLabel = defaultRowLabel;
  let colLabel = defaultColLabel;

  if (metadata.type === "MCR_ALS") {
    rowLabel = "samples";
    colLabel = "components";
  } else if (metadata.type === "PCA" || metadata.isPCA) {
    rowLabel = "observations";
    colLabel = "components";
  }

  // Handle Plotly format - extract shape from traces
  if (data.length > 0 && typeof data[0] === 'object' && data[0]?.type) {
    const trace = data[0];
    if (trace.z && Array.isArray(trace.z)) {
      // Heatmap/contour: z is 2D array
      const rows = trace.z.length;
      const cols = trace.z[0]?.length || 0;
      return { rows, cols, range: null, rowLabel, colLabel };
    } else if (trace.y && Array.isArray(trace.y)) {
      // Line/scatter: y is 1D array
      return { rows: trace.y.length, cols: 1, range: null, rowLabel: "points", colLabel: "traces" };
    }
    return { rows: data.length, cols: 0, range: null, rowLabel, colLabel };
  }

  const rows = data.length;
  const cols = Array.isArray(data[0]) ? data[0].length : 1;

  // Calculate value range
  let min = Infinity;
  let max = -Infinity;
  for (const row of data) {
    if (Array.isArray(row)) {
      for (const val of row) {
        if (typeof val === "number" && !isNaN(val)) {
          min = Math.min(min, val);
          max = Math.max(max, val);
        }
      }
    } else if (typeof row === "number" && !isNaN(row)) {
      min = Math.min(min, row);
      max = Math.max(max, row);
    }
  }

  return {
    rows,
    cols,
    range: min !== Infinity ? [min, max] : null,
    rowLabel,
    colLabel,
  };
});

// Check if data is pre-built Plotly format (from visualization nodes like CONTOUR_PLOT)
const isPlotlyFormat = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data) return false;

  // Check if nodeOutput itself has plot_type and data array with Plotly traces
  if (output.plot_type && Array.isArray(output.data) && output.data[0]?.type) {
    return true;
  }

  // Check if data array contains Plotly trace objects
  const data = output.data;
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object' && data[0]?.type) {
    return true;
  }

  return false;
});

// Dynamic axis labels from metadata (DRY with NodeDetailView.vue)
const xAxisTitle = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  return metadata.x_title || "Feature";
});

const xAxisUnits = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  return metadata.x_units || "";
});

const xAxisLabel = computed(() => {
  return xAxisUnits.value ? `${xAxisTitle.value} (${xAxisUnits.value})` : xAxisTitle.value;
});

const yAxisTitle = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  return metadata.y_title || "Value";
});

const yAxisUnits = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  return metadata.y_units || "";
});

const yAxisLabel = computed(() => {
  return yAxisUnits.value ? `${yAxisTitle.value} (${yAxisUnits.value})` : yAxisTitle.value;
});

// Detect if data is spectral type (wavenumber-based)
const isSpectraData = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  // Check backend-provided flag first
  if (metadata.is_spectra !== undefined) {
    return metadata.is_spectra;
  }
  // Fallback: check x_title for spectral keywords
  const xTitle = (metadata.x_title || "").toLowerCase();
  const spectralKeywords = ['wavenumber', 'wavelength', 'raman', 'cm-1', 'cm⁻¹', 'nm', 'shift'];
  return spectralKeywords.some(kw => xTitle.includes(kw));
});

// Feature names for hover templates and labels
const featureNames = computed(() => {
  const metadata = props.nodeOutput?.metadata || {};
  return metadata.feature_names || [];
});

// Data preview for table view (DRY with NodeDetailView.vue outputPreview)
const dataPreview = computed(() => {
  const data = props.nodeOutput?.data;
  if (!data || !Array.isArray(data)) return [];
  return data.slice(0, previewRowLimit).map((row: any, i: number) => {
    const obj: any = { _index: i + 1 };
    if (Array.isArray(row)) {
      row.slice(0, 10).forEach((val: any, j: number) => {
        obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
      });
    } else {
      obj.value = typeof row === "number" ? row.toFixed(4) : row;
    }
    return obj;
  });
});

// Data preview columns (DRY with NodeDetailView.vue outputPreviewColumns)
const dataPreviewColumns = computed(() => {
  if (!dataPreview.value.length) return [];
  const first = dataPreview.value[0];
  const metadata = props.nodeOutput?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const mcrLabels = metadata.labels || [];
  const _featureNames = metadata.feature_names || [];
  const xTitle = metadata.x_title || "";
  const isPCA = metadata.type === "PCA" || metadata.isPCA;
  const isMCR = metadata.type === "MCR_ALS";

  return Object.keys(first).map((key) => {
    let header = key;
    if (key === "_index") {
      header = "#";
    } else if (key.startsWith("col_")) {
      const colIdx = parseInt(key.replace("col_", ""));
      if (isPCA && pcLabels[colIdx]) {
        header = pcLabels[colIdx];
      } else if (isMCR && mcrLabels[colIdx]) {
        header = mcrLabels[colIdx];
      } else if (_featureNames.length > colIdx) {
        header = _featureNames[colIdx];
      } else if (xTitle && xTitle !== "Feature") {
        header = `${xTitle} ${colIdx + 1}`;
      } else {
        header = `Col ${colIdx + 1}`;
      }
    }
    return { field: key, header };
  });
});

// Build plot data based on type
const plotData = computed(() => {
  const output = props.nodeOutput;
  if (!output?.data && !output?.plots) return [];

  const data = output.data;
  const metadata = output.metadata || {};

  // Handle HCA dendrogram plots if available
  if (isHCAOutput.value) {
    const dendrogram = output.plots?.dendrogram;
    if (dendrogram?.data) {
      return dendrogram.data;
    }
    return buildScatterData(data, metadata);
  }

  // If this is pre-built Plotly data (from CONTOUR_PLOT, PLOT, etc.), use it directly
  if (isPlotlyFormat.value) {
    // Data is already in Plotly trace format
    return data;
  }

  // Handle MCR-ALS and decomposition outputs specially
  if (isMCROutput.value) {
    return buildMCRData(output, mcrDisplayMode.value);
  }

  // Handle PCA output specially
  if (isPCAOutput.value) {
    return buildPCAData(output, pcaDisplayMode.value, pcaXAxis.value, pcaYAxis.value);
  }

  // Handle PLS output (scores or loadings plot)
  if (isPLSOutput.value) {
    if (plsDisplayMode.value === "scores") {
      return buildPLSData(output, pcaXAxis.value, pcaYAxis.value);
    } else {
      return buildPLSLoadingsData(output);
    }
  }

  // Handle PLS-DA outputs with pre-built plots
  if (isPLSDAOutput.value) {
    if (output.plots && Object.keys(output.plots).length > 0) {
      return buildPLSDAPlotData(output, plsdaDisplayMode.value);
    }
    // Fallback: if no plots field, continue to classification handler below
  }

  // Handle classification outputs (PLS-DA without plots, SIMCA, KNN)
  if (isClassificationOutput.value) {
    return buildClassificationData(output, pcaXAxis.value, pcaYAxis.value);
  }

  // Handle generic dataset output (Load Data with non-spectral data like Iris)
  if (isGenericDatasetOutput.value) {
    if (genericDisplayMode.value === "boxplot") {
      return buildBoxPlotData(output);
    } else if (genericDisplayMode.value === "scatter_features") {
      return buildFeatureScatterData(output, featureXAxis.value, featureYAxis.value);
    }
  }

  // Get x-axis values: priority feature_names > wavenumbers > x_axis (DRY with NodeDetailView)
  const _featureNames = metadata.feature_names;
  const wavenumbersRaw = metadata.wavenumbers || metadata.x_axis || null;
  const dataLength = Array.isArray(data[0]) ? data[0].length : data.length;
  let xAxisValues = null;
  if (_featureNames && _featureNames.length === dataLength) {
    xAxisValues = _featureNames;
  } else if (wavenumbersRaw && wavenumbersRaw.length === dataLength) {
    xAxisValues = wavenumbersRaw;
  }

  if (plotType.value === "line") {
    return buildLineData(data, xAxisValues, metadata);
  } else if (plotType.value === "heatmap") {
    return buildHeatmapData(data, xAxisValues, metadata);
  } else if (plotType.value === "scatter") {
    return buildScatterData(data, metadata);
  }

  return [];
});

// Build MCR-ALS and decomposition specific plot data
function buildMCRData(output: any, mode: "C" | "St"): any[] {
  const metadata = output.metadata || {};
  const traces: any[] = [];

  if (mode === "C") {
    // Concentration profiles: C is (n_samples, n_components)
    // Each column is a component's concentration over time
    // For NMF, data is W matrix; for FastICA, data is S matrix
    const C = output.data; // Already in correct format
    const x = metadata.x_axis || Array.from({ length: C.length }, (_, i) => i);
    const labels = metadata.labels || [];
    const n_components = C[0]?.length || 0;
    const sampleLabels = metadata.sample_labels || Array.from({ length: C.length }, (_, i) => `Sample ${i + 1}`);

    // Transpose C: plot each component as a separate trace
    for (let comp = 0; comp < n_components; comp++) {
      const y = C.map((row: number[]) => row[comp]);
      const trace: any = {
        type: "scatter",
        mode: "lines+markers",
        x: x,
        y: y,
        name: labels[comp] || `Component ${comp + 1}`,
        line: { width: 2 },
        marker: { size: 6 },
        text: sampleLabels,
        hovertemplate: "%{text}<br>X: %{x}<br>Y: %{y:.3f}<extra></extra>",
      };

      traces.push(trace);
    }
  } else {
    // Pure spectra: St is (n_components, n_features)
    // Each row is a pure component spectrum
    const St = metadata.St || [];
    // Priority: feature_names > wavenumbers > feature indices (DRY with NodeDetailView)
    const _featureNames = metadata.feature_names;
    const wavenumbers = metadata.wavenumbers;
    let x_values;
    if (_featureNames && _featureNames.length === St[0]?.length) {
      x_values = _featureNames;
    } else if (wavenumbers && wavenumbers.length === St[0]?.length) {
      x_values = wavenumbers;
    } else {
      x_values = Array.from({ length: St[0]?.length || 0 }, (_, i) => i);
    }
    const labels = metadata.St_labels || [];

    for (let comp = 0; comp < St.length; comp++) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x: x_values,
        y: St[comp],
        name: labels[comp] || `Pure Spectrum ${comp + 1}`,
        line: { width: 2 },
      });
    }
  }

  return traces;
}

// Build PCA specific plot data
function buildPCAData(output: any, mode: "scores" | "loadings" | "scree" | "diagnostics", xAxis: number, yAxis: number): any[] {
  const metadata = output.metadata || {};
  const traces: any[] = [];

  if (mode === "scores") {
    // Scores scatter plot: data is (n_observations, n_components)
    const scores = output.data;
    if (!scores || !scores.length) return [];

    const pcLabels = metadata.pc_labels || [];
    const sampleLabels = metadata.sample_labels ||
      Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
    const labelCategories = metadata.label_categories;

    // Determine if we should use categorical coloring
    const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

    if (useCategorical) {
      // Multiple traces, one per category
      const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

      // Group points by category
      const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
      labelCategories.forEach((cat: any) => {
        categoryGroups.set(cat, { x: [], y: [], labels: [] });
      });

      scores.forEach((row: number[], idx: number) => {
        const category = sampleLabels[idx];
        const group = categoryGroups.get(category);
        if (group) {
          group.x.push(row[xAxis]);
          group.y.push(row[yAxis]);
          group.labels.push(String(sampleLabels[idx]));
        }
      });

      // Create one trace per category
      labelCategories.forEach((category: any) => {
        const group = categoryGroups.get(category);
        if (group && group.x.length > 0) {
          traces.push({
            type: "scatter",
            mode: "markers",
            x: group.x,
            y: group.y,
            text: group.labels,
            name: String(category),
            marker: {
              size: 10,
              color: colorMap.get(category),
              opacity: 0.8,
              line: { width: 1, color: "rgba(0,0,0,0.3)" },
            },
            hovertemplate: "%{text}<br>" +
              (pcLabels[xAxis] || `PC${xAxis + 1}`) + ": %{x:.3f}<br>" +
              (pcLabels[yAxis] || `PC${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
          });
        }
      });
    } else {
      // Fallback: Single trace with default blue color
      const x = scores.map((row: number[]) => row[xAxis]);
      const y = scores.map((row: number[]) => row[yAxis]);

      traces.push({
        type: "scatter",
        mode: "markers",
        x: x,
        y: y,
        text: sampleLabels,
        marker: {
          size: 10,
          color: "#3b82f6",
          opacity: 0.8,
          line: { width: 1, color: "#1e40af" },
        },
        hovertemplate: "%{text}<br>" +
          (pcLabels[xAxis] || `PC${xAxis + 1}`) + ": %{x:.3f}<br>" +
          (pcLabels[yAxis] || `PC${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
      });
    }
  } else if (mode === "loadings") {
    // Loadings plot: loadings is (n_components, n_features)
    const loadings = metadata.loadings || [];
    // Priority: feature_names > wavenumbers > feature indices (DRY with NodeDetailView)
    const _featureNames = metadata.feature_names;
    const wavenumbers = metadata.wavenumbers;
    let x_values;
    if (_featureNames && _featureNames.length === loadings[0]?.length) {
      x_values = _featureNames;
    } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
      x_values = wavenumbers;
    } else {
      x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
    }
    const pcLabels = metadata.pc_labels || [];

    for (let i = 0; i < loadings.length; i++) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x: x_values,
        y: loadings[i],
        name: pcLabels[i] || `PC${i + 1}`,
        line: { width: 2 },
      });
    }
  } else if (mode === "scree") {
    // Scree plot: explained variance per component
    const variance = metadata.explained_variance_ratio || [];
    if (!variance.length) return [];

    const pcLabels = metadata.pc_labels || [];
    const componentNumbers = Array.from({ length: variance.length }, (_, i) => i + 1);

    // Convert to percentages for display
    const variancePercent = variance.map((v: number) => v * 100);

    traces.push({
      type: "bar",
      x: componentNumbers,
      y: variancePercent,
      name: "Explained Variance",
      marker: { color: "#3b82f6" },
      hovertemplate: "%{x}: %{y:.2f}%<extra></extra>",
    });

    // Add cumulative variance line
    const cumulative = [];
    let sum = 0;
    for (const v of variancePercent) {
      sum += v;
      cumulative.push(sum);
    }

    traces.push({
      type: "scatter",
      mode: "lines+markers",
      x: componentNumbers,
      y: cumulative,
      name: "Cumulative Variance",
      yaxis: "y2",
      line: { color: "#ef4444", width: 2 },
      marker: { size: 8, color: "#ef4444" },
      hovertemplate: "PC%{x}: %{y:.2f}% cumulative<extra></extra>",
    });
  } else if (mode === "diagnostics") {
    // Diagnostics plot: Hotelling T² and SPE with categorical coloring
    const t2 = metadata.t2 || [];
    const spe = metadata.spe || [];
    const sampleLabels = metadata.sample_labels ||
      Array.from({ length: t2.length }, (_, i) => `Sample ${i + 1}`);
    const labelCategories = metadata.label_categories;

    if (!t2.length && !spe.length) return [];

    const sampleIndices = Array.from({ length: Math.max(t2.length, spe.length) }, (_, i) => i + 1);

    // Determine if we should use categorical coloring
    const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

    if (useCategorical) {
      // Categorical coloring: one trace per category
      const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

      // Group data by category
      const categoryGroups = new Map<string | number, { indices: number[], t2Values: number[], speValues: number[], labels: string[] }>();
      labelCategories.forEach((cat: any) => {
        categoryGroups.set(cat, { indices: [], t2Values: [], speValues: [], labels: [] });
      });

      sampleIndices.forEach((idx: number, i: number) => {
        const category = sampleLabels[i];
        const group = categoryGroups.get(category);
        if (group) {
          group.indices.push(idx);
          if (t2.length > i) group.t2Values.push(t2[i]);
          if (spe.length > i) group.speValues.push(spe[i]);
          group.labels.push(String(sampleLabels[i]));
        }
      });

      // Create T² traces per category
      if (t2.length > 0) {
        labelCategories.forEach((category: any) => {
          const group = categoryGroups.get(category);
          if (group && group.t2Values.length > 0) {
            traces.push({
              type: "scatter",
              mode: "markers",
              x: group.indices,
              y: group.t2Values,
              name: `T²: ${String(category)}`,
              text: group.labels,
              marker: { size: 8, color: colorMap.get(category), symbol: "circle" },
              hovertemplate: "%{text}<br>T²: %{y:.2f}<extra></extra>",
              legendgroup: String(category),
            });
          }
        });

        // Add T² control limit if available
        const t2_p95 = metadata.t2_p95;
        if (t2_p95) {
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [sampleIndices[0], sampleIndices[sampleIndices.length - 1]],
            y: [t2_p95, t2_p95],
            name: "T² Limit (95%)",
            line: { color: "#64748b", dash: "dash", width: 2 },
            showlegend: true,
            hoverinfo: "skip",
            legendgroup: "limits",
          });
        }
      }

      // Create SPE traces per category
      if (spe.length > 0) {
        labelCategories.forEach((category: any) => {
          const group = categoryGroups.get(category);
          if (group && group.speValues.length > 0) {
            traces.push({
              type: "scatter",
              mode: "markers",
              x: group.indices,
              y: group.speValues,
              name: `SPE: ${String(category)}`,
              text: group.labels,
              yaxis: "y2",
              marker: { size: 8, color: colorMap.get(category), symbol: "square" },
              hovertemplate: "%{text}<br>SPE: %{y:.2f}<extra></extra>",
              legendgroup: String(category),
            });
          }
        });

        // Add SPE control limit if available
        const spe_p95 = metadata.spe_p95;
        if (spe_p95) {
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [sampleIndices[0], sampleIndices[sampleIndices.length - 1]],
            y: [spe_p95, spe_p95],
            name: "SPE Limit (95%)",
            yaxis: "y2",
            line: { color: "#64748b", dash: "dash", width: 2 },
            showlegend: true,
            hoverinfo: "skip",
            legendgroup: "limits",
          });
        }
      }
    } else {
      // Fallback: static colors when no categorical labels
      if (t2.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: sampleIndices,
          y: t2,
          name: "Hotelling T²",
          text: sampleLabels,
          marker: { size: 8, color: "#3b82f6", symbol: "circle" },
          hovertemplate: "%{text}<br>T²: %{y:.2f}<extra></extra>",
        });

        // Add T² control limit if available
        const t2_p95 = metadata.t2_p95;
        if (t2_p95) {
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [sampleIndices[0], sampleIndices[sampleIndices.length - 1]],
            y: [t2_p95, t2_p95],
            name: "T² Limit (95%)",
            line: { color: "#3b82f6", dash: "dash", width: 2 },
            showlegend: true,
            hoverinfo: "skip",
          });
        }
      }

      if (spe.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: sampleIndices,
          y: spe,
          name: "SPE (Q)",
          text: sampleLabels,
          yaxis: "y2",
          marker: { size: 8, color: "#ef4444", symbol: "square" },
          hovertemplate: "%{text}<br>SPE: %{y:.2f}<extra></extra>",
        });

        // Add SPE control limit if available
        const spe_p95 = metadata.spe_p95;
        if (spe_p95) {
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [sampleIndices[0], sampleIndices[sampleIndices.length - 1]],
            y: [spe_p95, spe_p95],
            name: "SPE Limit (95%)",
            yaxis: "y2",
            line: { color: "#ef4444", dash: "dash", width: 2 },
            showlegend: true,
            hoverinfo: "skip",
          });
        }
      }
    }
  }

  return traces;
}

// Build PLS specific plot data (scores plot with categorical coloring)
function buildPLSData(output: any, xAxis: number, yAxis: number): any[] {
  const metadata = output.metadata || {};
  const traces: any[] = [];

  // PLS scores plot: data is (n_observations, n_components)
  const scores = output.data;
  if (!scores || !scores.length) return [];

  const pcLabels = metadata.pc_labels || [];
  const sampleLabels = metadata.sample_labels ||
    Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = metadata.label_categories;

  // Determine if we should use categorical coloring
  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    // Multiple traces, one per category
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

    // Group points by category
    const categoryGroups = new Map();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = sampleLabels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[xAxis]);
        group.y.push(row[yAxis]);
        group.labels.push(sampleLabels[idx]);
      }
    });

    // Create one trace per category
    labelCategories.forEach((category: any) => {
      const group = categoryGroups.get(category);
      if (group && group.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: group.x,
          y: group.y,
          text: group.labels,
          name: String(category),
          marker: {
            size: 10,
            color: colorMap.get(category),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: "%{text}<br>" +
            (pcLabels[xAxis] || `LV${xAxis + 1}`) + ": %{x:.3f}<br>" +
            (pcLabels[yAxis] || `LV${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
        });
      }
    });
  } else {
    // Fallback: Single trace with default blue color
    const x = scores.map((row: number[]) => row[xAxis]);
    const y = scores.map((row: number[]) => row[yAxis]);

    traces.push({
      type: "scatter",
      mode: "markers",
      x: x,
      y: y,
      text: sampleLabels,
      marker: {
        size: 10,
        color: "#3b82f6",
        opacity: 0.8,
        line: { width: 1, color: "#1e40af" },
      },
      hovertemplate: "%{text}<br>" +
        (pcLabels[xAxis] || `LV${xAxis + 1}`) + ": %{x:.3f}<br>" +
        (pcLabels[yAxis] || `LV${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
    });
  }

  return traces;
}

// Build PLS loadings plot data
function buildPLSLoadingsData(output: any): any[] {
  const metadata = output.metadata || {};
  const traces: any[] = [];

  // PLS loadings plot: X_loadings is (n_components, n_features)
  const loadings = metadata.X_loadings || [];
  if (!loadings || !loadings.length) return [];

  // Priority: feature_names > wavenumbers > feature indices (DRY with NodeDetailView)
  const _featureNames = metadata.feature_names;
  const wavenumbers = metadata.wavenumbers;
  let x_values;
  if (_featureNames && _featureNames.length === loadings[0]?.length) {
    x_values = _featureNames;
  } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
    x_values = wavenumbers;
  } else {
    x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
  }
  const pcLabels = metadata.pc_labels || [];
  const xLabel = xAxisTitle.value || "Feature";

  // Create one trace per latent variable (component)
  for (let i = 0; i < loadings.length; i++) {
    traces.push({
      type: "scatter",
      mode: "lines",
      x: x_values,
      y: loadings[i],
      name: pcLabels[i] || `LV${i + 1}`,
      line: { width: 2 },
      hovertemplate: `${xLabel}: %{x}<br>Loading: %{y:.4f}<extra></extra>`,
    });
  }

  return traces;
}

// Build PLS-DA specific plot data from pre-built plots
function buildPLSDAPlotData(output: any, mode: "scores" | "loadings" | "loadings_biplot" | "vip" | "cm_train" | "cm_cv"): any[] {
  const plots = output.plots || {};

  // Return the appropriate plot based on mode
  if (mode === "scores" && plots.scores) {
    return plots.scores.data || [];
  } else if (mode === "loadings") {
    // Try loadings_lines first (preferred for spectral data), fall back to loadings
    return plots.loadings_lines?.data || plots.loadings?.data || [];
  } else if (mode === "loadings_biplot" && plots.loadings_biplot) {
    return plots.loadings_biplot.data || [];
  } else if (mode === "vip" && plots.vip) {
    return plots.vip.data || [];
  } else if (mode === "cm_train" && plots.confusion_matrix_train) {
    return plots.confusion_matrix_train.data || [];
  } else if (mode === "cm_cv" && plots.confusion_matrix_cv) {
    return plots.confusion_matrix_cv.data || [];
  }

  // Fallback to empty if plot not available
  console.warn(`[QuickPlot] PLS-DA plot '${mode}' not available in output.plots`, plots);
  return [];
}

// Build classification output plot data (PLS-DA, SIMCA, KNN)
function buildClassificationData(output: any, xAxis: number, yAxis: number): any[] {
  const metadata = output.metadata || {};
  const traces: any[] = [];

  // For PLS-DA: data is scores (n_samples, n_components)
  // For SIMCA: data is scores in first class PC space (n_samples, n_components)
  // For KNN: data is PCA scores for high-dim or original features for low-dim
  const data = output.data;
  if (!data || !data.length) return [];

  const pcLabels = metadata.pc_labels || [];
  const sampleLabels = metadata.sample_labels ||
    Array.from({ length: data.length }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = metadata.label_categories;

  // Determine if we should use categorical coloring (always true for classification)
  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    // Multiple traces, one per category (class)
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

    // Group points by category
    const categoryGroups = new Map();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    data.forEach((row: number[], idx: number) => {
      const category = sampleLabels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        // Data is always 2D array (scores or features)
        group.x.push(row[xAxis]);
        group.y.push(row[yAxis]);
        group.labels.push(sampleLabels[idx]);
      }
    });

    // Create one trace per category
    labelCategories.forEach((category: any) => {
      const group = categoryGroups.get(category);
      if (group && group.x.length > 0) {
        traces.push({
          type: "scatter",
          mode: "markers",
          x: group.x,
          y: group.y,
          text: group.labels,
          name: String(category),
          marker: {
            size: 10,
            color: colorMap.get(category),
            opacity: 0.8,
            line: { width: 1, color: "rgba(0,0,0,0.3)" },
          },
          hovertemplate: "%{text}<br>" +
            (pcLabels[xAxis] || `Dimension ${xAxis + 1}`) + ": %{x:.3f}<br>" +
            (pcLabels[yAxis] || `Dimension ${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
        });
      }
    });
  } else {
    // Fallback: Single trace with default blue color
    const x = data.map((row: number[]) => row[xAxis]);
    const y = data.map((row: number[]) => row[yAxis]);

    traces.push({
      type: "scatter",
      mode: "markers",
      x: x,
      y: y,
      text: sampleLabels,
      marker: {
        size: 10,
        color: "#3b82f6",
        opacity: 0.8,
        line: { width: 1, color: "#1e40af" },
      },
      hovertemplate: "%{text}<br>" +
        (pcLabels[xAxis] || `Dimension ${xAxis + 1}`) + ": %{x:.3f}<br>" +
        (pcLabels[yAxis] || `Dimension ${yAxis + 1}`) + ": %{y:.3f}<extra></extra>",
    });
  }

  return traces;
}

// Build box plot data for generic datasets (one box per feature with points colored by class)
function buildBoxPlotData(output: any): any[] {
  const data = output.data;
  const metadata = output.metadata || {};
  if (!data || !Array.isArray(data) || data.length === 0) return [];

  const traces: any[] = [];
  const _featureNames = metadata.feature_names || [];
  const sampleLabels = metadata.labels || [];
  const n_features = Math.min(data[0]?.length || 0, 10);

  // Get unique categories from sample labels
  const categories = [...new Set(sampleLabels)];
  const hasCategories = categories.length > 1 && categories.length < 20;

  // Use color palette for categories
  const colors = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1"
  ];

  // Create one box per feature (showing all data)
  for (let featureIdx = 0; featureIdx < n_features; featureIdx++) {
    const featureValues = data.map((row: number[]) => row[featureIdx]);
    const featureName = _featureNames[featureIdx] || `Feature ${featureIdx + 1}`;

    traces.push({
      type: "box",
      y: featureValues,
      name: featureName,
      marker: { color: "#64748b" }, // Neutral gray for boxes
      boxpoints: false, // Don't show points on box - we'll add colored scatter
      showlegend: false,
    });
  }

  // If we have categories, add colored scatter points on top
  if (hasCategories) {
    categories.forEach((category, catIdx) => {
      const categoryIndices = sampleLabels
        .map((label: string, idx: number) => label === category ? idx : -1)
        .filter((idx: number) => idx !== -1);

      // Collect all points for this class across all features
      const xValues: string[] = [];
      const yValues: number[] = [];

      for (let featureIdx = 0; featureIdx < n_features; featureIdx++) {
        const featureName = _featureNames[featureIdx] || `Feature ${featureIdx + 1}`;
        categoryIndices.forEach((rowIdx: number) => {
          xValues.push(featureName);
          yValues.push(data[rowIdx][featureIdx]);
        });
      }

      traces.push({
        type: "scatter",
        mode: "markers",
        x: xValues,
        y: yValues,
        name: String(category),
        marker: {
          color: colors[catIdx % colors.length],
          size: 6,
          opacity: 0.7,
        },
        legendgroup: String(category),
        showlegend: true,
        hovertemplate: `${category}<br>%{x}: %{y:.3f}<extra></extra>`,
      });
    });
  }

  return traces;
}

// Build feature scatter plot data (X/Y from selected features, colored by label)
function buildFeatureScatterData(output: any, xFeatureIdx: number, yFeatureIdx: number): any[] {
  const data = output.data;
  const metadata = output.metadata || {};
  if (!data || !Array.isArray(data) || data.length === 0) return [];

  const traces: any[] = [];
  const _featureNames = metadata.feature_names || [];
  const sampleLabels = metadata.labels || [];
  const xFeatureName = _featureNames[xFeatureIdx] || `Feature ${xFeatureIdx + 1}`;
  const yFeatureName = _featureNames[yFeatureIdx] || `Feature ${yFeatureIdx + 1}`;

  // Get unique categories from sample labels
  const categories = [...new Set(sampleLabels)];
  const hasCategories = categories.length > 1 && categories.length < 20;

  // Use color palette for categories
  const colors = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1"
  ];

  if (hasCategories) {
    // Create one trace per category
    categories.forEach((category, catIdx) => {
      const categoryIndices = sampleLabels
        .map((label: string, idx: number) => label === category ? idx : -1)
        .filter((idx: number) => idx !== -1);

      const xValues = categoryIndices.map((rowIdx: number) => data[rowIdx][xFeatureIdx]);
      const yValues = categoryIndices.map((rowIdx: number) => data[rowIdx][yFeatureIdx]);
      const textLabels = categoryIndices.map((rowIdx: number) => `Sample ${rowIdx + 1}`);

      traces.push({
        type: "scatter",
        mode: "markers",
        x: xValues,
        y: yValues,
        text: textLabels,
        name: String(category),
        marker: {
          size: 10,
          color: colors[catIdx % colors.length],
          opacity: 0.8,
          line: { width: 1, color: "rgba(0,0,0,0.3)" },
        },
        hovertemplate: `%{text}<br>${xFeatureName}: %{x:.3f}<br>${yFeatureName}: %{y:.3f}<extra>${category}</extra>`,
      });
    });
  } else {
    // No categories - single trace
    const xValues = data.map((row: number[]) => row[xFeatureIdx]);
    const yValues = data.map((row: number[]) => row[yFeatureIdx]);
    const textLabels = data.map((_: any, idx: number) => sampleLabels[idx] || `Sample ${idx + 1}`);

    traces.push({
      type: "scatter",
      mode: "markers",
      x: xValues,
      y: yValues,
      text: textLabels,
      marker: {
        size: 10,
        color: "#3b82f6",
        opacity: 0.8,
        line: { width: 1, color: "#1e40af" },
      },
      hovertemplate: `%{text}<br>${xFeatureName}: %{x:.3f}<br>${yFeatureName}: %{y:.3f}<extra></extra>`,
    });
  }

  return traces;
}

function buildLineData(data: any[], xAxisValues: any[] | null, metadata: any) {
  const traces: any[] = [];
  const labels = metadata.labels || [];
  // Use "Row" for non-spectral data (DRY with NodeDetailView)
  const rowLabel = isSpectraData.value ? "Spectrum" : "Row";

  // Handle different data formats
  if (Array.isArray(data[0])) {
    // 2D array: each row is a spectrum/row
    const maxTraces = Math.min(data.length, 50); // Limit for performance
    for (let i = 0; i < maxTraces; i++) {
      const row = data[i];
      const x = xAxisValues || Array.from({ length: row.length }, (_, j) => j);
      traces.push({
        type: "scatter",
        mode: "lines",
        x: x,
        y: row,
        name: labels[i] || `${rowLabel} ${i + 1}`,
        line: { width: 1.5 },
        opacity: lineDisplayMode.value === "overlay" ? 0.7 : 1,
      });
    }
  } else {
    // 1D array: single spectrum/row
    const x = xAxisValues || Array.from({ length: data.length }, (_, i) => i);
    traces.push({
      type: "scatter",
      mode: "lines",
      x: x,
      y: data,
      name: labels[0] || rowLabel,
      line: { width: 2 },
    });
  }

  return traces;
}

function buildHeatmapData(data: any[], wavenumbers: number[] | null, metadata: any) {
  // Transpose if needed (rows = spectra, cols = wavenumbers)
  const z = Array.isArray(data[0]) ? data : [data];
  const x = wavenumbers || Array.from({ length: z[0]?.length || 0 }, (_, i) => i);
  const y = metadata.times || Array.from({ length: z.length }, (_, i) => i);

  // Use dynamic y-axis title for colorbar (DRY with NodeDetailView)
  const colorbarTitle = metadata.y_title || yAxisTitle.value || "Value";

  return [
    {
      type: "heatmap",
      z: z,
      x: x,
      y: y,
      colorscale: "Viridis",
      colorbar: {
        title: colorbarTitle,
        titleside: "right",
      },
    },
  ];
}

function buildScatterData(data: any[], metadata: any) {
  const traces: any[] = [];
  const labels = metadata.labels || [];

  // Assume first two columns are x, y coordinates
  const x = data.map((row) => (Array.isArray(row) ? row[0] : row));
  const y = data.map((row) => (Array.isArray(row) ? row[1] : 0));
  const text = labels.length ? labels : data.map((_, i) => `Point ${i + 1}`);

  traces.push({
    type: "scatter",
    mode: "markers",
    x: x,
    y: y,
    text: text,
    marker: {
      size: 8,
      color: "#3b82f6",
      opacity: 0.7,
    },
    hovertemplate: "%{text}<br>x: %{x:.3f}<br>y: %{y:.3f}<extra></extra>",
  });

  return traces;
}

// Plot layout
const plotLayout = computed(() => {
  const output = props.nodeOutput;
  const metadata = output?.metadata || {};

  const baseLayout = {
    template: "plotly_dark",
    paper_bgcolor: "#0f172a",
    plot_bgcolor: "#0f172a",
    font: { color: "#f8fafc", size: 12 },
    margin: { t: 40, r: 40, b: 60, l: 70 },
    showlegend: plotType.value === "line" && dataShape.value.rows <= 10,
    legend: {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
    },
  };

  // HCA dendrogram layout (use pre-built when available)
  if (isHCAOutput.value) {
    const dendrogramLayout = output?.plots?.dendrogram?.layout;
    return {
      ...baseLayout,
      height: 520,           // Default height (will be overwritten by backend if provided)
      showlegend: false,
      paper_bgcolor: "#0f172a",
      plot_bgcolor: "#0f172a",
      ...(dendrogramLayout || {}),  // Backend values override defaults
    };
  }

  // If pre-built Plotly data with layout, merge it
  if (isPlotlyFormat.value && output?.layout) {
    return {
      ...baseLayout,
      ...output.layout,
      // Override background colors for dark theme
      paper_bgcolor: "#0f172a",
      plot_bgcolor: "#0f172a",
    };
  }

  // MCR-ALS specific layout
  if (isMCROutput.value) {
    if (mcrDisplayMode.value === "C") {
      return {
        ...baseLayout,
        showlegend: true,
        xaxis: {
          title: metadata.x_label || "Time / Sample Index",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: metadata.y_label || "Relative Concentration",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    } else {
      return {
        ...baseLayout,
        showlegend: true,
        xaxis: {
          title: xAxisLabel.value,
          autorange: isSpectraData.value ? "reversed" : true,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: yAxisLabel.value,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    }
  }

  // PCA specific layout
  if (isPCAOutput.value) {
    const pcLabels = metadata.pc_labels || [];

    if (pcaDisplayMode.value === "scores") {
      const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

      const layout: Record<string, any> = {
        ...baseLayout,
        showlegend: hasCategorical,
        xaxis: {
          title: pcLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: pcLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };

      // Ensure legend is properly configured when categorical
      if (hasCategorical) {
        layout.legend = {
          ...baseLayout.legend,
          x: 1,
          y: 1,
          xanchor: "right",
          yanchor: "top",
        } as any;
      }

      return layout;
    } else if (pcaDisplayMode.value === "loadings") {
      return {
        ...baseLayout,
        showlegend: true,
        xaxis: {
          title: xAxisLabel.value,
          autorange: isSpectraData.value ? "reversed" : true,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: "Loading",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    } else if (pcaDisplayMode.value === "scree") {
      return {
        ...baseLayout,
        showlegend: true,
        xaxis: {
          title: "Principal Component",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: "Explained Variance (%)",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis2: {
          title: "Cumulative Variance (%)",
          overlaying: "y",
          side: "right",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    } else if (pcaDisplayMode.value === "diagnostics") {
      return {
        ...baseLayout,
        margin: { t: 40, r: 80, b: 60, l: 70 },
        showlegend: true,
        xaxis: {
          title: "Sample Number",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: "Hotelling T²",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis2: {
          title: { text: "SPE (Q Residuals)", standoff: 20 },
          overlaying: "y",
          side: "right",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    }
  }

  // PLS specific layout
  if (isPLSOutput.value) {
    const pcLabels = metadata.pc_labels || [];

    if (plsDisplayMode.value === "scores") {
      const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

      const layout: Record<string, any> = {
        ...baseLayout,
        showlegend: hasCategorical,
        xaxis: {
          title: pcLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}`,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: pcLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}`,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };

      // Ensure legend is properly configured when categorical
      if (hasCategorical) {
        layout.legend = {
          ...baseLayout.legend,
          x: 1,
          y: 1,
          xanchor: "right",
          yanchor: "top",
        } as any;
      }

      return layout;
    } else if (plsDisplayMode.value === "loadings") {
      return {
        ...baseLayout,
        showlegend: true,
        xaxis: {
          title: xAxisLabel.value,
          autorange: isSpectraData.value ? "reversed" : true,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: "Loading",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    }
  }

  // PLS-DA specific layout with pre-built plots
  if (isPLSDAOutput.value && output?.plots) {
    const plots = output.plots || {};
    let plotLayout = null;

    if (plsdaDisplayMode.value === "scores" && plots.scores) {
      plotLayout = plots.scores.layout;
    } else if (plsdaDisplayMode.value === "loadings") {
      // Try loadings_lines first (preferred for spectral data), fall back to loadings
      plotLayout = plots.loadings_lines?.layout || plots.loadings?.layout;
    } else if (plsdaDisplayMode.value === "loadings_biplot" && plots.loadings_biplot) {
      plotLayout = plots.loadings_biplot.layout;
    } else if (plsdaDisplayMode.value === "vip" && plots.vip) {
      plotLayout = plots.vip.layout;
    } else if (plsdaDisplayMode.value === "cm_train" && plots.confusion_matrix_train) {
      plotLayout = plots.confusion_matrix_train.layout;
    } else if (plsdaDisplayMode.value === "cm_cv" && plots.confusion_matrix_cv) {
      plotLayout = plots.confusion_matrix_cv.layout;
    }

    if (plotLayout) {
      return {
        ...baseLayout,
        ...plotLayout,
        // Override background colors for dark theme
        paper_bgcolor: "#0f172a",
        plot_bgcolor: "#0f172a",
        font: { color: "#f8fafc", size: 12 },
        // Ensure xaxis and yaxis have grid colors
        xaxis: {
          ...plotLayout.xaxis,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          ...plotLayout.yaxis,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
      };
    }
  }

  // Classification specific layout (PLS-DA without plots, SIMCA, KNN)
  if (isClassificationOutput.value) {
    const pcLabels = metadata.pc_labels || [];
    const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

    const layout: Record<string, any> = {
      ...baseLayout,
      showlegend: hasCategorical,
      xaxis: {
        title: pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}`,
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
      yaxis: {
        title: pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}`,
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
    };

    // Ensure legend is properly configured when categorical
    if (hasCategorical) {
      layout.legend = {
        ...baseLayout.legend,
        x: 1,
        y: 1,
        xanchor: "right",
        yanchor: "top",
      } as any;
    }

    return layout;
  }

  // Generic dataset layout (Load Data with non-spectral data like Iris)
  if (isGenericDatasetOutput.value) {
    const _featureNames = metadata.feature_names || [];
    const sampleLabels = metadata.labels || [];
    const categories = [...new Set(sampleLabels)];
    const hasCategories = categories.length > 1 && categories.length < 20;

    if (genericDisplayMode.value === "boxplot") {
      return {
        ...baseLayout,
        showlegend: hasCategories,
        boxmode: "group",
        xaxis: {
          title: "Feature",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: "Value",
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        legend: hasCategories ? {
          ...baseLayout.legend,
          x: 1,
          y: 1,
          xanchor: "right",
          yanchor: "top",
        } : baseLayout.legend,
      };
    } else if (genericDisplayMode.value === "scatter_features") {
      const xFeatureName = _featureNames[featureXAxis.value] || `Feature ${featureXAxis.value + 1}`;
      const yFeatureName = _featureNames[featureYAxis.value] || `Feature ${featureYAxis.value + 1}`;

      return {
        ...baseLayout,
        showlegend: hasCategories,
        xaxis: {
          title: xFeatureName,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        yaxis: {
          title: yFeatureName,
          gridcolor: "#334155",
          zerolinecolor: "#475569",
        },
        legend: hasCategories ? {
          ...baseLayout.legend,
          x: 1,
          y: 1,
          xanchor: "right",
          yanchor: "top",
        } : baseLayout.legend,
      };
    }
  }

  if (plotType.value === "line") {
    return {
      ...baseLayout,
      xaxis: {
        title: metadata.x_label || xAxisLabel.value,
        autorange: isSpectraData.value ? "reversed" : true,
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
      yaxis: {
        title: metadata.y_label || yAxisLabel.value,
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
    };
  } else if (plotType.value === "heatmap") {
    return {
      ...baseLayout,
      xaxis: {
        title: metadata.x_label || xAxisLabel.value,
        autorange: isSpectraData.value ? "reversed" : true,
      },
      yaxis: {
        title: metadata.y_label || "Sample Index",
      },
    };
  } else {
    // Scatter plot: use generic dimension labels
    return {
      ...baseLayout,
      xaxis: {
        title: metadata.x_label || "Dimension 1",
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
      yaxis: {
        title: metadata.y_label || "Dimension 2",
        gridcolor: "#334155",
        zerolinecolor: "#475569",
      },
    };
  }
});

const plotConfig = {
  responsive: true,
  displayModeBar: true,
  modeBarButtonsToRemove: ["lasso2d", "select2d"],
  displaylogo: false,
};

// Download functionality
const plotContainer = ref<HTMLElement | null>(null);

function downloadPlot() {
  // Use Plotly's built-in download
  const plotDiv = plotContainer.value?.querySelector(".js-plotly-plot") as HTMLElement;
  const PlotlyGlobal = (window as unknown as { Plotly?: { downloadImage: (el: HTMLElement, opts: Record<string, unknown>) => void } }).Plotly;
  if (plotDiv && PlotlyGlobal) {
    PlotlyGlobal.downloadImage(plotDiv, {
      format: "png",
      width: 1200,
      height: 800,
      filename: `${props.nodeLabel.replace(/\s+/g, "_")}_output`,
    });
  }
}
</script>

<style scoped>
.quick-plot-modal :deep(.p-dialog-content) {
  padding: 0;
  background: #0f172a;
}

.plot-container {
  display: flex;
  flex-direction: column;
  height: 70vh;
  min-height: 500px;
}

.plot-controls {
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

.plot-type-dropdown {
  min-width: 140px;
}

.mcr-mode-dropdown,
.pca-axis-dropdown,
.generic-mode-dropdown,
.feature-axis-dropdown {
  min-width: 160px;
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

.plotly-container {
  flex: 1;
  padding: 16px;
  overflow: auto;
}

.plotly-container :deep(.js-plotly-plot) {
  width: 100%;
  height: 100%;
}

.empty-plot {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
}

.empty-plot i {
  font-size: 3rem;
  margin-bottom: 16px;
  color: #475569;
}

.empty-plot p {
  font-size: 1.1rem;
  margin: 0 0 8px;
}

.empty-plot small {
  font-size: 0.85rem;
  color: #475569;
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

/* View toggle button */
.view-toggle {
  margin-left: 8px;
}

/* Data table container (DRY with NodeDetailView) */
.data-table-container {
  flex: 1;
  padding: 16px;
  overflow: auto;
  background: #0f172a;
}

.preview-datatable {
  font-size: 0.85rem;
}

:deep(.preview-datatable .p-datatable-header) {
  background: #1e293b;
  border-color: #334155;
}

:deep(.preview-datatable .p-datatable-thead > tr > th) {
  background: #1e293b;
  color: #f8fafc;
  border-color: #334155;
  font-weight: 600;
  padding: 8px 12px;
}

:deep(.preview-datatable .p-datatable-tbody > tr) {
  background: #0f172a;
  color: #e2e8f0;
}

:deep(.preview-datatable .p-datatable-tbody > tr > td) {
  border-color: #334155;
  padding: 6px 12px;
}

:deep(.preview-datatable .p-datatable-tbody > tr:nth-child(even)) {
  background: #1e293b;
}

:deep(.preview-datatable .p-datatable-tbody > tr:hover) {
  background: #334155;
}
</style>
