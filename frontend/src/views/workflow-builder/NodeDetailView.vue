<template>
  <div class="node-detail-view" :class="{ embedded }">
    <!-- Header -->
    <header class="detail-header">
      <div class="header-left">
        <span class="node-icon">{{ nodeIcon }}</span>
        <div class="header-info">
          <h1>{{ nodeLabel }}</h1>
          <span class="node-instance-id">Instance ID: {{ nodeId }}</span>
          <span class="node-type-badge">Canonical node: {{ nodeType }}</span>
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
          :title="
            hasValidationErrors
              ? 'Fix validation errors before running'
              : 'Run trial execution with current parameters'
          "
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
    <main class="detail-content two-column-layout">
      <div class="column-left">
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

        <PeakExecutionDetails
          v-if="nodeType === 'analysis.peak_finding'"
          :diagnostics="nodeOutput?.metadata?.diagnostics"
        />

        <!-- Output Section -->
        <OutputPanel
          :expanded="sections.output"
          :node-type="nodeType"
          @toggle="toggleSection('output')"
          @toggle-sub="toggleOutputSubsection"
          @show-full-metadata="showFullMetadata = true"
          @open-data-table="openDataTable"
          @open-quick-plot="openQuickPlot"
          @export-output="exportOutput"
        />
      </div>

      <div class="column-right">
        <!-- Plots Section -->
        <PlotsPanel
          :attention-node-id="nodeId"
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
      </div>
    </main>

    <!-- Modals -->
    <QuickPlotModal
      v-model="showQuickPlotModal"
      :nodeOutput="nodeOutput"
      :nodeType="nodeType"
      :nodeLabel="nodeLabel"
      :nodeInput="inputData"
      :nodeInputs="quickPlotInputs"
      :plot-selection="quickPlotSelection"
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
import PeakExecutionDetails from "@/components/common/PeakExecutionDetails.vue";
/* eslint-disable @typescript-eslint/no-explicit-any -- node outputs and plot payloads vary widely across node families in this inspection view. */
import { ref, computed, watch, onMounted, provide, nextTick } from "vue";
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
import { useProjectStore } from "@/stores/project";
import { cloneNodeDetailParams, resolveNodeDetailPayload } from "@/utils/nodeDetailPayload";
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
import { downloadExportArtifact, extractExportArtifact } from "@/utils/exportArtifact";
import type { NodeOutput } from "@/utils/nodeOutput";
import {
  availableScientificPresentations,
  presentationResolutionError,
  projectScientificPresentation,
  resolveScientificPresentation,
} from "@/utils/scientificPresentation";
import { isUserEditableNodeParameter } from "@/utils/nodeParameterVisibility";

const route = useRoute();
const toast = useToast();

const props = withDefaults(
  defineProps<{
    initialNodeData?: any | null;
    embedded?: boolean;
  }>(),
  {
    initialNodeData: null,
    embedded: false,
  },
);

const emit = defineEmits<{
  (event: "save", nodeId: string, params: Record<string, unknown>): void;
  (event: "close"): void;
}>();

// ── Section collapse state ──────────────────────────────────────────────
const {
  sections,
  outputSubsections,
  plotSections,
  toggleSection,
  toggleOutputSubsection,
  togglePlot,
} = useNodeSections();

// ── Execution log entries ───────────────────────────────────────────────
const { executionLogs, addLog, clearLogs, getLogIcon } = useNodeLog();

// ── Writable refs for panel v-model-style updates ───────────────────────
const plsdaLoadingsViewMode = ref<"lines" | "biplot">("lines");
const regressionTargetIdx = ref(0);
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);
const scoreColorMode = ref("labels");
const sampleColorField = ref("specimen_id");
const sampleSymbolField = ref("block");
const selectedFeatureScale = ref("__primary__");
const selectedFeatureLabels = ref("__primary__");
const selectedFeatureTitle = ref("__primary__");
const selectedSampleLabels = ref("__primary__");
const spectraDisplayMode = ref<"overlay" | "contour">("contour");
const genericDisplayMode = ref<"boxplot" | "scatter">("boxplot");
const featureXAxis = ref(0);
const featureYAxis = ref(1);
const contourClickPoint = ref<{
  sampleIdx: number;
  wavenumberIdx: number;
  wavenumber: number;
} | null>(null);
const selectedPresentationId = ref<string | null>(null);
const quickPlotSelection = {
  pcaXAxis, pcaYAxis, featureXAxis, featureYAxis, regressionTargetIdx,
  scoreColorMode, sampleColorField, sampleSymbolField,
  selectedFeatureScale, selectedFeatureLabels, selectedFeatureTitle, selectedSampleLabels,
};

// ── Modal state ─────────────────────────────────────────────────────────
const showQuickPlotModal = ref(false);
const showDataTableModal = ref(false);
const showFullMetadata = ref(false);

// ── Core node state ─────────────────────────────────────────────────────
const nodeData = ref<any>(null);
const localParams = ref<Record<string, any>>({});
const originalParams = ref<Record<string, any>>({});
const workflowStore = useWorkflowStore();
const projectStore = useProjectStore();

const NODE_ICONS: Record<string, string> = {
  "data.file_load": "📂",
  "preprocess.normalize": "📏",
  "preprocess.scale": "📏",
  "baseline.penalized_ls": "📉",
  "preprocess.smooth": "〰️",
  "model.pca": "🔀",
  "model.fitted_pls": "📈",
  "model.apply_fitted_pls": "🎯",
  "model.mcr_als": "🧩",
  "stats.summary": "📊",
  "analysis.peak_finding": "⛰️",
  "analysis.compare_library": "📚",
  "output.plot": "📈",
  "output.contour": "🗺️",
  "output.export": "💾",
};

const embedded = computed(() => props.embedded);
const nodeId = computed(() => String(props.initialNodeData?.id ?? route.params.nodeId ?? ""));
const nodeType = computed(() => nodeData.value?.type || "Unknown");
const nodeTypeKey = computed(() => nodeType.value);
const nodeLabel = computed(() => nodeData.value?.label || `Node ${nodeId.value}`);
const nodeIcon = computed(() => NODE_ICONS[nodeType.value] || "📦");
const nodeMetadata = computed(() => workflowStore.getNodeMetadata(nodeType.value));
const rawNodeOutput = computed<NodeOutput | null>(() => {
  const output = (nodeData.value?.output as NodeOutput | null | undefined) ?? null;
  if (!output) return null;
  const contract =
    output.presentation_contract ??
    nodeData.value?.presentationContract ??
    nodeMetadata.value?.presentation_contract;
  return contract ? { ...output, presentation_contract: contract } : output;
});
const presentationOptions = computed(() =>
  availableScientificPresentations(nodeMetadata.value, rawNodeOutput.value).map((item) => ({
    value: item.presentation.presentation_id,
    label: item.presentation.label,
  })),
);
const selectedPresentation = computed(() =>
  resolveScientificPresentation(
    nodeMetadata.value,
    rawNodeOutput.value,
    selectedPresentationId.value,
  ),
);
const presentationError = computed(() =>
  presentationResolutionError(
    nodeMetadata.value,
    rawNodeOutput.value,
    selectedPresentationId.value,
  ),
);
const nodeOutput = computed<NodeOutput | null>(() =>
  projectScientificPresentation(rawNodeOutput.value, selectedPresentation.value),
);

watch(
  () => [
    rawNodeOutput.value?.primary_port,
    Object.keys(rawNodeOutput.value?.ports ?? {}).join("|"),
    rawNodeOutput.value?.presentation_contract?.digest,
  ],
  () => {
    const preferred =
      nodeData.value?.selectedPresentationId ??
      rawNodeOutput.value?.presentation_contract?.payload.default_presentation;
    const available = new Set(presentationOptions.value.map((item) => item.value));
    selectedPresentationId.value =
      typeof preferred === "string" && available.has(preferred)
        ? preferred
        : (presentationOptions.value[0]?.value ?? preferred ?? null);
  },
  { immediate: true },
);
const quickPlotInputs = computed<Record<string, any>>(() =>
  Object.fromEntries(
    (nodeData.value?.inputConnections || []).map((connection: any) => [
      connection.toPort || "default",
      connection.data,
    ]),
  ),
);

// Training nodes emit `model_id` at the top level of their result after the
// executor's `_process_model_artifact` lift (executor.py:135). Surface that
// to the OutputPanel so it can render a Model Artifact section linking back
// to /runs?tab=4&artifact=<uid>.
const modelId = computed<string | null>(() => {
  const raw = (nodeOutput.value as Record<string, unknown> | null)?.model_id;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
});

// ── Parameter handling ──────────────────────────────────────────────────
const { displayedValidationErrors, hasValidationErrors, validateParams, getParamError } =
  useNodeValidation(workflowStore, nodeType, localParams);

watch(localParams, () => validateParams(), { deep: true });
watch(
  () => workflowStore.isLoadingNodeLibrary,
  (loading) => {
    if (!loading && workflowStore.nodeLibrary.size > 0) validateParams();
  },
);

const mapMetadataParams = (_nodeType: string, parameters: any[]): any[] =>
  parameters.map((p) => ({
    name: p.name,
    label: p.label,
    type: p.param_type,
    min: p.min_value,
    max: p.max_value,
    step: p.step,
    options: p.options?.map((o: any) => (typeof o === "string" ? { label: o, value: o } : o)),
    description: p.description,
    default: p.default,
    required: p.required,
    category: p.category,
    visible_when: p.visible_when || null,
  }));

const isParamVisible = (param: any): boolean => {
  if (!param.visible_when) return true;
  for (const [ctrl, allowed] of Object.entries(param.visible_when)) {
    if (!(allowed as string[]).includes(String(localParams.value[ctrl] ?? ""))) return false;
  }
  return true;
};

const nodeParams = computed(() => {
  const params = nodeMetadata.value?.parameters?.length
    ? mapMetadataParams(nodeType.value, nodeMetadata.value.parameters)
    : nodeData.value?.paramDefinitions || [];
  return params.filter(
    (param: any) => isUserEditableNodeParameter(param) && isParamVisible(param),
  );
});
const settingsCount = computed(() => nodeParams.value.length);

// ── Output composable ───────────────────────────────────────────────────
const { normalizeNodeOutput, resolvePortPayload } = useNodeOutput(nodeOutput, nodeMetadata);

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
  isRegressionComparison,
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
  previewRowLimit: 50,
});

watch(
  [isPCAOutput, hasOutput, selectedPresentationId],
  ([pcaOutput, outputAvailable, presentationId]) => {
    if (!pcaOutput || !outputAvailable) return;
    sections.value.plots = true;
    for (const key of ["pcaScores", "pcaBiplot", "pcaLoadings", "pcaScree", "pcaDiagnostics"]) {
      plotSections.value[key] = false;
    }
    if (presentationId === "loadings") {
      plotSections.value.pcaLoadings = true;
    } else if (presentationId === "explained_variance") {
      plotSections.value.pcaScree = true;
    } else if (presentationId === "diagnostics") {
      plotSections.value.pcaDiagnostics = true;
    } else {
      // Scores plus scree are the minimum PCA interpretation view: where the
      // samples sit and how much variance those axes represent.
      plotSections.value.pcaScores = true;
      plotSections.value.pcaScree = true;
    }
  },
  { immediate: true },
);

watch(
  [nodeTypeKey, hasOutput],
  ([type, outputAvailable]) => {
    if (!outputAvailable || !["data.file_load", "data.collection_load"].includes(type)) return;
    sections.value.output = true;
    sections.value.plots = true;
    plotSections.value.spectraOverview = true;
    plotSections.value.dataOverview = true;
  },
  { immediate: true },
);

watch(
  [nodeTypeKey, hasOutput, selectedPresentationId],
  ([type, outputAvailable]) => {
    if (!outputAvailable || type !== "analysis.peak_finding") return;
    sections.value.plots = true;
    plotSections.value.peakFinding = true;
  },
  { immediate: true },
);

// ── Plot composable (owns all plot data/layout computeds + derived flags) ──
const { plotBag, handleContourClick } = useNodePlotData({
  nodeOutput,
  nodeType,
  nodeTypeKey,
  hasOutput,
  isPCAOutput,
  pcaXAxis,
  pcaYAxis,
  scoreColorMode,
  sampleColorField,
  sampleSymbolField,
  selectedFeatureScale,
  selectedFeatureLabels,
  selectedFeatureTitle,
  selectedSampleLabels,
  plsdaLoadingsViewMode,
  featureXAxis,
  featureYAxis,
  contourClickPoint,
  regressionTargetOptions,
});

// ── Actions ─────────────────────────────────────────────────────────────
const resetToDefaults = () => {
  for (const p of nodeParams.value) {
    if (p.default !== undefined) localParams.value[p.name] = p.default;
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

const exportOutput = async () => {
  if (nodeType.value === "output.export") {
    try {
      const artifact = await downloadExportArtifact(extractExportArtifact(nodeOutput.value));
      toast.add({
        severity: "success",
        summary: "Prepared export downloaded",
        detail: `${artifact.filename} (${artifact.content_sha256.slice(0, 12)}…)`,
        life: 3000,
      });
    } catch (error) {
      toast.add({
        severity: "error",
        summary: "Export verification failed",
        detail: error instanceof Error ? error.message : "Prepared export is invalid",
        life: 5000,
      });
    }
    return;
  }
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return;
  const csv = Array.isArray(data[0])
    ? data.map((row) => (Array.isArray(row) ? row.join(",") : String(row))).join("\n")
    : data.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${nodeLabel.value.replace(/\s+/g, "_")}_output.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

const handleCancel = () => {
  if (embedded.value) {
    emit("close");
    return;
  }
  window.close();
};

const { isExecuting, broadcastParamsUpdate, waitForParamsAck, handleRunTrial } = useNodeTrial({
  nodeData,
  localParams,
  nodeType,
  addLog,
  normalizeNodeOutput,
  validateTrial: () => workflowStore.assertNumericExecutionInputs(
    String(nodeData.value?.id), localParams.value,
    nodeData.value?.workflowNodes || [], nodeData.value?.workflowEdges || [],
  ),
  toast,
});

const handleSaveAndExit = async () => {
  (document.activeElement as HTMLElement | null)?.blur();
  await nextTick();
  if (embedded.value) {
    emit(
      "save",
      String(nodeData.value?.id ?? nodeId.value),
      cloneNodeDetailParams(localParams.value),
    );
    return;
  }
  const requestId = broadcastParamsUpdate();
  const ack = await waitForParamsAck(requestId);
  if (!ack.applied) {
    toast.add({
      severity: "warn",
      summary: "Save Not Confirmed",
      detail: "Couldn't reach the workflow tab. Reopen the workflow and try again.",
      life: 6000,
    });
    return;
  }
  toast.add({
    severity: "success",
    summary: "Saved",
    detail: "Settings applied to the workflow",
    life: 1500,
  });
  setTimeout(() => {
    try {
      window.close();
    } catch {
      /* no-op */
    }
    setTimeout(() => {
      if (!window.closed) {
        if (window.opener && !window.opener.closed) {
          try {
            window.opener.focus();
          } catch {
            /* cross-origin */
          }
        }
        toast.add({
          severity: "info",
          summary: "Settings applied",
          detail: "You may close this tab — changes are live in the workflow.",
          life: 6000,
        });
      }
    }, 400);
  }, 500);
};

// ── Lifecycle ───────────────────────────────────────────────────────────
onMounted(async () => {
  const sourceData = props.initialNodeData ?? sessionStorage.getItem(STORAGE_KEY);
  if (sourceData) {
    try {
      const parsed = resolveNodeDetailPayload(
        props.initialNodeData,
        sessionStorage.getItem(STORAGE_KEY),
      );
      if (!parsed) throw new TypeError("node detail payload is missing");
      // Embedded trial sheets already own an in-memory payload. Do not force
      // that reactive object through JSON solely to read it; canonical result
      // ports may be large, and JSON is the fallback transport for a separate
      // browser tab rather than the state authority for an embedded sheet.
      nodeData.value = parsed;
      const storedProjectId = (nodeData.value as any)?.projectId;
      if (
        typeof storedProjectId === "number" &&
        storedProjectId > 0 &&
        projectStore.currentProjectId !== storedProjectId
      ) {
        await projectStore.selectProject(storedProjectId);
      }
      const defaults: Record<string, any> = {};
      for (const p of nodeParams.value || []) {
        if (p.default !== undefined) defaults[p.name] = p.default;
      }
      localParams.value = cloneNodeDetailParams({
        ...defaults,
        ...(nodeData.value.params || {}),
      });
      originalParams.value = cloneNodeDetailParams(localParams.value);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "unknown node-detail payload error";
      console.error("Failed to load node detail payload:", error);
      toast.add({
        severity: "error",
        summary: "Error",
        detail: `Failed to load node data: ${detail}`,
        life: 5000,
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

// ── Provide canonical state to descendant panels ────────────────────────
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
    presentationOptions,
    presentationError,
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
    isRegressionComparison,
    regressionTargetOptions,
    selectedRegressionR2,
    selectedRegressionRmse,
    modelId,
    getMetaTooltip,
    formatMetaValue,
  },
  plots: plotBag,
  writable: {
    selectedPresentationId,
    pcaXAxis,
    pcaYAxis,
    scoreColorMode,
    sampleColorField,
    sampleSymbolField,
    selectedFeatureScale,
    selectedFeatureLabels,
    selectedFeatureTitle,
    selectedSampleLabels,
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

.node-detail-view.embedded {
  min-height: 100%;
  width: 100%;
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

.node-instance-id {
  display: block;
  margin-top: 3px;
  color: #cbd5e1;
  font-size: 0.75rem;
}

.node-type-badge {
  display: block;
  width: fit-content;
  margin-top: 4px;
  padding: 2px 10px;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.detail-content {
  max-width: 1600px;
  margin: 0 auto;
  padding: 32px;
}

.two-column-layout {
  display: grid;
  grid-template-columns: minmax(400px, 1fr) minmax(400px, 1.2fr);
  gap: 24px;
  align-items: start;
}

.column-left,
.column-right {
  display: flex;
  flex-direction: column;
  gap: 16px;
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

@media (max-width: 1100px) {
  .two-column-layout {
    grid-template-columns: 1fr;
  }
}
</style>
