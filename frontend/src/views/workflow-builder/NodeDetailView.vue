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
import { normalizeSampleLabel } from "@/utils/sampleLabels";
import { useNodeLog } from "./node-detail/composables/useNodeLog";
import { useNodeValidation } from "./node-detail/composables/useNodeValidation";
import { useNodeOutput } from "./node-detail/composables/useNodeOutput";
import { useNodeOutputData } from "./node-detail/composables/useNodeOutputData";
import { useNodePlotData } from "./node-detail/composables/useNodePlotData";
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

const settingsCount = computed(() => nodeParams.value.length);

const { normalizeNodeOutput, resolvePortPayload, primaryOutputPayload } = useNodeOutput(
  nodeOutput,
  nodeMetadata,
);

// Output-panel data + preview tables + regression selector extracted to composable.
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
  isPCAOutput,
  portSummaries,
  fullMetadataJson,
  getMetaTooltip,
  formatMetaValue,
  inputPreview,
  inputPreviewColumns,
  inputDataSummary,
  outputPreview,
  outputPreviewColumns,
  outputDataSummary,
  pcaDiagnosticsPreview,
  pcaDiagnosticsColumns,
  pcaDiagSummary,
  regressionTargetOptions,
  selectedRegressionR2,
  selectedRegressionRmse,
} = useNodeOutputData({
  nodeOutput,
  nodeData,
  nodeTypeKey,
  resolvePortPayload,
  regressionTargetIdx,
  previewRowLimit,
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



// ============================================================================
// PLOTS SECTION - writable refs + all data/layout via useNodePlotData
// ============================================================================

// Writable refs for panel v-model-style updates. Owned by the shell so they
// survive past useNodePlotData and feed into useNodeDetailState.writable.
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);
const spectraDisplayMode = ref<"overlay" | "contour">("contour");
const genericDisplayMode = ref<"boxplot" | "scatter">("boxplot");
const featureXAxis = ref(0);
const featureYAxis = ref(1);
const contourClickPoint = ref<
  { sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null
>(null);

const {
  availablePlots,
  isPreprocessingNode,
  pcaAxisOptions,
  featureOptions,
  spectraDisplayOptions,
  genericDisplayOptions,
  holdoutVisualization,
  handleContourClick,
  pcaScoresData, pcaScoresLayout, pcaScoresConfig,
  pcaBiplotData, pcaBiplotLayout,
  pcaLoadingsData, pcaLoadingsLayout, pcaLoadingsConfig,
  pcaScreeData, pcaScreeLayout,
  pcaDiagnosticsData, pcaDiagnosticsLayout,
  mcrConcentrationData, mcrConcentrationLayout,
  mcrSpectraData, mcrSpectraLayout,
  efaEigenvalueData, efaEigenvalueLayout,
  plsScoresData, plsScoresLayout,
  plsLoadingsData, plsLoadingsLayout,
  classificationScoresData, classificationScoresLayout,
  plsdaLoadingsData, plsdaLoadingsLayout,
  plsdaVipData, plsdaVipLayout,
  plsdaConfusionTrainData, plsdaConfusionTrainLayout,
  plsdaConfusionCVData, plsdaConfusionCVLayout,
  classificationAccuracyData, classificationAccuracyLayout,
  regressionCorrelationData, regressionCorrelationLayout,
  hcaDendrogramData, hcaDendrogramLayout,
  peakFindingPlotData, peakFindingPlotLayout,
  plotNodeData, plotNodeLayout,
  spectraOverlayData, spectraOverlayLayout,
  spectraContourData, spectraContourLayout,
  horizontalSliceData, horizontalSliceLayout,
  verticalSliceData, verticalSliceLayout,
  genericBoxPlotData, genericBoxPlotLayout,
  genericScatterData, genericScatterLayout,
  clusterScatterData, clusterScatterLayout,
  outlierChartData, outlierChartLayout,
  holdoutConfusionData, holdoutConfusionLayout,
  holdoutRegressionData, holdoutRegressionLayout,
  statsPlotData, statsPlotLayout,
} = useNodePlotData({
  nodeOutput,
  nodeType,
  nodeTypeKey,
  hasOutput,
  isPCAOutput,
  isDataNode,
  isSpectraData,
  isGenericDataNode,
  resolvePortPayload,
  pcaSampleLabels,
  pcaLabelCategories,
  pcaUseCategorical,
  pcaXAxis,
  pcaYAxis,
  plsdaLoadingsViewMode,
  regressionTargetIdx,
  featureXAxis,
  featureYAxis,
  contourClickPoint,
  regressionTargetOptions,
  selectedRegressionR2,
  selectedRegressionRmse,
});

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
