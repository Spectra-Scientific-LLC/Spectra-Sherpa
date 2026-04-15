<template>
  <div class="node-detail-view">
    <!-- Header -->
    <header class="detail-header">
      <div class="header-left">
        <span class="node-icon">{{ nodeIcon }}</span>
        <div class="header-info">
          <h1>{{ nodeLabel }}</h1>
          <span class="node-type-badge">{{ nodeType }}</span>
        </div>
      </div>
      <div class="header-actions">
        <Button
          label="Run Trial"
          icon="pi pi-play"
          class="p-button-success"
          :loading="isExecuting"
          :disabled="hasValidationErrors"
          @click="handleRunTrial"
          :title="hasValidationErrors ? 'Fix validation errors before running' : 'Run trial execution with current parameters'"
        />
        <Button
          label="Cancel"
          icon="pi pi-times"
          class="p-button-text p-button-secondary"
          @click="handleCancel"
        />
        <Button
          label="Save and Exit"
          icon="pi pi-check"
          class="p-button-primary"
          @click="handleSaveAndExit"
        />
      </div>
    </header>

    <!-- Main Content -->
    <main class="detail-content">
      <!-- Input Section -->
      <InputPanel
        :expanded="sections.input"
        :has-input="hasInput"
        :input-summary="inputSummary"
        :input-data="inputData"
        :input-connections="inputConnections"
        :input-preview="inputPreview"
        :input-data-summary="inputDataSummary"
        :input-preview-columns="inputPreviewColumns"
        @toggle="toggleSection('input')"
      />

      <!-- Settings Section -->
      <SettingsPanel
        :expanded="sections.settings"
        :settings-count="settingsCount"
        :params="nodeParams"
        :local-params="localParams"
        :has-validation-errors="hasValidationErrors"
        :displayed-validation-errors="displayedValidationErrors"
        :get-param-error="getParamError"
        @toggle="toggleSection('settings')"
        @reset="resetToDefaults"
        @update-param="(name, v) => (localParams[name] = v)"
      />

      <!-- Output Section -->
      <OutputPanel
        :expanded="sections.output"
        @toggle="toggleSection('output')"
        @toggle-sub="toggleOutputSubsection"
        @show-full-metadata="showFullMetadata = true"
        @open-data-table="openDataTable"
        @open-quick-plot="openQuickPlot"
        @export-output="exportOutput"
      />

      <!-- Plots Section -->
      <PlotsPanel
        :expanded="sections.plots"
        @toggle="toggleSection('plots')"
        @toggle-plot="togglePlot"
        @contour-click="handleContourClick"
      />

      <!-- Log Section -->
      <LogPanel
        :logs="executionLogs"
        :expanded="sections.log"
        :get-log-icon="getLogIcon"
        @toggle="toggleSection('log')"
        @clear="clearLogs"
      />
    </main>

    <!-- Modals -->
    <QuickPlotModal
      v-model="showQuickPlotModal"
      :nodeOutput="nodeOutput"
      :nodeType="nodeType"
      :nodeLabel="nodeLabel"
      :nodeInput="inputData"
    />
    <DataTableModal
      v-model="showDataTableModal"
      :nodeOutput="nodeOutput"
      :nodeType="nodeType"
      :nodeLabel="nodeLabel"
    />

    <!-- Full Metadata Modal -->
    <Dialog
      v-model:visible="showFullMetadata"
      header="Full Metadata (JSON)"
      :style="{ width: '720px', maxHeight: '80vh' }"
      :modal="true"
      class="full-metadata-dialog"
    >
      <pre class="full-metadata-json">{{ fullMetadataJson }}</pre>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- node outputs and plot payloads vary widely across node families in this inspection view. */
import { ref, computed, watch, onMounted, provide } from "vue";
import {
  NODE_DETAIL_STATE_KEY,
  type NodeDetailState,
} from "./node-detail/state/useNodeDetailState";
import { useRoute } from "vue-router";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import { useToast } from "primevue/usetoast";
import QuickPlotModal from "./modals/QuickPlotModal.vue";
import DataTableModal from "./modals/DataTableModal.vue";
import { useWorkflowStore } from "@/stores/workflow";
import { createCategoryColorMap } from "@/utils/colors";
import { getYAxisLabel } from "@/utils/plotLabels";
import {
  compactSampleLabel,
  detectLabelDelimiter,
  normalizeSampleLabel,
  splitLabelByDelimiter,
} from "@/utils/sampleLabels";
import { useNodeLog } from "./node-detail/composables/useNodeLog";
import { useNodeValidation } from "./node-detail/composables/useNodeValidation";
import { useNodeOutput } from "./node-detail/composables/useNodeOutput";
import { useNodeOutputData } from "./node-detail/composables/useNodeOutputData";
import { useNodeSections } from "./node-detail/composables/useNodeSections";
import { useNodeTrial, STORAGE_KEY } from "./node-detail/composables/useNodeTrial";
import LogPanel from "./node-detail/panels/LogPanel.vue";
import InputPanel from "./node-detail/panels/InputPanel.vue";
import SettingsPanel from "./node-detail/panels/SettingsPanel.vue";
import OutputPanel from "./node-detail/panels/OutputPanel.vue";
import PlotsPanel from "./node-detail/panels/PlotsPanel.vue";


const route = useRoute();
const toast = useToast();

// Trial execution + cross-tab broadcast — extracted to composable.
// (STORAGE_KEY / BROADCAST_CHANNEL_NAME re-exported from the composable module.)

// Section collapse state — extracted to composable
const {
  sections,
  outputSubsections,
  plotSections,
  toggleSection,
  toggleOutputSubsection,
  togglePlot,
} = useNodeSections();

// Execution log entries — extracted to composable
const { executionLogs, addLog, clearLogs, getLogIcon } = useNodeLog();
const previewRowLimit = 50;

// PLS-DA loadings view mode (lines or biplot)
const plsdaLoadingsViewMode = ref<"lines" | "biplot">("lines");

// Regression correlation plot target selector
const regressionTargetIdx = ref(0);

// Modal state
const showQuickPlotModal = ref(false);
const showDataTableModal = ref(false);
const showFullMetadata = ref(false);

// Node data loaded from session storage
const nodeData = ref<any>(null);
const localParams = ref<Record<string, any>>({});
const originalParams = ref<Record<string, any>>({});

const workflowStore = useWorkflowStore();

// Node icon mapping
const NODE_ICONS: Record<string, string> = {
  "data.source": "📊",
  "preprocess.normalize": "📏",
  "preprocess.scale": "📏",
  "baseline.penalized_ls": "📉",
  "preprocess.smooth": "〰️",
  "model.pca": "🔀",
  "model.pls": "📈",
  "model.mcr_als": "🧩",
  "stats.summary": "📊",
  "output.plot": "📈",
  "output.contour": "🗺️",
  "output.export": "💾",
};

// Computed properties
const nodeId = computed(() => route.params.nodeId as string);
const nodeType = computed(() => nodeData.value?.type || "Unknown");
const nodeTypeKey = computed(() => nodeType.value);

// Parameter validation — extracted to composable
const {
  displayedValidationErrors,
  hasValidationErrors,
  validateParams,
  getParamError,
} = useNodeValidation(workflowStore, nodeType, localParams);

watch(localParams, () => validateParams(), { deep: true });
watch(
  () => workflowStore.isLoadingNodeLibrary,
  (isLoading) => {
    if (!isLoading && workflowStore.nodeLibrary.size > 0) {
      validateParams();
    }
  },
);
const isDataNode = computed(() => nodeType.value.startsWith("data."));

// Detect if data is spectral (vs generic like Iris dataset)
const isSpectraData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};

  // Use explicit flag if available
  if (metadata.is_spectra !== undefined) {
    return metadata.is_spectra;
  }

  // Check data_type if available
  if (metadata.data_type === "spectra") return true;
  if (metadata.data_type === "generic") return false;

  // Fallback: check if x_title contains spectral keywords
  const xTitle = (metadata.x_title || "").toLowerCase();
  const spectralKeywords = ['wavenumber', 'wavelength', 'raman', 'cm-1', 'cm⁻¹', 'nm', 'shift', 'frequency'];
  return spectralKeywords.some(kw => xTitle.includes(kw));
});

// Detect if data is time-series (kinetic / evolving)
// Detect if this is a generic dataset (like Iris) with feature names
const isGenericDataNode = computed(() => {
  if (!isDataNode.value) return false;
  const metadata = nodeOutput.value?.metadata || {};
  const hasFeatureNames = metadata.feature_names && metadata.feature_names.length > 0;
  return !isSpectraData.value && hasFeatureNames;
});

const nodeLabel = computed(() => nodeData.value?.label || `Node ${nodeId.value}`);
const nodeIcon = computed(() => NODE_ICONS[nodeType.value] || "📦");
const nodeMetadata = computed(() => workflowStore.getNodeMetadata(nodeType.value));
const mapMetadataParams = (_nodeType: string, parameters: any[]): any[] => {
  return parameters.map((param) => {
    return {
      name: param.name,
      label: param.label,
      type: param.param_type,
      min: param.min_value,
      max: param.max_value,
      step: param.step,
      options: param.options?.map((opt: any) => typeof opt === 'string' ? { label: opt, value: opt } : opt),
      description: param.description,
      default: param.default,
      required: param.required,
      visible_when: param.visible_when || null,
    };
  });
};

/** Check if a parameter should be visible based on visible_when rules. */
const isParamVisible = (param: any): boolean => {
  if (!param.visible_when) return true;
  for (const [controlParam, allowedValues] of Object.entries(param.visible_when)) {
    const currentValue = String(localParams.value[controlParam] ?? '');
    if (!(allowedValues as string[]).includes(currentValue)) return false;
  }
  return true;
};

const nodeParams = computed(() => {
  let params: any[];
  if (nodeMetadata.value?.parameters?.length) {
    params = mapMetadataParams(nodeType.value, nodeMetadata.value.parameters);
  } else {
    params = nodeData.value?.paramDefinitions || [];
  }
  return params.filter(isParamVisible);
});
const nodeOutput = computed(() => nodeData.value?.output || null);

// Output-panel data + helpers extracted to composable (issue #26 phase 2a).
const {
  hasInput,
  hasOutput,
  inputSummary,
  outputSummary,
  inputConnections,
  inputData,
  outputData,
  outputMetadata,
  datasetInfo,
  datasetLabelTable,
  labelPreviewLimit,
  processingHistory,
  provenanceInfo,
  qualitySummary,
  isRegressionNode,
  portSummaries,
  fullMetadataJson,
  getMetaTooltip,
  formatMetaValue,
} = useNodeOutputData({ nodeOutput, nodeData, nodeTypeKey });

const settingsCount = computed(() => nodeParams.value.length);

const { normalizeNodeOutput, resolvePortPayload, primaryOutputPayload } = useNodeOutput(
  nodeOutput,
  nodeMetadata,
);

const isPCAOutput = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return nodeTypeKey.value === "model.pca" || metadata.type === "model.pca" || metadata.isPCA === true;
});

const pcaSampleLabels = computed<string[]>(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const candidates = [
    metadata.sample_labels,
    metadata.labels,
    primaryOutputPayload.value?.y_axis?.labels,
  ];

  for (const raw of candidates) {
    if (Array.isArray(raw) && raw.length > 0) {
      return raw.map((item) => normalizeSampleLabel(item));
    }
  }

  return [];
});

const pcaLabelCategories = computed<string[]>(() => {
  const labels = pcaSampleLabels.value;
  if (labels.length === 0) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const labelSet = new Set(labels);

  const rawCategories = Array.isArray(metadata.label_categories)
    ? metadata.label_categories.map((item: any) => normalizeSampleLabel(item))
    : [];

  let categories = rawCategories.filter((category: string) => labelSet.has(category));
  if (categories.length === 0) {
    categories = Array.from(labelSet);
  }
  return Array.from(new Set(categories));
});

const pcaUseCategorical = computed(() => {
  const labels = pcaSampleLabels.value;
  const categories = pcaLabelCategories.value;
  if (labels.length === 0 || categories.length < 2) return false;
  // Avoid one-trace-per-sample views (noisy and frequently unreadable).
  if (categories.length >= labels.length) return false;
  return categories.length <= 20;
});


// Preview data for tables
const inputPreview = computed(() => {
  const data = nodeData.value?.inputData?.data;
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

const inputDataSummary = computed(() => {
  const data = nodeData.value?.inputData?.data;
  if (!data || !Array.isArray(data)) return "";
  const totalRows = data.length;
  const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const inputPreviewColumns = computed(() => {
  if (!inputPreview.value.length) return [];
  const first = inputPreview.value[0];
  const metadata = nodeData.value?.inputData?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const xTitle = metadata.x_title || "";

  return Object.keys(first).map((key) => {
    let header = key;
    if (key === "_index") {
      header = "#";
    } else if (key.startsWith("col_")) {
      const colIdx = parseInt(key.replace("col_", ""));
      if (featureNames.length > colIdx) {
        header = featureNames[colIdx];
      } else if (xTitle && xTitle !== "Feature") {
        header = `${xTitle} ${colIdx + 1}`;
      } else {
        header = `Col ${colIdx + 1}`;
      }
    }
    return { field: key, header };
  });
});

const outputPreview = computed(() => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const labelsRaw = metadata.sample_labels || metadata.labels || [];
  const labels = Array.isArray(labelsRaw)
    ? labelsRaw.map((label: any) => normalizeSampleLabel(label))
    : [];
  const labelDelimiter = detectLabelDelimiter(labels);
  const splitLabels = labelDelimiter
    ? labels.map((label: string) => splitLabelByDelimiter(label, labelDelimiter))
    : [];
  const maxLabelParts = splitLabels.length > 0
    ? Math.max(...splitLabels.map((parts: string[]) => parts.length))
    : 0;
  const useSplitLabelColumns = !!labelDelimiter && maxLabelParts > 1;

  return data.slice(0, previewRowLimit).map((row: any, i: number) => {
    const obj: any = { _index: i + 1 };
    const fullLabel = labels[i] || "";
    obj._label_full = fullLabel;

    if (labels.length > 0) {
      if (useSplitLabelColumns) {
        const parts = splitLabels[i] || [];
        for (let labelIdx = 0; labelIdx < maxLabelParts; labelIdx += 1) {
          const value = parts[labelIdx] || "";
          obj[`_label_${labelIdx}`] = compactSampleLabel(value, {
            maxLength: 42,
            headLength: 28,
            tailLength: 12,
          });
        }
      } else {
        obj._label = compactSampleLabel(fullLabel, {
          maxLength: 52,
          headLength: 34,
          tailLength: 14,
        });
      }
    }

    if (Array.isArray(row)) {
      row.slice(0, 10).forEach((val: any, j: number) => {
        obj[`col_${j}`] = typeof val === "number" ? val.toFixed(4) : val;
      });
    } else if (typeof row === "object" && row !== null) {
      // Dict rows (e.g. PeakFinding stats output)
      for (const [k, v] of Object.entries(row)) {
        obj[k] = typeof v === "number" ? Number(v).toFixed(4) : v;
      }
    } else {
      obj.value = typeof row === "number" ? row.toFixed(4) : row;
    }
    return obj;
  });
});

const outputPreviewColumns = computed(() => {
  if (!outputPreview.value.length) return [];
  const first = outputPreview.value[0] as Record<string, any>;
  const metadata = nodeOutput.value?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const mcrLabels = metadata.labels || [];
  const featureNames = metadata.feature_names || [];
  const columnNames: string[] = Array.isArray(metadata.column_names) ? metadata.column_names : [];
  const xTitle = metadata.x_title || "";
  const isPCA = metadata.type === "model.pca" || metadata.isPCA;
  const isMCR = metadata.type === "model.mcr_als";

  return Object.keys(first)
    .filter((key) => key !== "_label_full")
    .map((key) => {
    let header = key;
    if (key === "_index") {
      header = "#";
    } else if (key === "_label") {
      header = "Label";
    } else if (key.startsWith("_label_")) {
      const labelIdx = Number.parseInt(key.replace("_label_", ""), 10);
      header = Number.isNaN(labelIdx) ? "Label" : `Field ${labelIdx + 1}`;
    } else if (key.startsWith("col_")) {
      const colIdx = parseInt(key.replace("col_", ""));
      if (columnNames.length > colIdx) {
        header = columnNames[colIdx];
      } else if (isPCA && pcLabels[colIdx]) {
        header = pcLabels[colIdx];
      } else if (isMCR && mcrLabels[colIdx]) {
        header = mcrLabels[colIdx];
      } else if (featureNames.length > colIdx) {
        header = featureNames[colIdx];
      } else if (xTitle && xTitle !== "Feature") {
        header = `${xTitle} ${colIdx + 1}`;
      } else {
        header = `Col ${colIdx + 1}`;
      }
    }
    return { field: key, header };
  });
});

const outputDataSummary = computed(() => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return "";
  const totalRows = data.length;
  const totalCols = Array.isArray(data[0]) ? data[0].length : 1;
  const shownRows = Math.min(totalRows, previewRowLimit);
  const shownCols = Math.min(totalCols, 10);
  let summary = `${shownRows} of ${totalRows} rows`;
  if (totalCols > 10) summary += `, ${shownCols} of ${totalCols} columns`;
  return summary;
});

const pcaDiagnosticsPreview = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const rowCount = Math.max(t2.length, spe.length);
  if (rowCount === 0) return [];

  const rows = [];
  const limit = Math.min(rowCount, previewRowLimit);
  for (let i = 0; i < limit; i += 1) {
    rows.push({
      sample: i + 1,
      t2: typeof t2[i] === "number" ? t2[i].toFixed(4) : "",
      spe: typeof spe[i] === "number" ? spe[i].toFixed(6) : "",
    });
  }
  return rows;
});

const pcaDiagSummary = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return "";
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const totalRows = Math.max(t2.length, spe.length);
  const shownRows = Math.min(totalRows, previewRowLimit);
  return `${shownRows} of ${totalRows} rows`;
});

const pcaDiagnosticsColumns = computed(() => ([
  { field: "sample", header: "Sample" },
  { field: "t2", header: "T²" },
  { field: "spe", header: "SPE (Q)" },
]));

// ============================================================================
// PLOTS SECTION - State and Computed Properties
// ============================================================================

// PCA axis selection
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);

// Spectra display mode
const spectraDisplayMode = ref<"overlay" | "contour">("contour");
const spectraDisplayOptions = [
  { label: "Overlay", value: "overlay" },
  { label: "Contour (Interactive)", value: "contour" },
];

// Generic data display mode (for non-spectral datasets like Iris)
const genericDisplayMode = ref<"boxplot" | "scatter">("boxplot");
const genericDisplayOptions = [
  { label: "Box Plot (by Label)", value: "boxplot" },
  { label: "Feature Scatter", value: "scatter" },
];

// Feature selection for scatter plot
const featureXAxis = ref(0);
const featureYAxis = ref(1);

// Available features for scatter plot axis selection
const featureOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  if (featureNames.length === 0) return [];
  return featureNames.map((name: string, i: number) => ({ label: name, value: i }));
});

// Contour click point for slicing
const contourClickPoint = ref<{ sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null>(null);

// Check if node is a preprocessing type
const isPreprocessingNode = computed(() => {
  const nt = nodeType.value;
  return (
    nt.startsWith("normalize.") ||
    nt.startsWith("baseline.") ||
    nt.startsWith("smooth.") ||
    nt.startsWith("derivative.") ||
    nt.startsWith("preprocess.")
  );
});

// Available plots based on node type
const availablePlots = computed(() => {
  const plots: string[] = [];
  if (isPCAOutput.value) {
    plots.push("Scores Plot", "Biplot", "Loadings Plot", "Scree Plot", "Diagnostics Plot");
    return plots;
  }
  switch (nodeTypeKey.value) {
    case "model.mcr_als":
    case "model.simplisma":
      plots.push("Concentration Profiles", "Pure Spectra");
      break;
    case "model.efa":
      plots.push("Eigenvalue Plot");
      break;
    case "model.pls":
      plots.push("Scores Plot", "Loadings Plot", "Predicted vs Actual");
      break;
    case "model.pcr":
    case "model.svr":
      plots.push("Predicted vs Actual");
      break;
    case "classification.plsda":
      plots.push("Scores Plot (with confidence ellipses)", "Loadings Plot", "VIP Scores", "Class Accuracy");
      break;
    case "classification.simca":
      plots.push("Scores Plot", "Confusion Matrix", "Per-Class Accuracy");
      break;
    case "classification.knn":
      plots.push("Feature Space Plot", "K-Optimization", "Confusion Matrix", "Per-Class Accuracy");
      break;
    case "diagnostics.outliers":
      plots.push("T² vs Q Control Chart");
      break;
    case "diagnostics.holdout_evaluation":
      plots.push("Evaluation Results");
      break;
    case "diagnostics.cross_validation":
      plots.push("Evaluation Results");
      break;
    case "model.kmeans":
    case "model.dbscan":
      plots.push("Cluster Scatter");
      break;
    case "model.nmf":
    case "model.ica":
      plots.push("Concentration Profiles", "Pure Spectra");
      break;
    case "model.hca":
      plots.push("Dendrogram");
      break;
    case "stats.summary":
      plots.push("Summary Plot");
      break;
    case "analysis.peak_finding":
      plots.push("Spectra with Peaks");
      break;
    case "output.plot":
    case "output.contour":
      plots.push("Visualization");
      break;
    case "data.source":
    case "preprocess.normalize":
    case "preprocess.scale":
    case "preprocess.clip_range":
    case "preprocess.cosmic_ray":
    case "baseline.penalized_ls":
    case "baseline.rubberband":
    case "preprocess.smooth":
      // Show appropriate overview based on data type
      if (isGenericDataNode.value) {
        plots.push("Data Overview");
      } else if (isSpectraData.value) {
        plots.push("Spectra Overview");
      } else {
        plots.push("Data Overview"); // Default to Data Overview for unknown types
      }
      break;
  }
  if (plots.length === 0 && (isDataNode.value || isPreprocessingNode.value)) {
    if (isGenericDataNode.value) {
      plots.push("Data Overview");
    } else if (isSpectraData.value) {
      plots.push("Spectra Overview");
    } else {
      plots.push("Data Overview");
    }
  }
  return plots;
});

// Base plot layout for dark theme
const basePlotLayout = {
  autosize: true,
  paper_bgcolor: "#1e293b",
  plot_bgcolor: "#0f172a",
  font: { color: "#f8fafc", size: 12 },
  margin: { t: 40, r: 20, b: 50, l: 60 },
  xaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
  yaxis: { gridcolor: "#334155", zerolinecolor: "#475569" },
};

// ============================================================================
// Dynamic Axis Labels (using shared utilities from @/utils/plotLabels)
// ============================================================================

/**
 * Compute Y-axis label from metadata using shared utility.
 * Never uses "a.u." - falls back to ML terms ("Response").
 */
const yAxisLabel = computed(() => getYAxisLabel(nodeOutput.value?.metadata));

/**
 * Compute X-axis label from metadata using shared utility.
 * Never uses "a.u." - falls back to ML terms ("Feature").
 */
// Watch for changes in PCA component count and clamp axis indices
watch(
  () => nodeOutput.value?.metadata?.n_components,
  (n_components) => {
    if (isPCAOutput.value && typeof n_components === "number") {
      const maxIndex = Math.max(0, n_components - 1);
      // Clamp X axis
      if (pcaXAxis.value > maxIndex) {
        pcaXAxis.value = Math.min(pcaXAxis.value, maxIndex);
      }
      // Clamp Y axis, ensuring it's different from X axis if possible
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

// ============================================================================
// PCA Plots
// ============================================================================

/**
 * Derive PC axis labels from explained_variance_ratio.
 * Falls back to metadata.pc_labels for backwards compat with old node outputs.
 */
const pcLabels = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  // Backwards compat: use pre-computed pc_labels if available
  if (metadata.pc_labels?.length) return metadata.pc_labels;
  // Derive from explained_variance_ratio
  const evr = metadata.explained_variance_ratio || [];
  if (!evr.length) return [];
  const yTitle = metadata.y_title;
  const suffix = yTitle && yTitle !== "Response" ? ` [${yTitle}]` : "";
  return evr.map((v: number, i: number) => {
    const pct = v > 1 ? v : v * 100;
    return `PC${i + 1} (${pct.toFixed(1)}%)${suffix}`;
  });
});

const pcaAxisOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const labels = pcLabels.value;
  const n = labels.length || metadata.n_components || 5;
  return Array.from({ length: n }, (_, i) => ({
    label: labels[i] || `PC${i + 1}`,
    value: i,
  }));
});

const pcaScoresData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const scores = nodeOutput.value?.data || [];
  if (!scores.length) return [];

  const labels = pcaSampleLabels.value.length === scores.length
    ? pcaSampleLabels.value
    : Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const axisLabels = pcLabels.value;  // Use computed pcLabels
  const labelCategories = pcaLabelCategories.value;

  // Determine if we should use categorical coloring
  const useCategorical = pcaUseCategorical.value;

  if (useCategorical) {
    // Multiple traces, one per category
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];

    // Group points by category
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
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
          hovertemplate: `%{text}<br>${axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`}: %{x:.3f}<br>${axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });

    if (traces.length > 0) {
      return traces;
    }
  }
  // Fallback: Single trace with default blue color
  const x = scores.map((row: number[]) => row[pcaXAxis.value]);
  const y = scores.map((row: number[]) => row[pcaYAxis.value]);

  return [{
    type: "scatter",
    mode: "markers",
    x, y,
    text: labels,
    marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
    hovertemplate: `%{text}<br>${axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`}: %{x:.3f}<br>${axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
  }];
});

const pcaScoresLayout = computed(() => {
  const axisLabels = pcLabels.value;  // Use computed pcLabels
  const hasCategorical = pcaUseCategorical.value;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}` },
  };

  // Ensure legend is properly configured when categorical
  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

const pcaScoresConfig = computed(() => ({
  editable: true,
  edits: { legendPosition: true },
}));

const pcaBiplotData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];

  const scores = nodeOutput.value?.data || [];
  if (!Array.isArray(scores) || scores.length === 0) return [];

  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];

  // Fallback to scores-only plot when loadings are unavailable.
  if (!Array.isArray(loadings) || loadings.length === 0) {
    return pcaScoresData.value;
  }

  const maxLoadingPcIndex = loadings.length - 1;
  const pcX = Math.max(0, Math.min(pcaXAxis.value, maxLoadingPcIndex));
  const pcY = Math.max(0, Math.min(pcaYAxis.value, maxLoadingPcIndex));

  const loadingXRaw = Array.isArray(loadings[pcX]) ? loadings[pcX] : [];
  const loadingYRaw = Array.isArray(loadings[pcY]) ? loadings[pcY] : [];
  if (!loadingXRaw.length || !loadingYRaw.length) {
    return pcaScoresData.value;
  }

  const nFeatures = Math.min(loadingXRaw.length, loadingYRaw.length);
  const axisLabels = pcLabels.value;
  const pcXLabel = axisLabels[pcX] || `PC${pcX + 1}`;
  const pcYLabel = axisLabels[pcY] || `PC${pcY + 1}`;

  const sampleLabels = pcaSampleLabels.value.length === scores.length
    ? pcaSampleLabels.value
    : Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = pcaLabelCategories.value;
  const useCategorical = pcaUseCategorical.value;

  const sampleTraces: any[] = [];
  if (useCategorical) {
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);
    const categoryGroups = new Map<string | number, { x: number[]; y: number[]; labels: string[] }>();
    labelCategories.forEach((category: string | number) => {
      categoryGroups.set(category, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = sampleLabels[idx];
      const group = categoryGroups.get(category);
      if (group && Array.isArray(row) && row.length > Math.max(pcX, pcY)) {
        group.x.push(Number(row[pcX]));
        group.y.push(Number(row[pcY]));
        group.labels.push(String(sampleLabels[idx]));
      }
    });

    labelCategories.forEach((category: string | number) => {
      const group = categoryGroups.get(category);
      if (!group || group.x.length === 0) return;
      sampleTraces.push({
        type: "scatter",
        mode: "markers",
        x: group.x,
        y: group.y,
        text: group.labels,
        name: String(category),
        marker: {
          size: 9,
          color: colorMap.get(category),
          opacity: 0.78,
          line: { width: 1, color: "rgba(15, 23, 42, 0.55)" },
        },
        hovertemplate: `%{text}<br>${pcXLabel}: %{x:.3f}<br>${pcYLabel}: %{y:.3f}<extra></extra>`,
      });
    });
  } else {
    const pairedPoints = scores
      .map((row: number[], idx: number) => ({
        x: Number(row?.[pcX]),
        y: Number(row?.[pcY]),
        label: sampleLabels[idx],
      }))
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));

    sampleTraces.push({
      type: "scatter",
      mode: "markers",
      x: pairedPoints.map((point) => point.x),
      y: pairedPoints.map((point) => point.y),
      text: pairedPoints.map((point) => point.label),
      name: "Samples",
      marker: {
        size: 9,
        color: "#60a5fa",
        opacity: 0.8,
        line: { width: 1, color: "#1d4ed8" },
      },
      hovertemplate: `%{text}<br>${pcXLabel}: %{x:.3f}<br>${pcYLabel}: %{y:.3f}<extra></extra>`,
    });
  }

  // Build feature labels for loading vectors.
  const featureNames = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;
  const featureLabels = Array.from({ length: nFeatures }, (_, idx) => {
    if (Array.isArray(featureNames) && featureNames.length === nFeatures) {
      return String(featureNames[idx]);
    }
    if (Array.isArray(wavenumbers) && wavenumbers.length === nFeatures) {
      const w = Number(wavenumbers[idx]);
      return Number.isFinite(w) ? `${w.toFixed(0)}` : String(wavenumbers[idx]);
    }
    return `F${idx + 1}`;
  });

  // Keep biplot readable on high-dimensional data:
  // draw strongest vectors and label the strongest subset.
  const vectors = Array.from({ length: nFeatures }, (_, idx) => {
    const lx = Number(loadingXRaw[idx]);
    const ly = Number(loadingYRaw[idx]);
    return {
      idx,
      lx,
      ly,
      label: featureLabels[idx],
      norm: Math.hypot(lx, ly),
    };
  }).filter((row) => Number.isFinite(row.lx) && Number.isFinite(row.ly));

  if (vectors.length === 0) {
    return sampleTraces;
  }

  vectors.sort((a, b) => b.norm - a.norm);
  const maxVectors = Math.min(80, vectors.length);
  const selectedVectors = vectors.slice(0, maxVectors);
  const labeledCount = Math.min(24, selectedVectors.length);
  const labeledFeatures = new Set(selectedVectors.slice(0, labeledCount).map((row) => row.idx));

  const scoreXValues = scores
    .map((row: number[]) => Number(row?.[pcX]))
    .filter((value: number) => Number.isFinite(value));
  const scoreYValues = scores
    .map((row: number[]) => Number(row?.[pcY]))
    .filter((value: number) => Number.isFinite(value));

  const maxScoreX = Math.max(1e-12, ...scoreXValues.map((value: number) => Math.abs(value)));
  const maxScoreY = Math.max(1e-12, ...scoreYValues.map((value: number) => Math.abs(value)));
  const maxLoadX = Math.max(1e-12, ...selectedVectors.map((row) => Math.abs(row.lx)));
  const maxLoadY = Math.max(1e-12, ...selectedVectors.map((row) => Math.abs(row.ly)));
  const loadingScale = 0.82 * Math.min(maxScoreX / maxLoadX, maxScoreY / maxLoadY);

  const vectorLineX: Array<number | null> = [];
  const vectorLineY: Array<number | null> = [];
  const vectorEndX: number[] = [];
  const vectorEndY: number[] = [];
  const vectorText: string[] = [];
  const vectorCustomData: Array<[string, number, number, number]> = [];

  selectedVectors.forEach((row) => {
    const scaledX = row.lx * loadingScale;
    const scaledY = row.ly * loadingScale;

    vectorLineX.push(0, scaledX, null);
    vectorLineY.push(0, scaledY, null);
    vectorEndX.push(scaledX);
    vectorEndY.push(scaledY);
    vectorText.push(labeledFeatures.has(row.idx) ? row.label : "");
    vectorCustomData.push([row.label, row.lx, row.ly, row.norm]);
  });

  const loadingLineTrace = {
    type: "scatter",
    mode: "lines",
    x: vectorLineX,
    y: vectorLineY,
    name: "Loadings vectors",
    line: { color: "#f59e0b", width: 1.6 },
    hoverinfo: "skip",
    showlegend: true,
  };

  const loadingMarkerTrace = {
    type: "scatter",
    mode: "markers+text",
    x: vectorEndX,
    y: vectorEndY,
    text: vectorText,
    textposition: "top center",
    textfont: { size: 10, color: "#fde68a" },
    customdata: vectorCustomData,
    marker: {
      size: 6,
      color: "#f97316",
      opacity: 0.92,
      line: { width: 1, color: "#7c2d12" },
    },
    name: "Variables",
    showlegend: false,
    hovertemplate:
      `<b>%{customdata[0]}</b><br>${pcXLabel} loading: %{customdata[1]:.3f}` +
      `<br>${pcYLabel} loading: %{customdata[2]:.3f}` +
      `<br>Vector norm: %{customdata[3]:.3f}<extra></extra>`,
  };

  return [...sampleTraces, loadingLineTrace, loadingMarkerTrace];
});

const pcaBiplotLayout = computed(() => {
  const axisLabels = pcLabels.value;
  const pcXLabel = axisLabels[pcaXAxis.value] || `PC${pcaXAxis.value + 1}`;
  const pcYLabel = axisLabels[pcaYAxis.value] || `PC${pcaYAxis.value + 1}`;
  const hasCategorical = pcaUseCategorical.value;

  return {
    ...basePlotLayout,
    height: 460,
    showlegend: true,
    legend: {
      bgcolor: "rgba(30, 41, 59, 0.82)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
      orientation: hasCategorical ? "v" : "h",
    },
    xaxis: {
      ...basePlotLayout.xaxis,
      title: `${pcXLabel} (scores)`,
      zeroline: true,
      zerolinecolor: "#64748b",
      zerolinewidth: 1.2,
    },
    yaxis: {
      ...basePlotLayout.yaxis,
      title: `${pcYLabel} (scores)`,
      zeroline: true,
      zerolinecolor: "#64748b",
      zerolinewidth: 1.2,
    },
    annotations: [
      {
        xref: "paper",
        yref: "paper",
        x: 0,
        y: 1.08,
        showarrow: false,
        text: "Loading vectors are scaled to score-space for interpretation.",
        font: { size: 11, color: "#cbd5e1" },
      },
    ],
    hovermode: "closest",
  };
});

const pcaLoadingsData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];

  // Read loadings from port (new architecture) or metadata (backwards compat)
  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];
  if (!loadings.length) return [];

  // Wavenumbers/features: prefer loadings port x_axis (has actual wavenumbers), then metadata
  const portWavenumbers = loadingsPayload?.x_axis?.data;
  const feature_names = metadata.feature_names;
  const wavenumbers = portWavenumbers || metadata.wavenumbers;
  const axisLabels = pcLabels.value;  // Use computed pcLabels

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === loadings[0]?.length) {
    x_values = feature_names;
  } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
    x_values = wavenumbers;
  } else {
    x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
  }

  return loadings.map((loading: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: x_values,
    y: loading,
    name: axisLabels[i] || `PC${i + 1}`,
    line: { width: 2 },
  }));
});

const pcaLoadingsLayout = computed(() => {
  const loadingsPort = nodeOutput.value?.ports?.loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const feature_names = metadata.feature_names;
  // Prefer loadings port x_axis metadata (has actual wavenumber title/units)
  const portXTitle = loadingsPayload?.x_axis?.title;
  const portXUnits = loadingsPayload?.x_axis?.units;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  // Determine x-axis title and orientation from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (portXTitle) {
    // Use title/units from loadings port coordinate
    xaxis_title = portXUnits ? `${portXTitle} (${portXUnits})` : portXTitle;
    xaxis_reversed = portXTitle.toLowerCase().includes("wavenumber");
  } else if (wavenumbers && wavenumbers.length > 0) {
    // Use metadata x_title/x_units (could be wavenumber, wavelength, m/z, etc.)
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "Loading" },
  };
});

const pcaLoadingsConfig = computed(() => ({
  editable: true,
  edits: { legendPosition: true },
}));

const pcaScreeData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const variance = metadata.explained_variance_ratio || [];

  // Debug: log what we're getting
  console.log('[PCA Scree] variance data:', variance, 'length:', variance.length);

  if (!variance.length) return [];

  // Detect if variance is already in percentage form (values > 1) or ratio form (0-1)
  const maxVal = Math.max(...variance);
  const isPercentage = maxVal > 1;

  // Convert to percentage if needed
  const variancePercent = isPercentage
    ? variance.map((v: number) => v)
    : variance.map((v: number) => v * 100);

  // Use simple PC labels for x-axis (not the ones with percentages)
  const xLabels = Array.from({ length: variance.length }, (_, i) => `PC${i + 1}`);

  // Bar chart for individual variance
  const bars = {
    type: "bar",
    x: xLabels,
    y: variancePercent,
    name: "Individual %",
    marker: { color: "#3b82f6" },
    hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
  };

  // Line for cumulative variance - on same y-axis for visibility
  let cumulative = 0;
  const cumulativeY = variancePercent.map((v: number) => {
    cumulative += v;
    return cumulative;
  });

  const line = {
    type: "scatter",
    mode: "lines+markers",
    x: xLabels,
    y: cumulativeY,
    name: "Cumulative %",
    line: { color: "#f97316", width: 3 },
    marker: { size: 10, color: "#f97316" },
    hovertemplate: "%{x}: %{y:.1f}% cumulative<extra></extra>",
  };

  console.log('[PCA Scree] bars y:', variancePercent, 'cumulative y:', cumulativeY);

  return [bars, line];
});

const pcaScreeLayout = computed(() => ({
  ...basePlotLayout,
  height: 350,
  showlegend: true,
  legend: {
    x: 0.5,
    xanchor: "center",
    y: 1.15,
    orientation: "h",
    bgcolor: "rgba(0,0,0,0)",
    font: { color: "#f8fafc" },
  },
  xaxis: {
    ...basePlotLayout.xaxis,
    title: { text: "Principal Component", font: { color: "#f8fafc" } },
  },
  yaxis: {
    ...basePlotLayout.yaxis,
    title: { text: "Variance (%)", font: { color: "#f8fafc" } },
    rangemode: "tozero",
    range: [0, 105],
  },
}));

const pcaDiagnosticsData = computed(() => {
  if (!isPCAOutput.value || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const t2 = Array.isArray(metadata.t2) ? metadata.t2 : [];
  const spe = Array.isArray(metadata.spe) ? metadata.spe : [];
  const rowCount = Math.max(t2.length, spe.length);
  if (rowCount === 0) return [];
  const sampleLabels = pcaSampleLabels.value.length === rowCount
    ? pcaSampleLabels.value
    : Array.from({ length: rowCount }, (_, i) => `Sample ${i + 1}`);
  const labelCategories = pcaLabelCategories.value;

  const x = Array.from({ length: rowCount }, (_, i) => i + 1);
  const traces = [];

  // Determine if we should use categorical coloring
  const useCategorical = pcaUseCategorical.value;

  if (useCategorical) {
    // Categorical coloring: one trace per category
    const colorMap = createCategoryColorMap(sampleLabels, labelCategories);

    // Group data by category
    const categoryGroups = new Map<string | number, { indices: number[], t2Values: number[], speValues: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { indices: [], t2Values: [], speValues: [], labels: [] });
    });

    x.forEach((idx: number, i: number) => {
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
            mode: "lines+markers",
            x: group.indices,
            y: group.t2Values,
            name: `T²: ${String(category)}`,
            text: group.labels,
            yaxis: "y",
            line: { color: colorMap.get(category), width: 2 },
            marker: { size: 6, color: colorMap.get(category), symbol: "circle" },
            hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
            legendgroup: String(category),
          });
        }
      });

      // Add T² control limit as separate trace
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          yaxis: "y",
          line: { color: "#64748b", width: 1, dash: "dash" },
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
            mode: "lines+markers",
            x: group.indices,
            y: group.speValues,
            name: `SPE: ${String(category)}`,
            text: group.labels,
            yaxis: "y2",
            line: { color: colorMap.get(category), width: 2 },
            marker: { size: 6, color: colorMap.get(category), symbol: "square" },
            hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
            legendgroup: String(category),
          });
        }
      });

      // Add SPE control limit as separate trace
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)",
          yaxis: "y2",
          line: { color: "#64748b", width: 1, dash: "dash" },
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
        mode: "lines+markers",
        x,
        y: t2,
        name: "T²",
        text: sampleLabels,
        yaxis: "y",
        line: { color: "#38bdf8", width: 2 },
        marker: { size: 6, color: "#38bdf8", symbol: "circle" },
        hovertemplate: "%{text}<br>T²: %{y:.4f}<extra></extra>",
      });

      // Add T² control limit
      if (typeof metadata.t2_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.t2_p95, metadata.t2_p95],
          name: "T² Limit (95%)",
          yaxis: "y",
          line: { color: "#38bdf8", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
        });
      }
    }

    if (spe.length > 0) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        x,
        y: spe,
        name: "SPE (Q)",
        text: sampleLabels,
        yaxis: "y2",
        line: { color: "#f97316", width: 2 },
        marker: { size: 6, color: "#f97316", symbol: "square" },
        hovertemplate: "%{text}<br>SPE: %{y:.6f}<extra></extra>",
      });

      // Add SPE control limit
      if (typeof metadata.spe_p95 === "number") {
        traces.push({
          type: "scatter",
          mode: "lines",
          x: [x[0], x[x.length - 1]],
          y: [metadata.spe_p95, metadata.spe_p95],
          name: "SPE Limit (95%)",
          yaxis: "y2",
          line: { color: "#f97316", width: 1, dash: "dash" },
          showlegend: true,
          hoverinfo: "skip",
        });
      }
    }
  }

  return traces;
});

const pcaDiagnosticsLayout = computed(() => {
  return {
    ...basePlotLayout,
    height: 350,
    margin: { t: 40, r: 80, b: 50, l: 60 },
    showlegend: true,
    legend: {
      x: 0.5,
      xanchor: "center",
      y: 1.15,
      orientation: "h",
      bgcolor: "rgba(0,0,0,0)",
      font: { color: "#f8fafc" },
    },
    xaxis: { ...basePlotLayout.xaxis, title: "Sample" },
    yaxis: { ...basePlotLayout.yaxis, title: "T²" },
    yaxis2: {
      overlaying: "y",
      side: "right",
      title: { text: "SPE (Q)", standoff: 20 },
      gridcolor: "rgba(0,0,0,0)",
      zerolinecolor: "#475569",
    },
  };
});

// ============================================================================
// MCR-ALS Plots
// ============================================================================

const mcrConcentrationData = computed(() => {
  if ((nodeTypeKey.value !== "model.mcr_als" && nodeTypeKey.value !== "model.simplisma") || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const labels = metadata.labels || Array.from({ length: data[0]?.length || 0 }, (_, i) => `Component ${i + 1}`);

  if (!data.length || !Array.isArray(data[0])) return [];

  const nSamples = data.length;
  const nComponents = data[0].length;
  const x = Array.from({ length: nSamples }, (_, i) => i + 1);

  return Array.from({ length: nComponents }, (_, c) => ({
    type: "scatter",
    mode: "lines",
    x,
    y: data.map((row: number[]) => row[c]),
    name: labels[c],
    line: { width: 2 },
  }));
});

const mcrConcentrationLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: metadata.y_title || "Sample Index" },
    yaxis: { ...basePlotLayout.yaxis, title: metadata.value_units_label || metadata.value_units || "Relative Concentration" },
  };
});

const mcrSpectraData = computed(() => {
  if ((nodeTypeKey.value !== "model.mcr_als" && nodeTypeKey.value !== "model.simplisma") || !hasOutput.value) return [];
  const metadata = nodeOutput.value?.metadata || {};
  const St = metadata.St || [];
  if (!St.length) return [];
  const nFeatures = St[0]?.length || 0;
  // Use spectral_wavenumbers (survives serialization) with length-check fallback.
  // metadata.wavenumbers may be component indices [0,1] from C_dataset's feature
  // axis, so only use it if its length matches the spectrum length.
  const candidates = metadata.spectral_wavenumbers || metadata.wavenumbers;
  const wavenumbers = (candidates && Array.isArray(candidates) && candidates.length === nFeatures)
    ? candidates
    : Array.from({ length: nFeatures }, (_, i) => i);
  const labels = metadata.St_labels || Array.from({ length: St.length }, (_, i) => `Component ${i + 1}`);

  return St.map((spectrum: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: wavenumbers,
    y: spectrum,
    name: labels[i],
    line: { width: 2 },
  }));
});

const mcrSpectraLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  // Use spectral_x_title/x_units (survives serialization) with fallback.
  // Only use axis info if the actual wavenumber data was resolved (not index fallback).
  const St = metadata.St || [];
  const nFeatures = St[0]?.length || 0;
  const candidates = metadata.spectral_wavenumbers || metadata.wavenumbers;
  const hasRealWavenumbers = candidates && Array.isArray(candidates) && candidates.length === nFeatures;
  const xTitle = hasRealWavenumbers ? (metadata.spectral_x_title || metadata.x_title || "") : "";
  const xUnits = hasRealWavenumbers ? (metadata.spectral_x_units || metadata.x_units || "") : "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : (xTitle || "Feature Index");
  const yLabel = yAxisLabel.value || "Response";
  // Reverse x-axis for wavenumber data (cm⁻¹), not for wavelength (nm)
  const shouldReverse = hasRealWavenumbers && (xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber"));

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: {
      ...basePlotLayout.xaxis,
      title: xLabel,
      autorange: shouldReverse ? "reversed" : true,
    },
    yaxis: { ...basePlotLayout.yaxis, title: yLabel },
  };
});

// ============================================================================
// Plot / Contour Node Visualization (server-rendered Plotly)
// ============================================================================

const plotNodeData = computed(() => {
  if (!['output.plot', 'output.contour'].includes(nodeTypeKey.value) || !hasOutput.value) return [];
  // The visualization port stores {plot_type, data, layout}.
  // After buildNodeOutput, data = plotly traces, metadata = full vis object.
  const viz: any = nodeOutput.value?.ports?.visualization?.value || nodeOutput.value?.metadata || {};
  if (Array.isArray(viz.data) && viz.data.length > 0) return viz.data;

  // Defensive fallback: if a caller hands us a raw multi-target
  // predicted-vs-actual series payload (``viz.series = [{name, actual,
  // predicted}, ...]``) without going through PlotNode._plot_predicted_vs_actual
  // first, synthesize Plotly traces here so the plot still renders.
  const series = viz.series as Array<{
    name?: string;
    actual?: number[];
    predicted?: number[];
  }> | undefined;
  if (Array.isArray(series) && series.length > 0) {
    const traces: any[] = [];
    const allActual: number[] = [];
    const allPredicted: number[] = [];
    for (const s of series) {
      const actual = Array.isArray(s.actual) ? s.actual.map(Number) : [];
      const predicted = Array.isArray(s.predicted) ? s.predicted.map(Number) : [];
      if (!actual.length || !predicted.length) continue;
      traces.push({
        x: actual,
        y: predicted,
        mode: "markers" as const,
        type: "scatter" as const,
        name: String(s.name || "Target"),
      });
      allActual.push(...actual);
      allPredicted.push(...predicted);
    }
    if (traces.length > 0) {
      const minVal = Math.min(...allActual, ...allPredicted);
      const maxVal = Math.max(...allActual, ...allPredicted);
      traces.push({
        x: [minVal, maxVal],
        y: [minVal, maxVal],
        mode: "lines" as const,
        type: "scatter" as const,
        name: "Ideal",
        line: { dash: "dash" as const, color: "#94a3b8" },
      });
      return traces;
    }
  }

  return nodeOutput.value?.data || [];
});

const plotNodeLayout = computed(() => {
  if (!['output.plot', 'output.contour'].includes(nodeTypeKey.value) || !hasOutput.value) return basePlotLayout;
  const viz = nodeOutput.value?.ports?.visualization?.value || nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    ...(viz.layout || {}),
    height: 450,
    paper_bgcolor: basePlotLayout.paper_bgcolor,
    plot_bgcolor: basePlotLayout.plot_bgcolor,
    font: basePlotLayout.font,
  };
});

// ============================================================================
// PLS Plots
// ============================================================================

const plsScoresData = computed(() => {
  if (nodeTypeKey.value !== "model.pls" || !hasOutput.value) return [];
  const scores = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  if (!scores.length) return [];

  const labels = metadata.sample_labels || Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const lvLabels = metadata.pc_labels || [];
  const labelCategories = metadata.label_categories;

  // Determine if we should use categorical coloring
  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
      }
    });

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
          hovertemplate: `%{text}<br>${lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}`}: %{x:.3f}<br>${lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });
    return traces;
  } else {
    const x = scores.map((row: number[]) => row[pcaXAxis.value]);
    const y = scores.map((row: number[]) => row[pcaYAxis.value]);
    return [{
      type: "scatter",
      mode: "markers",
      x, y,
      text: labels,
      marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
      hovertemplate: `%{text}<br>${lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}`}: %{x:.3f}<br>${lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const plsScoresLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const lvLabels = metadata.pc_labels || [];
  const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: lvLabels[pcaXAxis.value] || `LV${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: lvLabels[pcaYAxis.value] || `LV${pcaYAxis.value + 1}` },
  };

  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

const plsLoadingsData = computed(() => {
  if (nodeTypeKey.value !== "model.pls" || !hasOutput.value) return [];

  // Read loadings from port (new architecture) or metadata (backwards compat)
  const loadingsPort = nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.X_loadings || [];
  if (!loadings.length) return [];

  // Wavenumbers/features: prefer loadings port x_axis, then metadata
  const portWavenumbers = loadingsPayload?.x_axis?.data;
  const feature_names = metadata.feature_names;
  const wavenumbers = portWavenumbers || metadata.wavenumbers;
  const lvLabels = metadata.pc_labels || [];

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === loadings[0]?.length) {
    x_values = feature_names;
  } else if (wavenumbers && wavenumbers.length === loadings[0]?.length) {
    x_values = wavenumbers;
  } else {
    x_values = Array.from({ length: loadings[0]?.length || 0 }, (_, i) => i);
  }

  return loadings.map((loading: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: x_values,
    y: loading,
    name: lvLabels[i] || `LV${i + 1}`,
    line: { width: 2 },
  }));
});

const plsLoadingsLayout = computed(() => {
  const loadingsPort = nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const feature_names = metadata.feature_names;
  const portXTitle = loadingsPayload?.x_axis?.title;
  const portXUnits = loadingsPayload?.x_axis?.units;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  // Determine x-axis title and orientation from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (portXTitle) {
    xaxis_title = portXUnits ? `${portXTitle} (${portXUnits})` : portXTitle;
    xaxis_reversed = portXTitle.toLowerCase().includes("wavenumber");
  } else if (wavenumbers && wavenumbers.length > 0) {
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "Loading" },
  };
});

// ============================================================================
// Classification Plots (PLS-DA, SIMCA, KNN)
// ============================================================================

const classificationScoresData = computed(() => {
  const nodeType = nodeTypeKey.value;
  if (!["classification.plsda", "classification.simca", "classification.knn"].includes(nodeType) || !hasOutput.value) return [];

  // For PLS-DA, use pre-built scores plot if available
  if (nodeType === "classification.plsda") {
    const plots = nodeOutput.value?.plots;
    if (plots?.scores?.data) {
      return plots.scores.data;
    }
  }

  // Fallback: build scores plot from raw data
  const scores = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  if (!scores.length) return [];

  const labels = metadata.sample_labels || Array.from({ length: scores.length }, (_, i) => `Sample ${i + 1}`);
  const pcLabels = metadata.pc_labels || [];
  const labelCategories = metadata.label_categories;

  const useCategorical = labelCategories && labelCategories.length > 0 && labelCategories.length < 50;

  if (useCategorical) {
    const colorMap = createCategoryColorMap(labels, labelCategories);
    const traces: any[] = [];
    const categoryGroups = new Map<string | number, { x: number[], y: number[], labels: string[] }>();
    labelCategories.forEach((cat: any) => {
      categoryGroups.set(cat, { x: [], y: [], labels: [] });
    });

    scores.forEach((row: number[], idx: number) => {
      const category = labels[idx];
      const group = categoryGroups.get(category);
      if (group) {
        group.x.push(row[pcaXAxis.value]);
        group.y.push(row[pcaYAxis.value]);
        group.labels.push(String(labels[idx]));
      }
    });

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
          hovertemplate: `%{text}<br>${pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}`}: %{x:.3f}<br>${pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
        });
      }
    });
    return traces;
  } else {
    const x = scores.map((row: number[]) => row[pcaXAxis.value]);
    const y = scores.map((row: number[]) => row[pcaYAxis.value]);
    return [{
      type: "scatter",
      mode: "markers",
      x, y,
      text: labels,
      marker: { size: 10, color: "#3b82f6", opacity: 0.8, line: { width: 1, color: "#1e40af" } },
      hovertemplate: `%{text}<br>${pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}`}: %{x:.3f}<br>${pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}`}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const classificationScoresLayout = computed(() => {
  // For PLS-DA, use pre-built layout if available
  if (nodeTypeKey.value === "classification.plsda") {
    const plots = nodeOutput.value?.plots;
    if (plots?.scores?.layout) {
      return {
        ...basePlotLayout,
        ...plots.scores.layout,
        height: 400,
      };
    }
  }

  // Fallback layout
  const metadata = nodeOutput.value?.metadata || {};
  const pcLabels = metadata.pc_labels || [];
  const hasCategorical = metadata.label_categories && metadata.label_categories.length > 0 && metadata.label_categories.length < 50;

  const layout: Record<string, any> = {
    ...basePlotLayout,
    height: 400,
    showlegend: hasCategorical,
    xaxis: { ...basePlotLayout.xaxis, title: pcLabels[pcaXAxis.value] || `Dimension ${pcaXAxis.value + 1}` },
    yaxis: { ...basePlotLayout.yaxis, title: pcLabels[pcaYAxis.value] || `Dimension ${pcaYAxis.value + 1}` },
  };

  if (hasCategorical) {
    layout.legend = {
      bgcolor: "rgba(30, 41, 59, 0.8)",
      bordercolor: "#334155",
      borderwidth: 1,
      x: 1,
      y: 1,
      xanchor: "right",
      yanchor: "top",
    } as any;
  }

  return layout;
});

// ============================================================================
// HCA Plots
// ============================================================================

const hcaDendrogramData = computed(() => {
  if (nodeTypeKey.value !== "model.hca" || !hasOutput.value) return [];
  const plots = nodeOutput.value?.plots;
  if (plots?.dendrogram?.data) {
    return plots.dendrogram.data;
  }
  return [];
});

const hcaDendrogramLayout = computed(() => {
  // Early return for non-HCA nodes (consistent with hcaDendrogramData)
  if (nodeTypeKey.value !== "model.hca" || !hasOutput.value) {
    return { ...basePlotLayout, height: 500, showlegend: false };
  }

  const plots = nodeOutput.value?.plots;
  const dendrogramLayout = plots?.dendrogram?.layout;
  if (dendrogramLayout) {
    // Let backend layout (including height) take precedence
    return {
      ...basePlotLayout,
      height: 500,           // Default height (will be overwritten by backend if provided)
      showlegend: false,
      ...dendrogramLayout,   // Backend values override defaults
    };
  }
  // Fallback: axis titles match backend defaults (Distance on X, Sample Index on Y for rotated dendrogram)
  return {
    ...basePlotLayout,
    height: 500,
    showlegend: false,
    xaxis: { ...basePlotLayout.xaxis, title: "Distance" },
    yaxis: { ...basePlotLayout.yaxis, title: "Sample Index" },
  };
});

// ============================================================================
// Peak Finding Plot (pre-computed on the backend)
// ============================================================================
const peakFindingPlotData = computed(() => {
  if (nodeTypeKey.value !== "analysis.peak_finding" || !hasOutput.value) return [];
  const plots = nodeOutput.value?.plots;
  if (plots?.peak_finding?.data) {
    return plots.peak_finding.data;
  }
  return [];
});

const peakFindingPlotLayout = computed(() => {
  if (nodeTypeKey.value !== "analysis.peak_finding" || !hasOutput.value) {
    return { ...basePlotLayout, height: 500 };
  }
  const plots = nodeOutput.value?.plots;
  const backendLayout = plots?.peak_finding?.layout;
  if (backendLayout) {
    return { ...basePlotLayout, height: 500, ...backendLayout };
  }
  return { ...basePlotLayout, height: 500 };
});

const plsdaLoadingsData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  // Use pre-built plots from backend (preferred)
  const plots = nodeOutput.value?.plots;

  if (plsdaLoadingsViewMode.value === "lines") {
    // Try loadings_lines first, fall back to loadings
    if (plots?.loadings_lines?.data) {
      return plots.loadings_lines.data;
    } else if (plots?.loadings?.data) {
      return plots.loadings.data;
    }
  } else if (plsdaLoadingsViewMode.value === "biplot") {
    // Try loadings_biplot first, fall back to old biplot in loadings
    if (plots?.loadings_biplot?.data) {
      return plots.loadings_biplot.data;
    }
  }

  // Fallback: dummy invisible trace needed for Plotly to render annotations
  return [{
    x: [0],
    y: [0],
    type: "scatter",
    mode: "markers",
    marker: { size: 0.1, opacity: 0 },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const plsdaLoadingsLayout = computed(() => {
  // Use pre-built layout if available
  const plots = nodeOutput.value?.plots;

  if (plsdaLoadingsViewMode.value === "lines") {
    if (plots?.loadings_lines?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings_lines.layout,
        height: 350,
      };
    } else if (plots?.loadings?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings.layout,
        height: 350,
      };
    }
  } else if (plsdaLoadingsViewMode.value === "biplot") {
    if (plots?.loadings_biplot?.layout) {
      return {
        ...basePlotLayout,
        ...plots.loadings_biplot.layout,
        height: 350,
      };
    }
  }

  // Fallback layout with arrow annotations
  const loadingsPort = nodeOutput.value?.ports?.loadings || nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const loadings = loadingsPort?.data || metadata.loadings || [];
  const feature_names = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  if (!loadings || loadings.length === 0 || loadings[0]?.length < 2) {
    return {
      ...basePlotLayout,
      height: 350,
      showlegend: false,
      xaxis: { ...basePlotLayout.xaxis, title: "Loading on LV1" },
      yaxis: { ...basePlotLayout.yaxis, title: "Loading on LV2" },
    };
  }

  const n_features = loadings.length;

  // Create labels for features
  let labels;
  if (feature_names && feature_names.length === n_features) {
    labels = feature_names;
  } else if (wavenumbers && wavenumbers.length === n_features) {
    if (wavenumbers.length <= 50) {
      labels = wavenumbers.map((w: number) => w.toFixed(0));
    } else {
      const step = Math.floor(wavenumbers.length / 20);
      labels = wavenumbers.map((w: number, i: number) => i % step === 0 ? w.toFixed(0) : "");
    }
  } else {
    labels = Array.from({ length: n_features }, (_, i) => `F${i}`);
  }

  // Create arrow annotations (quiver plot style)
  const annotations: any[] = [];
  for (let i = 0; i < loadings.length; i++) {
    const lv1 = loadings[i][0];
    const lv2 = loadings[i][1];

    // Arrow from origin to loading position
    annotations.push({
      x: lv1,
      y: lv2,
      ax: 0,
      ay: 0,
      xref: "x",
      yref: "y",
      axref: "x",
      ayref: "y",
      showarrow: true,
      arrowhead: 2,
      arrowsize: 1,
      arrowwidth: 2,
      arrowcolor: "steelblue",
    });

    // Text label at 1.15x arrow length
    annotations.push({
      x: lv1 * 1.15,
      y: lv2 * 1.15,
      text: labels[i],
      xref: "x",
      yref: "y",
      showarrow: false,
      font: { size: 10, color: "black" },
      xanchor: "center",
      yanchor: "middle",
    });
  }

  return {
    ...basePlotLayout,
    height: 350,
    showlegend: false,
    xaxis: {
      ...basePlotLayout.xaxis,
      title: "Loading on LV1",
      zeroline: true,
      zerolinecolor: "gray",
      zerolinewidth: 1,
    },
    yaxis: {
      ...basePlotLayout.yaxis,
      title: "Loading on LV2",
      zeroline: true,
      zerolinecolor: "gray",
      zerolinewidth: 1,
    },
    annotations,
    hovermode: "closest",
  };
});

const plsdaVipData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  // Use pre-built VIP plot
  const plots = nodeOutput.value?.plots;
  if (plots?.vip?.data) {
    return plots.vip.data;
  }

  // Fallback: build from metadata
  const loadingsPort = nodeOutput.value?.ports?.loadings || nodeOutput.value?.ports?.X_loadings;
  const loadingsPayload = resolvePortPayload(loadingsPort);
  const metadata = nodeOutput.value?.metadata || {};
  const vip_scores = metadata.vip_scores;
  const feature_names = metadata.feature_names;
  const wavenumbers = loadingsPayload?.x_axis?.data || metadata.wavenumbers;

  if (!vip_scores || vip_scores.length === 0) return [];

  // Show top N VIP scores
  const top_n = Math.min(50, vip_scores.length);
  const indices = Array.from(vip_scores.keys()) as number[];
  indices.sort((a, b) => vip_scores[b] - vip_scores[a]);
  const top_indices = indices.slice(0, top_n);

  // Priority: feature_names > wavenumbers > feature indices
  let x_values;
  if (feature_names && feature_names.length === vip_scores.length) {
    x_values = top_indices.map((i: number) => feature_names[i]);
  } else if (wavenumbers && wavenumbers.length === vip_scores.length) {
    x_values = top_indices.map((i: number) => wavenumbers[i]);
  } else {
    x_values = top_indices;
  }

  const y_values = top_indices.map((i: number) => vip_scores[i]);

  return [{
    x: x_values,
    y: y_values,
    type: "bar",
    name: "VIP Scores",
    marker: {
      color: y_values,
      colorscale: "Viridis",
      showscale: true,
      colorbar: { title: "VIP" },
    },
  }];
});

const plsdaVipLayout = computed(() => {
  // Use pre-built layout if available
  const plots = nodeOutput.value?.plots;
  if (plots?.vip?.layout) {
    return {
      ...basePlotLayout,
      ...plots.vip.layout,
      height: 350,
    };
  }

  // Fallback layout
  const metadata = nodeOutput.value?.metadata || {};
  const vip_scores = metadata.vip_scores || [];
  const feature_names = metadata.feature_names;
  const wavenumbers = metadata.wavenumbers;

  // Determine x-axis title from actual metadata
  let xaxis_title = "Feature Index";
  let xaxis_reversed = false;
  if (feature_names && feature_names.length > 0) {
    xaxis_title = "Feature";
  } else if (wavenumbers && wavenumbers.length > 0) {
    const xTitle = metadata.x_title || "Feature";
    const xUnits = metadata.x_units || "";
    xaxis_title = xUnits ? `${xTitle} (${xUnits})` : xTitle;
    xaxis_reversed = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  }

  // Calculate number of bars for threshold line
  const top_n = Math.min(50, vip_scores.length);

  return {
    ...basePlotLayout,
    height: 350,
    xaxis: { ...basePlotLayout.xaxis, title: xaxis_title, autorange: xaxis_reversed ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: "VIP Score" },
    shapes: top_n > 0 ? [{
      type: "line",
      x0: 0,
      x1: top_n - 1,
      y0: 1,
      y1: 1,
      line: { color: "red", width: 2, dash: "dash" },
    }] : [],
  };
});

// Confusion Matrix (Training) for PLS-DA
const plsdaConfusionTrainData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_train?.data) {
    return plots.confusion_matrix_train.data;
  }

  return [];
});

const plsdaConfusionTrainLayout = computed(() => {
  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_train?.layout) {
    return {
      ...basePlotLayout,
      ...plots.confusion_matrix_train.layout,
      height: 400,
    };
  }

  return {
    ...basePlotLayout,
    height: 400,
    title: "Confusion Matrix (Training)",
    xaxis: { ...basePlotLayout.xaxis, title: "Predicted Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "True Class", autorange: "reversed" },
  };
});

// Confusion Matrix (Cross-Validation) for PLS-DA
const plsdaConfusionCVData = computed(() => {
  if (nodeTypeKey.value !== "classification.plsda" || !hasOutput.value) return [];

  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_cv?.data) {
    return plots.confusion_matrix_cv.data;
  }

  return [];
});

const plsdaConfusionCVLayout = computed(() => {
  const plots = nodeOutput.value?.plots;
  if (plots?.confusion_matrix_cv?.layout) {
    return {
      ...basePlotLayout,
      ...plots.confusion_matrix_cv.layout,
      height: 400,
    };
  }

  return {
    ...basePlotLayout,
    height: 400,
    title: "Confusion Matrix (Cross-Validation)",
    xaxis: { ...basePlotLayout.xaxis, title: "Predicted Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "True Class", autorange: "reversed" },
  };
});

// ============================================================================
// Preprocessing / DATA Spectra Plots
// ============================================================================

const spectraOverlayData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const nFeatures = data[0]?.length || 0;
  const wn = metadata.wavenumbers;
  const wavenumbers = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const labelsRaw = metadata.labels || metadata.sample_labels || [];
  const labels = Array.isArray(labelsRaw) ? labelsRaw.map((label: any) => normalizeSampleLabel(label)) : [];

  if (!Array.isArray(data[0])) return [];

  const maxTraces = Math.min(data.length, 50);
  return data.slice(0, maxTraces).map((spectrum: number[], i: number) => ({
    type: "scatter",
    mode: "lines",
    x: wavenumbers,
    y: spectrum,
    name: labels[i] || `Spectrum ${i + 1}`,
    line: { width: 1.5 },
    opacity: 0.8,
  }));
});

const spectraOverlayLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
  };
});

const spectraContourData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};

  if (!Array.isArray(data[0])) return [];

  const nFeatures = data[0].length;
  const wn = metadata.wavenumbers;
  const xValues = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const sampleIndices = Array.from({ length: data.length }, (_, i) => i + 1);
  const xTitle = metadata.x_title || "Feature";

  return [{
    type: "heatmap",
    z: data,
    x: xValues,
    y: sampleIndices,
    colorscale: "Viridis",
    hovertemplate: `${xTitle}: %{x:.1f}<br>Sample: %{y}<br>Value: %{z:.4f}<extra></extra>`,
  }];
});

const spectraContourLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");
  const yLabel = metadata.is_time_series ? "Scan / Time Index" : "Sample Index";

  return {
    ...basePlotLayout,
    height: 400,
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yLabel },
  };
});

// ============================================================================
// Generic Data Plots (for non-spectral datasets like Iris)
// ============================================================================

// Box plot data: one box per feature with points colored by class
const genericBoxPlotData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const targetPort = nodeOutput.value?.ports?.target;
  const target = targetPort?.data || metadata.target || [];
  const targetNames = metadata.target_names || [];

  if (!Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const numFeatures = data[0].length;
  const traces: any[] = [];
  const colors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

  // Create one box per feature (showing all data)
  for (let f = 0; f < numFeatures; f++) {
    const featureData = data.map((row: number[]) => row[f]);
    const featureName = featureNames[f] || `Feature ${f + 1}`;
    traces.push({
      type: "box",
      y: featureData,
      name: featureName,
      marker: { color: "#64748b" }, // Neutral gray for boxes
      boxpoints: false, // Don't show points on box - we'll add colored scatter
      showlegend: false,
    });
  }

  // If we have labels, add colored scatter points on top
  if (target.length > 0 && targetNames.length > 0) {
    targetNames.forEach((className: string, classIdx: number) => {
      const classIndices = target
        .map((t: number | string, i: number) => (t === classIdx || t === className) ? i : -1)
        .filter((i: number) => i >= 0);

      // Collect all points for this class across all features
      const xValues: string[] = [];
      const yValues: number[] = [];

      featureNames.forEach((featureName: string, featureIdx: number) => {
        classIndices.forEach((rowIdx: number) => {
          // Add jitter to x position for visibility
          xValues.push(featureName);
          yValues.push(data[rowIdx][featureIdx]);
        });
      });

      traces.push({
        type: "scatter",
        mode: "markers",
        x: xValues,
        y: yValues,
        name: className,
        marker: {
          color: colors[classIdx % colors.length],
          size: 6,
          opacity: 0.7,
        },
        legendgroup: className,
        showlegend: true,
        hovertemplate: `${className}<br>%{x}: %{y:.3f}<extra></extra>`,
      });
    });
  }

  return traces;
});

const genericBoxPlotLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const targetPort = nodeOutput.value?.ports?.target;
  const hasTarget = (targetPort?.data?.length || metadata.target?.length || 0) > 0;

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: hasTarget,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: "Feature" },
    yaxis: { ...basePlotLayout.yaxis, title: "Value" },
  };
});

// Feature scatter plot: X vs Y with label coloring
const genericScatterData = computed(() => {
  if (!hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const featureNames = metadata.feature_names || [];
  const targetPort = nodeOutput.value?.ports?.target;
  const target = targetPort?.data || metadata.target || [];
  const targetNames = metadata.target_names || [];

  if (!Array.isArray(data) || data.length === 0 || !Array.isArray(data[0])) return [];

  const xIdx = featureXAxis.value;
  const yIdx = featureYAxis.value;
  const xName = featureNames[xIdx] || `Feature ${xIdx + 1}`;
  const yName = featureNames[yIdx] || `Feature ${yIdx + 1}`;

  const colors = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316"];

  // If we have labels, create one trace per class
  if (target.length > 0 && targetNames.length > 0) {
    return targetNames.map((className: string, classIdx: number) => {
      const classIndices = target
        .map((t: number | string, i: number) => (t === classIdx || t === className) ? i : -1)
        .filter((i: number) => i >= 0);

      return {
        type: "scatter",
        mode: "markers",
        x: classIndices.map((i: number) => data[i][xIdx]),
        y: classIndices.map((i: number) => data[i][yIdx]),
        name: className,
        marker: {
          color: colors[classIdx % colors.length],
          size: 8,
          opacity: 0.8,
        },
        hovertemplate: `${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<br>${className}<extra></extra>`,
      };
    });
  } else {
    // No labels: single trace
    return [{
      type: "scatter",
      mode: "markers",
      x: data.map((row: number[]) => row[xIdx]),
      y: data.map((row: number[]) => row[yIdx]),
      name: "Samples",
      marker: {
        color: "#3b82f6",
        size: 8,
        opacity: 0.8,
      },
      hovertemplate: `${xName}: %{x:.3f}<br>${yName}: %{y:.3f}<extra></extra>`,
    }];
  }
});

const genericScatterLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const targetPort = nodeOutput.value?.ports?.target;
  const featureNames = metadata.feature_names || [];
  const xName = featureNames[featureXAxis.value] || `Feature ${featureXAxis.value + 1}`;
  const yName = featureNames[featureYAxis.value] || `Feature ${featureYAxis.value + 1}`;
  const hasTarget = (targetPort?.data?.length || metadata.target?.length || 0) > 0;

  return {
    ...basePlotLayout,
    height: 400,
    showlegend: hasTarget,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)", font: { size: 10 } },
    xaxis: { ...basePlotLayout.xaxis, title: xName },
    yaxis: { ...basePlotLayout.yaxis, title: yName },
  };
});

// Handle contour click for interactive slicing
const handleContourClick = (event: any) => {
  if (!event.points || !event.points.length) return;
  const point = event.points[0];
  const metadata = nodeOutput.value?.metadata || {};
  const wavenumbers = metadata.wavenumbers || [];

  // Find closest indices
  const clickedX = point.x;
  const clickedY = point.y;

  // Find wavenumber index
  let wavenumberIdx = 0;
  if (wavenumbers.length) {
    let minDiff = Infinity;
    wavenumbers.forEach((wn: number, i: number) => {
      const diff = Math.abs(wn - clickedX);
      if (diff < minDiff) {
        minDiff = diff;
        wavenumberIdx = i;
      }
    });
  } else {
    wavenumberIdx = Math.round(clickedX);
  }

  const sampleIdx = Math.round(clickedY) - 1; // Convert to 0-indexed

  contourClickPoint.value = {
    sampleIdx: Math.max(0, sampleIdx),
    wavenumberIdx,
    wavenumber: wavenumbers[wavenumberIdx] || wavenumberIdx,
  };
};

// Horizontal slice (spectrum at selected sample)
const horizontalSliceData = computed(() => {
  if (!contourClickPoint.value || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];
  const metadata = nodeOutput.value?.metadata || {};
  const nFeatures = data[0]?.length || 0;
  const wn = metadata.wavenumbers;
  const xValues = (Array.isArray(wn) && wn.length === nFeatures) ? wn : Array.from({ length: nFeatures }, (_, i) => i);
  const xTitle = metadata.x_title || "Feature";

  const spectrum = data[contourClickPoint.value.sampleIdx];
  if (!spectrum) return [];

  return [{
    type: "scatter",
    mode: "lines",
    x: xValues,
    y: spectrum,
    line: { color: "#3b82f6", width: 2 },
    hovertemplate: `${xTitle}: %{x:.1f}<br>Value: %{y:.4f}<extra></extra>`,
  }, {
    // Marker at clicked point
    type: "scatter",
    mode: "markers",
    x: [contourClickPoint.value.wavenumber],
    y: [spectrum[contourClickPoint.value.wavenumberIdx]],
    marker: { size: 12, color: "#f97316", symbol: "circle" },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const horizontalSliceLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const xTitle = metadata.x_title || "Feature";
  const xUnits = metadata.x_units || "";
  const xLabel = xUnits ? `${xTitle} (${xUnits})` : xTitle;
  const shouldReverse = xUnits.includes("cm") || xTitle.toLowerCase().includes("wavenumber");

  return {
    ...basePlotLayout,
    height: 250,
    showlegend: false,
    xaxis: { ...basePlotLayout.xaxis, title: xLabel, autorange: shouldReverse ? "reversed" : true },
    yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
  };
});

// Vertical slice (time profile at selected wavenumber)
const verticalSliceData = computed(() => {
  if (!contourClickPoint.value || !hasOutput.value) return [];
  const data = nodeOutput.value?.data || [];

  const profile = data.map((row: number[]) => row[contourClickPoint.value!.wavenumberIdx]);
  const x = Array.from({ length: data.length }, (_, i) => i + 1);

  return [{
    type: "scatter",
    mode: "lines",
    x,
    y: profile,
    line: { color: "#10b981", width: 2 },
    hovertemplate: "Sample %{x}: %{y:.4f}<extra></extra>",
  }, {
    // Marker at clicked point
    type: "scatter",
    mode: "markers",
    x: [contourClickPoint.value.sampleIdx + 1],
    y: [profile[contourClickPoint.value.sampleIdx]],
    marker: { size: 12, color: "#f97316", symbol: "circle" },
    showlegend: false,
    hoverinfo: "skip",
  }];
});

const verticalSliceLayout = computed(() => ({
  ...basePlotLayout,
  height: 250,
  showlegend: false,
  xaxis: { ...basePlotLayout.xaxis, title: "Sample Index" },
  yaxis: { ...basePlotLayout.yaxis, title: yAxisLabel.value || "Response" },
}));

// ============================================================================
// CLUSTER SCATTER (KMeans / DBSCAN)
// ============================================================================

const CLUSTER_COLORS = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#6366f1", "#14b8a6"];

const clusterScatterData = computed(() => {
  if (!["model.kmeans", "model.hca", "model.dbscan"].includes(nodeTypeKey.value) || !hasOutput.value) return [];
  // Clustering nodes expose two relevant ports:
  //   - `embedding` — 2D projection (Array2D, [n_samples, 2])
  //   - `labels`    — cluster assignment (Array1D, [n_samples])
  // Fall back to top-level for legacy bundled output shapes.
  const ports = nodeOutput.value?.ports;
  const embeddingPort = ports?.embedding?.value as Record<string, unknown> | undefined;
  const labelsPort = ports?.labels?.value as unknown;
  const embedding = (embeddingPort?.data ?? embeddingPort) as number[][] | undefined;
  const labels = (Array.isArray(labelsPort) ? labelsPort : (labelsPort as Record<string, unknown> | undefined)?.data) as number[] | undefined;
  if (!embedding || !labels) return [];

  const uniqueLabels = [...new Set(labels)].sort((a, b) => a - b);
  return uniqueLabels.map((label) => {
    const indices = labels.map((l, i) => (l === label ? i : -1)).filter((i) => i >= 0);
    const isNoise = label === -1;
    return {
      x: indices.map((i) => embedding[i][0]),
      y: indices.map((i) => embedding[i][1]),
      mode: "markers" as const,
      type: "scatter" as const,
      name: isNoise ? "Noise" : `Cluster ${label}`,
      marker: {
        color: isNoise ? "#6b7280" : CLUSTER_COLORS[label % CLUSTER_COLORS.length],
        size: isNoise ? 5 : 8,
        symbol: isNoise ? "x" : "circle",
        opacity: isNoise ? 0.5 : 0.8,
      },
    };
  });
});

const clusterScatterLayout = computed(() => ({
  ...basePlotLayout,
  title: { text: "Cluster Assignments", font: { color: "#e2e8f0", size: 14 } },
  xaxis: { title: "Component 1", color: "#94a3b8" },
  yaxis: { title: "Component 2", color: "#94a3b8" },
  showlegend: true,
  legend: { font: { color: "#94a3b8" } },
}));

// OUTLIER DETECTION: T² vs Q Control Chart
// ============================================================================

const outlierChartData = computed(() => {
  if (nodeTypeKey.value !== "diagnostics.outliers" || !hasOutput.value) return [];
  const result = nodeOutput.value?.ports?.default?.value as Record<string, unknown> | undefined;
  if (!result) return [];
  const T2 = result.T2 as number[] | undefined;
  const Q = result.Q as number[] | undefined;
  const T2_limit = result.T2_limit as number | undefined;
  const Q_limit = result.Q_limit as number | undefined;
  const outliers = result.outliers as boolean[] | undefined;
  if (!T2 || !Q) return [];

  const normal_T2: number[] = [];
  const normal_Q: number[] = [];
  const normal_labels: string[] = [];
  const outlier_T2: number[] = [];
  const outlier_Q: number[] = [];
  const outlier_labels: string[] = [];

  for (let i = 0; i < T2.length; i++) {
    const label = `Sample ${i + 1}`;
    if (outliers && outliers[i]) {
      outlier_T2.push(T2[i]);
      outlier_Q.push(Q[i]);
      outlier_labels.push(label);
    } else {
      normal_T2.push(T2[i]);
      normal_Q.push(Q[i]);
      normal_labels.push(label);
    }
  }

  const traces: Record<string, unknown>[] = [
    {
      x: normal_T2, y: normal_Q, text: normal_labels,
      mode: "markers", type: "scatter", name: "Normal",
      marker: { color: "#3b82f6", size: 7 },
      hovertemplate: "%{text}<br>T²: %{x:.2f}<br>Q: %{y:.2f}<extra></extra>",
    },
  ];
  if (outlier_T2.length > 0) {
    traces.push({
      x: outlier_T2, y: outlier_Q, text: outlier_labels,
      mode: "markers", type: "scatter", name: "Outlier",
      marker: { color: "#ef4444", size: 9, symbol: "diamond" },
      hovertemplate: "%{text}<br>T²: %{x:.2f}<br>Q: %{y:.2f}<extra></extra>",
    });
  }
  // T² limit line (vertical)
  if (T2_limit != null) {
    const maxQ = Math.max(...Q) * 1.1;
    traces.push({
      x: [T2_limit, T2_limit], y: [0, maxQ],
      mode: "lines", type: "scatter", name: `T² limit`,
      line: { dash: "dash", color: "#f59e0b", width: 2 },
      showlegend: true,
    });
  }
  // Q limit line (horizontal)
  if (Q_limit != null) {
    const maxT2 = Math.max(...T2) * 1.1;
    traces.push({
      x: [0, maxT2], y: [Q_limit, Q_limit],
      mode: "lines", type: "scatter", name: `Q limit`,
      line: { dash: "dash", color: "#f59e0b", width: 2 },
      showlegend: true,
    });
  }
  return traces;
});

const outlierChartLayout = computed(() => ({
  ...basePlotLayout,
  title: { text: "T² vs Q Residuals (Control Chart)", font: { color: "#e2e8f0", size: 14 } },
  xaxis: { title: "Hotelling T²", color: "#94a3b8", zeroline: false },
  yaxis: { title: "Q Residuals (SPE)", color: "#94a3b8", zeroline: false },
  showlegend: true,
  legend: { font: { color: "#94a3b8" } },
}));

// HOLDOUT / CROSS-VALIDATION Evaluation Plots
// ============================================================================

const holdoutVisualization = computed(() => {
  if (!hasOutput.value) return null;
  // HoldoutEvaluation declares named output ports ('metrics',
  // 'predictions', 'visualization', 'evaluation') — there is no
  // 'default' port, so the previous lookup at ports.default.value was
  // always undefined and this panel has been empty since the node was
  // introduced.  Read the visualization port directly; fall through to
  // metadata only if the port is missing (legacy single-output shape).
  const vizPortValue = nodeOutput.value?.ports?.visualization?.value as
    | Record<string, unknown>
    | undefined;
  if (vizPortValue && typeof vizPortValue === "object") {
    // If the port was built by normalizePortOutput from the eval node's
    // visualization payload directly, ``vizPortValue`` is the viz dict
    // itself (with ``type``, ``data``/``series``, ``metadata``).
    if (typeof (vizPortValue as any).type === "string") {
      return vizPortValue;
    }
    // Otherwise it's a wrapper that carries a nested ``visualization``
    // key — unwrap it.
    const nested = (vizPortValue as any).visualization;
    if (nested && typeof nested === "object") return nested as Record<string, unknown>;
  }
  // Last-resort legacy fallback: some older node shapes put the
  // visualization payload on the node's top-level metadata.
  const meta = nodeOutput.value?.metadata as Record<string, unknown> | undefined;
  const metaViz = meta?.visualization as Record<string, unknown> | undefined;
  return metaViz || null;
});

const holdoutConfusionData = computed(() => {
  const viz = holdoutVisualization.value;
  if (!viz || viz.type !== "confusion_matrix") return [];
  const cm = viz.data as number[][];
  if (!cm || !cm.length) return [];
  const labels = (viz.metadata as Record<string, unknown>)?.classes as string[] ||
    cm.map((_: unknown, i: number) => `Class ${i}`);
  return [{
    z: cm,
    x: labels,
    y: labels,
    type: "heatmap" as const,
    colorscale: "Blues",
    showscale: true,
    text: cm.map((row: number[]) => row.map((v: number) => String(v))),
    texttemplate: "%{text}",
    hovertemplate: "True: %{y}<br>Predicted: %{x}<br>Count: %{z}<extra></extra>",
  }];
});

const holdoutConfusionLayout = computed(() => ({
  ...basePlotLayout,
  title: { text: "Confusion Matrix", font: { color: "#e2e8f0", size: 14 } },
  xaxis: { title: "Predicted", color: "#94a3b8" },
  yaxis: { title: "True", color: "#94a3b8", autorange: "reversed" as const },
}));

const holdoutRegressionData = computed(() => {
  const viz = holdoutVisualization.value;
  if (!viz || viz.type !== "predicted_vs_actual") return [];

  // Multi-target PLS2 payload (new shape from HoldoutEvaluation):
  //   viz.series = [{name, actual: number[], predicted: number[]}, ...]
  // Render one marker trace per target, plus a dashed 1:1 line spanning
  // the combined min/max of all series.
  const series = viz.series as Array<{
    name?: string;
    actual?: number[];
    predicted?: number[];
  }> | undefined;
  if (Array.isArray(series) && series.length > 0) {
    const traces: any[] = [];
    const allActual: number[] = [];
    const allPredicted: number[] = [];
    for (const s of series) {
      const actual = Array.isArray(s.actual) ? s.actual.map(Number) : [];
      const predicted = Array.isArray(s.predicted) ? s.predicted.map(Number) : [];
      if (actual.length === 0 || predicted.length === 0) continue;
      traces.push({
        x: actual,
        y: predicted,
        mode: "markers" as const,
        type: "scatter" as const,
        name: String(s.name || "Target"),
      });
      allActual.push(...actual);
      allPredicted.push(...predicted);
    }
    if (traces.length === 0) return [];
    const minVal = Math.min(...allActual, ...allPredicted);
    const maxVal = Math.max(...allActual, ...allPredicted);
    traces.push({
      x: [minVal, maxVal],
      y: [minVal, maxVal],
      mode: "lines" as const,
      type: "scatter" as const,
      name: "1:1 Line",
      line: { dash: "dash" as const, color: "#94a3b8" },
    });
    return traces;
  }

  // Legacy single-target payload: viz.data = number[][] of [actual, predicted] pairs.
  const pairs = (viz.data as number[][]) || [];
  if (!pairs.length) return [];
  const actual = pairs.map((p: number[]) => p[0]);
  const predicted = pairs.map((p: number[]) => p[1]);
  const minVal = Math.min(...actual, ...predicted);
  const maxVal = Math.max(...actual, ...predicted);
  return [
    { x: actual, y: predicted, mode: "markers" as const, type: "scatter" as const, name: "Samples", marker: { color: "#3b82f6" } },
    { x: [minVal, maxVal], y: [minVal, maxVal], mode: "lines" as const, type: "scatter" as const, name: "1:1 Line", line: { dash: "dash" as const, color: "#94a3b8" } },
  ];
});

const holdoutRegressionLayout = computed(() => {
  // Show the legend when there are multiple target series so users can
  // tell the colors apart; keep the legacy single-target layout clean.
  // For multi-target runs, incorporate the real reference property names
  // from metadata.target_names (populated by HoldoutEvaluation via the
  // ``context`` port) into the yaxis title — falls back to generic
  // "Predicted" when no names are available.
  const viz = holdoutVisualization.value as any;
  const isMultiTarget = Array.isArray(viz?.series) && viz.series.length > 1;
  const rawNames = (viz?.metadata as any)?.target_names;
  const targetNames = Array.isArray(rawNames) ? rawNames.map(String).filter(Boolean) : [];
  const hasRealNames = targetNames.length > 0
    && !targetNames.every((n) => /^Target_\d+$/.test(n));

  let yTitle = "Predicted";
  let titleText = isMultiTarget ? "Predicted vs Actual (per target)" : "Predicted vs Actual";
  if (isMultiTarget && hasRealNames) {
    const joined = targetNames.join(", ");
    yTitle = `Predicted (${joined})`;
    titleText = `Predicted vs Actual — ${joined}`;
  } else if (!isMultiTarget && hasRealNames) {
    yTitle = `Predicted ${targetNames[0]}`;
    titleText = `Predicted vs Actual — ${targetNames[0]}`;
  }

  return {
    ...basePlotLayout,
    title: { text: titleText, font: { color: "#e2e8f0", size: 14 } },
    xaxis: { title: "Actual", color: "#94a3b8" },
    yaxis: { title: yTitle, color: "#94a3b8" },
    showlegend: isMultiTarget,
  };
});

// STATS Plots (adaptive: PeakFinding → bar chart, otherwise → histogram)
// ============================================================================

const statsPlotData = computed(() => {
  if (nodeTypeKey.value !== "stats.summary" || !hasOutput.value) return [];
  const portValue = nodeOutput.value?.ports?.statistics?.value as Record<string, unknown> | undefined;
  const metadata = nodeOutput.value?.metadata || {};
  const inputType = (portValue?.input_type as string) || (metadata.type as string) || "";

  // PeakFinding: two-axis plot
  //   - Vertical axis: median height with IQR error bars (intensity variation)
  //   - Horizontal axis: position with std error bars (positional scatter)
  if (inputType === "PeakFinding") {
    const horiz = (portValue?.horizontal || []) as Array<Record<string, number | string>>;
    const vert = (portValue?.vertical || []) as Array<Record<string, number | string>>;
    if (!horiz.length) return [];

    const positions = horiz.map((h) => Number(h.median_pos));
    const heights = vert.map((v) => Number(v.median_height));
    const q1 = vert.map((v) => Number(v.q1_height));
    const q3 = vert.map((v) => Number(v.q3_height));
    const posStd = horiz.map((h) => Number(h.std_pos));
    const labels = horiz.map((h, i) => {
      const v = vert[i];
      return `<b>${h.label}</b><br>` +
        `Position: ${Number(h.median_pos).toFixed(1)} ± ${Number(h.std_pos).toFixed(1)}<br>` +
        `Range: ${Number(h.min_pos).toFixed(1)}–${Number(h.max_pos).toFixed(1)}<br>` +
        `Height: ${Number(v.median_height).toFixed(4)}<br>` +
        `IQR: ${Number(v.q1_height).toFixed(4)}–${Number(v.q3_height).toFixed(4)}`;
    });

    return [{
      type: "scatter",
      mode: "markers",
      x: positions,
      y: heights,
      text: labels,
      hovertemplate: "%{text}<extra></extra>",
      marker: { color: "#3b82f6", size: 10 },
      name: "Median Height",
      error_y: {
        type: "data",
        symmetric: false,
        array: q3.map((q, i) => q - heights[i]),       // upper = q3 - median
        arrayminus: heights.map((h, i) => h - q1[i]),   // lower = median - q1
        color: "#60a5fa",
        thickness: 2,
        width: 6,
      },
      error_x: {
        type: "data",
        array: posStd,
        arrayminus: posStd,
        color: "#94a3b8",
        thickness: 1.5,
        width: 4,
      },
    }];
  }

  // Default: histogram of flattened numeric data
  const data = nodeOutput.value?.data || [];
  const values: number[] = [];
  for (const row of data) {
    if (Array.isArray(row)) {
      for (const val of row) {
        if (typeof val === "number" && !isNaN(val)) values.push(val);
      }
    } else if (typeof row === "number") {
      values.push(row);
    } else if (typeof row === "object" && row !== null) {
      for (const val of Object.values(row)) {
        if (typeof val === "number" && !isNaN(val)) values.push(val);
      }
    }
  }
  return [{
    type: "histogram",
    x: values,
    nbinsx: 50,
    marker: { color: "#3b82f6" },
    hovertemplate: "Range: %{x}<br>Count: %{y}<extra></extra>",
  }];
});

const statsPlotLayout = computed(() => {
  const portValue = nodeOutput.value?.ports?.statistics?.value as Record<string, unknown> | undefined;
  const metadata = nodeOutput.value?.metadata || {};
  const inputType = (portValue?.input_type as string) || (metadata.type as string) || "";

  if (inputType === "PeakFinding") {
    const summary = (portValue?.summary || {}) as Record<string, unknown>;
    const xLabel = (summary.x_label as string) || "Position";
    return {
      ...basePlotLayout,
      height: 450,
      title: { text: "Peak Consensus: Position ± σ (horizontal) · Height ± IQR (vertical)", font: { size: 13, color: "#94a3b8" } },
      xaxis: { ...basePlotLayout.xaxis, title: xLabel },
      yaxis: { ...basePlotLayout.yaxis, title: "Peak Height (absorbance)" },
      showlegend: false,
    };
  }
  return {
    ...basePlotLayout,
    height: 350,
    xaxis: { ...basePlotLayout.xaxis, title: "Value" },
    yaxis: { ...basePlotLayout.yaxis, title: "Count" },
    bargap: 0.05,
  };
});



// ============================================================================
// EFA Eigenvalue Plot
// ============================================================================

const efaEigenvalueData = computed(() => {
  if (nodeTypeKey.value !== "model.efa" || !hasOutput.value) return [];
  // EFA primary output is forward eigenvalues as a SherpaDataset
  const data = nodeOutput.value?.data || [];
  if (!data.length || !Array.isArray(data[0])) return [];

  const nSamples = data.length;
  const nComponents = data[0].length;
  const x = Array.from({ length: nSamples }, (_, i) => i + 1);

  // Forward eigenvalues from primary output
  const traces: Record<string, unknown>[] = [];
  for (let c = 0; c < nComponents; c++) {
    traces.push({
      type: "scatter",
      mode: "lines",
      x,
      y: data.map((row: number[]) => row[c]),
      name: `Forward EV ${c + 1}`,
      line: { width: 2 },
    });
  }

  // Backward eigenvalues from ports if available
  const bwPort = nodeOutput.value?.ports?.backward_eigenvalues;
  const bwData = bwPort?.data || bwPort?.value?.data;
  if (bwData && Array.isArray(bwData) && bwData.length > 0) {
    const bwComponents = bwData[0]?.length || 0;
    for (let c = 0; c < bwComponents; c++) {
      traces.push({
        type: "scatter",
        mode: "lines",
        x,
        y: bwData.map((row: number[]) => row[c]),
        name: `Backward EV ${c + 1}`,
        line: { width: 2, dash: "dash" },
      });
    }
  }

  return traces;
});

const efaEigenvalueLayout = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  return {
    ...basePlotLayout,
    height: 450,
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
    xaxis: { ...basePlotLayout.xaxis, title: metadata.x_title || "Sample Index" },
    yaxis: { ...basePlotLayout.yaxis, title: "Eigenvalue (log scale)", type: "log" },
  };
});

// ============================================================================
// Regression: Predicted vs Actual correlation plot
// ============================================================================

const regressionTargetNames = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yLoadings = resolvePortPayload(nodeOutput.value?.ports?.Y_loadings);
  const targetPort = resolvePortPayload(nodeOutput.value?.ports?.target);
  const candidates = [
    metadata.target_names,
    yLoadings?.y_axis?.labels,
    targetPort?.y_axis?.labels,
    targetPort?.metadata?.target_names,
  ];

  for (const raw of candidates) {
    if (Array.isArray(raw) && raw.length > 0) {
      return raw.map((name: unknown) => normalizeSampleLabel(name));
    }
  }

  return [];
});

const regressionTargetOptions = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  if (!Array.isArray(yTrue) || yTrue.length === 0) return [];
  const nTargets = Array.isArray(yTrue[0]) ? yTrue[0].length : 1;
  const names = regressionTargetNames.value;
  return Array.from({ length: nTargets }, (_, i) => ({
    label: names[i] || `Target ${i + 1}`,
    value: i,
  }));
});

watch(
  regressionTargetOptions,
  (options) => {
    if (options.length === 0) {
      regressionTargetIdx.value = 0;
      return;
    }
    if (!options.some((option) => option.value === regressionTargetIdx.value)) {
      regressionTargetIdx.value = options[0].value;
    }
  },
  { immediate: true },
);

const selectedRegressionR2 = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const r2List = metadata.r2_per_target;
  if (!Array.isArray(r2List)) return null;
  const value = r2List[regressionTargetIdx.value];
  return typeof value === "number" ? value : null;
});

const selectedRegressionRmse = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const rmseList = metadata.rmse_per_target;
  if (!Array.isArray(rmseList)) return null;
  const value = rmseList[regressionTargetIdx.value];
  return typeof value === "number" ? value : null;
});

const regressionCorrelationData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || yTrue.length === 0) return [];

  try {
    const idx = regressionTargetIdx.value;
    const trueVals = yTrue.map((row: number[]) => (Array.isArray(row) ? row[idx] : row));
    const predVals = yPred.map((row: number[]) => (Array.isArray(row) ? row[idx] : row));

    const allVals = [...trueVals, ...predVals];
    const minVal = Math.min(...allVals);
    const maxVal = Math.max(...allVals);
    const pad = (maxVal - minVal) * 0.05 || 0.1;

  return [
    {
      type: "scatter",
      mode: "markers",
      x: trueVals,
      y: predVals,
      marker: { color: "#3b82f6", size: 7, opacity: 0.7 },
      name: "Samples",
      hovertemplate: "Actual: %{x:.3f}<br>Predicted: %{y:.3f}<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines",
      x: [minVal - pad, maxVal + pad],
      y: [minVal - pad, maxVal + pad],
      line: { color: "#94a3b8", dash: "dash", width: 1.5 },
      name: "1:1 Line",
      showlegend: false,
      hoverinfo: "skip",
    },
  ];
  } catch (e) {
    console.error("[Regression Plot] ERROR in computed:", e);
    return [];
  }
});

const regressionCorrelationLayout = computed(() => {
  const targetName = regressionTargetOptions.value.find((option) => option.value === regressionTargetIdx.value)?.label || "";
  const r2 = selectedRegressionR2.value;
  const rmse = selectedRegressionRmse.value;

  let title = "Predicted vs Actual";
  if (targetName) title += ` — ${targetName}`;
  const metrics: string[] = [];
  if (r2 != null) metrics.push(`R² = ${r2.toFixed(4)}`);
  if (rmse != null) metrics.push(`RMSE = ${rmse.toFixed(4)}`);
  if (metrics.length) title += `<br><span style="font-size:11px;color:#94a3b8">${metrics.join("  |  ")}</span>`;

  return {
    ...basePlotLayout,
    height: 400,
    title: { text: title, font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...basePlotLayout.xaxis, title: "Actual" },
    yaxis: { ...basePlotLayout.yaxis, title: "Predicted", scaleanchor: "x", scaleratio: 1 },
    showlegend: false,
  };
});

// ============================================================================
// Classification: Per-class accuracy bar chart
// ============================================================================

const classificationAccuracyData = computed(() => {
  const metadata = nodeOutput.value?.metadata || {};
  const yTrue = metadata.y_true;
  const yPred = metadata.y_pred;
  const categories = metadata.label_categories;
  if (!Array.isArray(yTrue) || !Array.isArray(yPred) || !Array.isArray(categories)) return [];

  // Compute per-class accuracy
  const classCorrect: Record<string, number> = {};
  const classTotal: Record<string, number> = {};
  for (const c of categories) {
    classCorrect[c] = 0;
    classTotal[c] = 0;
  }
  for (let i = 0; i < yTrue.length; i++) {
    const t = String(yTrue[i]);
    const p = String(yPred[i]);
    if (classTotal[t] !== undefined) {
      classTotal[t]++;
      if (t === p) classCorrect[t]++;
    }
  }

  const accuracies = categories.map((c: string) =>
    classTotal[c] > 0 ? classCorrect[c] / classTotal[c] : 0
  );
  const overall = yTrue.length > 0
    ? yTrue.filter((t: string, i: number) => String(t) === String(yPred[i])).length / yTrue.length
    : 0;

  return [
    {
      type: "bar",
      x: categories,
      y: accuracies.map((a: number) => a * 100),
      marker: { color: "#3b82f6" },
      name: "Per-class",
      hovertemplate: "%{x}: %{y:.1f}%<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines",
      x: [categories[0], categories[categories.length - 1]],
      y: [overall * 100, overall * 100],
      line: { color: "#f59e0b", dash: "dash", width: 2 },
      name: `Overall (${(overall * 100).toFixed(1)}%)`,
    },
  ];
});

const classificationAccuracyLayout = computed(() => {
  return {
    ...basePlotLayout,
    height: 350,
    title: { text: "Per-Class Accuracy", font: { size: 14, color: "#f8fafc" } },
    xaxis: { ...basePlotLayout.xaxis, title: "Class" },
    yaxis: { ...basePlotLayout.yaxis, title: "Accuracy (%)", range: [0, 105] },
    showlegend: true,
    legend: { x: 1, xanchor: "right", y: 1, bgcolor: "rgba(0,0,0,0)" },
  };
});

// ============================================================================
// End of Plots Section
// ============================================================================

// Methods
const resetToDefaults = () => {
  for (const param of nodeParams.value) {
    if (param.default !== undefined) {
      localParams.value[param.name] = param.default;
    }
  }
  toast.add({
    severity: "info",
    summary: "Reset",
    detail: "Parameters reset to defaults",
    life: 2000,
  });
};


const openDataTable = () => {
  showDataTableModal.value = true;
};

const openQuickPlot = () => {
  showQuickPlotModal.value = true;
};

const exportOutput = () => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return;

  let csv = "";
  if (Array.isArray(data[0])) {
    csv = data.map((row: any[]) => row.join(",")).join("\n");
  } else {
    csv = data.join("\n");
  }

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${nodeLabel.value.replace(/\s+/g, "_")}_output.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

const handleCancel = () => {
  // Close without saving
  window.close();
};

const { isExecuting, broadcastParamsUpdate, handleRunTrial } = useNodeTrial({
  nodeData,
  localParams,
  nodeType,
  addLog,
  normalizeNodeOutput,
  toast,
});

const handleSaveAndExit = () => {
  // Broadcast params update to main tab
  broadcastParamsUpdate();

  toast.add({
    severity: "success",
    summary: "Saved",
    detail: "Settings saved successfully",
    life: 1500,
  });

  // Close after brief delay
  setTimeout(() => {
    window.close();
  }, 500);
};


// Lifecycle — BroadcastChannel setup/teardown lives in useNodeTrial
onMounted(() => {
  // Load node data from session storage
  const storedData = sessionStorage.getItem(STORAGE_KEY);
  if (storedData) {
    try {
      nodeData.value = JSON.parse(storedData);

      // Build params with defaults from paramDefinitions, then override with stored values
      const defaults: Record<string, any> = {};
      const paramDefs = nodeParams.value || [];
      for (const param of paramDefs) {
        if (param.default !== undefined) {
          defaults[param.name] = param.default;
        }
      }

      // Merge: defaults first, then stored params override
      localParams.value = { ...defaults, ...nodeData.value.params };
      originalParams.value = { ...localParams.value };

      console.log('[NodeDetailView] Loaded params:', {
        defaults,
        stored: nodeData.value.params,
        merged: localParams.value,
      });
    } catch (e) {
      console.error("Failed to parse node data from session storage:", e);
      toast.add({
        severity: "error",
        summary: "Error",
        detail: "Failed to load node data",
        life: 3000,
      });
    }
  } else {
    toast.add({
      severity: "warn",
      summary: "No Data",
      detail: "No node data found. Please open from the workflow inspector.",
      life: 5000,
    });
  }
});

// Aggregate plot-related state for PlotsPanel (read-only surface).
const plotState = computed(() => ({
  hasOutput: hasOutput.value,
  availablePlots: availablePlots.value,
  nodeTypeKey: nodeTypeKey.value,
  isPCAOutput: isPCAOutput.value,
  isPreprocessingNode: isPreprocessingNode.value,
  isDataNode: isDataNode.value,
  isSpectraData: isSpectraData.value,
  isGenericDataNode: isGenericDataNode.value,
  nodeOutput: nodeOutput.value,
  contourClickPoint: contourClickPoint.value,
  pcaAxisOptions: pcaAxisOptions.value,
  regressionTargetOptions: regressionTargetOptions.value,
  spectraDisplayOptions,
  genericDisplayOptions,
  featureOptions: featureOptions.value,
  holdoutVisualization: holdoutVisualization.value,
  // PCA
  pcaScoresData: pcaScoresData.value, pcaScoresLayout: pcaScoresLayout.value, pcaScoresConfig: pcaScoresConfig.value,
  pcaBiplotData: pcaBiplotData.value, pcaBiplotLayout: pcaBiplotLayout.value,
  pcaLoadingsData: pcaLoadingsData.value, pcaLoadingsLayout: pcaLoadingsLayout.value, pcaLoadingsConfig: pcaLoadingsConfig.value,
  pcaScreeData: pcaScreeData.value, pcaScreeLayout: pcaScreeLayout.value,
  pcaDiagnosticsData: pcaDiagnosticsData.value, pcaDiagnosticsLayout: pcaDiagnosticsLayout.value,
  // MCR / SIMPLISMA / NMF / ICA
  mcrConcentrationData: mcrConcentrationData.value, mcrConcentrationLayout: mcrConcentrationLayout.value,
  mcrSpectraData: mcrSpectraData.value, mcrSpectraLayout: mcrSpectraLayout.value,
  // EFA
  efaEigenvalueData: efaEigenvalueData.value, efaEigenvalueLayout: efaEigenvalueLayout.value,
  // PLS
  plsScoresData: plsScoresData.value, plsScoresLayout: plsScoresLayout.value,
  plsLoadingsData: plsLoadingsData.value, plsLoadingsLayout: plsLoadingsLayout.value,
  // PLS-DA + classification
  classificationScoresData: classificationScoresData.value, classificationScoresLayout: classificationScoresLayout.value,
  plsdaLoadingsData: plsdaLoadingsData.value, plsdaLoadingsLayout: plsdaLoadingsLayout.value,
  plsdaVipData: plsdaVipData.value, plsdaVipLayout: plsdaVipLayout.value,
  plsdaConfusionTrainData: plsdaConfusionTrainData.value, plsdaConfusionTrainLayout: plsdaConfusionTrainLayout.value,
  plsdaConfusionCVData: plsdaConfusionCVData.value, plsdaConfusionCVLayout: plsdaConfusionCVLayout.value,
  classificationAccuracyData: classificationAccuracyData.value, classificationAccuracyLayout: classificationAccuracyLayout.value,
  // Regression
  regressionCorrelationData: regressionCorrelationData.value, regressionCorrelationLayout: regressionCorrelationLayout.value,
  // HCA / Peak / Plot node
  hcaDendrogramData: hcaDendrogramData.value, hcaDendrogramLayout: hcaDendrogramLayout.value,
  peakFindingPlotData: peakFindingPlotData.value, peakFindingPlotLayout: peakFindingPlotLayout.value,
  plotNodeData: plotNodeData.value, plotNodeLayout: plotNodeLayout.value,
  // Spectra
  spectraOverlayData: spectraOverlayData.value, spectraOverlayLayout: spectraOverlayLayout.value,
  spectraContourData: spectraContourData.value, spectraContourLayout: spectraContourLayout.value,
  horizontalSliceData: horizontalSliceData.value, horizontalSliceLayout: horizontalSliceLayout.value,
  verticalSliceData: verticalSliceData.value, verticalSliceLayout: verticalSliceLayout.value,
  // Generic
  genericBoxPlotData: genericBoxPlotData.value, genericBoxPlotLayout: genericBoxPlotLayout.value,
  genericScatterData: genericScatterData.value, genericScatterLayout: genericScatterLayout.value,
  // Clusters / outliers / holdout / stats
  clusterScatterData: clusterScatterData.value, clusterScatterLayout: clusterScatterLayout.value,
  outlierChartData: outlierChartData.value, outlierChartLayout: outlierChartLayout.value,
  holdoutConfusionData: holdoutConfusionData.value, holdoutConfusionLayout: holdoutConfusionLayout.value,
  holdoutRegressionData: holdoutRegressionData.value, holdoutRegressionLayout: holdoutRegressionLayout.value,
  statsPlotData: statsPlotData.value, statsPlotLayout: statsPlotLayout.value,
}));

// ── Provide canonical state to descendant panels (issue #24a) ─────────
// Panels inject NODE_DETAIL_STATE_KEY instead of receiving the big prop
// bags they used to. Readonly refs are passed through directly; the
// writable slice gives panels typed handles for v-model-style updates.
const detailState: NodeDetailState = {
  output: {
    summary: outputSummary,
    hasOutput,
    data: outputData,
    metadata: outputMetadata,
    subsections: outputSubsections,
    datasetInfo,
    datasetLabelTable,
    labelPreviewLimit,
    processingHistory,
    provenance: provenanceInfo,
    quality: qualitySummary,
    portSummaries,
    preview: computed(() => ({
      rows: outputPreview.value,
      columns: outputPreviewColumns.value,
      summary: outputDataSummary.value,
    })),
    pcaDiagnostics: computed(() => ({
      rows: pcaDiagnosticsPreview.value,
      columns: pcaDiagnosticsColumns.value,
      summary: pcaDiagSummary.value,
    })),
    isRegressionNode,
    regressionTargetOptions,
    selectedRegressionR2,
    selectedRegressionRmse,
    getMetaTooltip,
    formatMetaValue,
  },
  plots: plotState,
  writable: {
    pcaXAxis,
    pcaYAxis,
    plsdaLoadingsViewMode,
    regressionTargetIdx,
    spectraDisplayMode,
    genericDisplayMode,
    featureXAxis,
    featureYAxis,
    contourClickPoint,
  },
  plotSections,
};
provide(NODE_DETAIL_STATE_KEY, detailState);

</script>

<style scoped>
/* Shell-only styles. Per-panel styles live in node-detail/panels/*.vue. */
.node-detail-view {
  min-height: 100vh;
  background: #0f172a;
  color: #f8fafc;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 32px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.node-icon {
  font-size: 2.5rem;
}

.header-info h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.node-type-badge {
  display: inline-block;
  margin-top: 4px;
  padding: 2px 10px;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  text-transform: uppercase;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.detail-content {
  max-width: 1000px;
  margin: 0 auto;
  padding: 32px;
}

.full-metadata-json {
  background: #0f172a;
  color: #e2e8f0;
  padding: 16px;
  border-radius: 8px;
  font-family: "JetBrains Mono", monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

@media (max-width: 768px) {
  .detail-header {
    flex-direction: column;
    gap: 16px;
    padding: 16px;
  }
  .header-actions {
    width: 100%;
    justify-content: stretch;
  }
  .header-actions .p-button {
    flex: 1;
  }
  .detail-content {
    padding: 16px;
  }
}
</style>
