<template>
  <div class="node-detail-view" :class="{ embedded }">
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

const props = withDefaults(defineProps<{
  initialNodeData?: any | null;
  embedded?: boolean;
}>(), {
  initialNodeData: null,
  embedded: false,
});

const emit = defineEmits<{
  (event: "save", nodeId: string, params: Record<string, unknown>): void;
  (event: "close"): void;
}>();

// ── Section collapse state ──────────────────────────────────────────────
const {
  sections, outputSubsections, plotSections,
  toggleSection, toggleOutputSubsection, togglePlot,
} = useNodeSections();

// ── Execution log entries ───────────────────────────────────────────────
const { executionLogs, addLog, clearLogs, getLogIcon } = useNodeLog();

// ── Writable refs for panel v-model-style updates ───────────────────────
const plsdaLoadingsViewMode = ref<"lines" | "biplot">("lines");
const regressionTargetIdx = ref(0);
const pcaXAxis = ref(0);
const pcaYAxis = ref(1);
const scoreColorMode = ref("labels");
const spectraDisplayMode = ref<"overlay" | "contour">("contour");
const genericDisplayMode = ref<"boxplot" | "scatter">("boxplot");
const featureXAxis = ref(0);
const featureYAxis = ref(1);
const contourClickPoint = ref<
  { sampleIdx: number; wavenumberIdx: number; wavenumber: number } | null
>(null);

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

const cloneParams = (params: Record<string, any>): Record<string, any> => {
  if (typeof structuredClone === "function") {
    return structuredClone(params);
  }
  return JSON.parse(JSON.stringify(params));
};

const NODE_ICONS: Record<string, string> = {
  "data.source": "📊", "data.my_dataset": "🧪", "preprocess.normalize": "📏", "preprocess.scale": "📏",
  "baseline.penalized_ls": "📉", "preprocess.smooth": "〰️", "model.pca": "🔀",
  "model.pls": "📈", "model.mcr_als": "🧩", "stats.summary": "📊",
  "analysis.peak_finding": "⛰️", "analysis.peak_id": "🔬", "analysis.compare_library": "📚",
  "output.plot": "📈", "output.contour": "🗺️", "output.export": "💾",
};

const embedded = computed(() => props.embedded);
const nodeId = computed(() => String(props.initialNodeData?.id ?? route.params.nodeId ?? ""));
const nodeType = computed(() => nodeData.value?.type || "Unknown");
const nodeTypeKey = computed(() => nodeType.value);
const nodeLabel = computed(() => nodeData.value?.label || `Node ${nodeId.value}`);
const nodeIcon = computed(() => NODE_ICONS[nodeType.value] || "📦");
const nodeMetadata = computed(() => workflowStore.getNodeMetadata(nodeType.value));
const nodeOutput = computed(() => nodeData.value?.output || null);

// Training nodes emit `model_id` at the top level of their result after the
// executor's `_process_model_artifact` lift (executor.py:135). Surface that
// to the OutputPanel so it can render a Model Artifact section linking back
// to /runs?tab=4&artifact=<uid>.
const modelId = computed<string | null>(() => {
  const raw = (nodeOutput.value as Record<string, unknown> | null)?.model_id;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
});

// ── Parameter handling ──────────────────────────────────────────────────
const {
  displayedValidationErrors, hasValidationErrors, validateParams, getParamError,
} = useNodeValidation(workflowStore, nodeType, localParams);

watch(localParams, () => validateParams(), { deep: true });
watch(
  () => workflowStore.isLoadingNodeLibrary,
  (loading) => { if (!loading && workflowStore.nodeLibrary.size > 0) validateParams(); },
);

const mapMetadataParams = (_nodeType: string, parameters: any[]): any[] =>
  parameters.map((p) => ({
    name: p.name, label: p.label, type: p.param_type,
    min: p.min_value, max: p.max_value, step: p.step,
    options: p.options?.map((o: any) => typeof o === "string" ? { label: o, value: o } : o),
    description: p.description, default: p.default, required: p.required,
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
  return params.filter(isParamVisible);
});
const settingsCount = computed(() => nodeParams.value.length);

// ── Output composable ───────────────────────────────────────────────────
const { normalizeNodeOutput, resolvePortPayload } = useNodeOutput(nodeOutput, nodeMetadata);

const {
  hasInput, hasOutput, inputSummary, outputSummary, inputConnections, inputData,
  outputData, outputMetadata, datasetInfo, datasetLabelTable, labelPreviewLimit,
  processingHistory, provenanceInfo, qualitySummary, isRegressionNode, isPCAOutput,
  portSummaries, fullMetadataJson, getMetaTooltip, formatMetaValue,
  inputPreview, inputPreviewColumns, inputDataSummary,
  outputPreview, outputPreviewColumns, outputDataSummary,
  pcaDiagnosticsPreview, pcaDiagnosticsColumns, pcaDiagSummary,
  regressionTargetOptions, selectedRegressionR2, selectedRegressionRmse,
} = useNodeOutputData({
  nodeOutput, nodeData, nodeTypeKey, resolvePortPayload,
  regressionTargetIdx, previewRowLimit: 50,
});

// ── Plot composable (owns all plot data/layout computeds + derived flags) ──
const { plotBag, handleContourClick } = useNodePlotData({
  nodeOutput, nodeType, nodeTypeKey, hasOutput, isPCAOutput,
  pcaXAxis, pcaYAxis, scoreColorMode, plsdaLoadingsViewMode, regressionTargetIdx,
  featureXAxis, featureYAxis, contourClickPoint,
  regressionTargetOptions, selectedRegressionR2, selectedRegressionRmse,
});

// ── Actions ─────────────────────────────────────────────────────────────
const resetToDefaults = () => {
  for (const p of nodeParams.value) {
    if (p.default !== undefined) localParams.value[p.name] = p.default;
  }
  toast.add({ severity: "info", summary: "Reset", detail: "Parameters reset to defaults", life: 2000 });
};

const openDataTable = () => { showDataTableModal.value = true; };
const openQuickPlot = () => {
  if (nodeType.value === "output.data_table") return;
  showQuickPlotModal.value = true;
};

const exportOutput = () => {
  const data = nodeOutput.value?.data;
  if (!data || !Array.isArray(data)) return;
  const csv = Array.isArray(data[0])
    ? data.map((row: any[]) => row.join(",")).join("\n")
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
  nodeData, localParams, nodeType, addLog, normalizeNodeOutput, toast,
});

const handleSaveAndExit = async () => {
  (document.activeElement as HTMLElement | null)?.blur();
  await nextTick();
  if (embedded.value) {
    emit("save", String(nodeData.value?.id ?? nodeId.value), cloneParams(localParams.value));
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
  toast.add({ severity: "success", summary: "Saved", detail: "Settings applied to the workflow", life: 1500 });
  setTimeout(() => {
    try { window.close(); } catch { /* no-op */ }
    setTimeout(() => {
      if (!window.closed) {
        if (window.opener && !window.opener.closed) {
          try { window.opener.focus(); } catch { /* cross-origin */ }
        }
        toast.add({ severity: "info", summary: "Settings applied", detail: "You may close this tab — changes are live in the workflow.", life: 6000 });
      }
    }, 400);
  }, 500);
};

// ── Lifecycle ───────────────────────────────────────────────────────────
onMounted(() => {
  const storedData = props.initialNodeData ? JSON.stringify(props.initialNodeData) : sessionStorage.getItem(STORAGE_KEY);
  if (storedData) {
    try {
      nodeData.value = JSON.parse(storedData);
      const storedProjectId = (nodeData.value as any)?.projectId;
      if (typeof storedProjectId === "number" && storedProjectId > 0) {
        projectStore.selectProject(storedProjectId);
      }
      const defaults: Record<string, any> = {};
      for (const p of nodeParams.value || []) {
        if (p.default !== undefined) defaults[p.name] = p.default;
      }
      localParams.value = cloneParams({ ...defaults, ...nodeData.value.params });
      originalParams.value = cloneParams(localParams.value);
    } catch (e) {
      console.error("Failed to parse node data from session storage:", e);
      toast.add({ severity: "error", summary: "Error", detail: "Failed to load node data", life: 3000 });
    }
  } else {
    toast.add({ severity: "warn", summary: "No Data", detail: "No node data found. Please open from the workflow inspector.", life: 5000 });
  }
});

// ── Provide canonical state to descendant panels ────────────────────────
const detailState: NodeDetailState = {
  output: {
    summary: outputSummary, hasOutput, data: outputData, metadata: outputMetadata,
    subsections: outputSubsections, datasetInfo, datasetLabelTable, labelPreviewLimit,
    processingHistory, provenance: provenanceInfo, quality: qualitySummary, portSummaries,
    preview: computed(() => ({ rows: outputPreview.value, columns: outputPreviewColumns.value, summary: outputDataSummary.value })),
    pcaDiagnostics: computed(() => ({ rows: pcaDiagnosticsPreview.value, columns: pcaDiagnosticsColumns.value, summary: pcaDiagSummary.value })),
    isRegressionNode, regressionTargetOptions, selectedRegressionR2, selectedRegressionRmse,
    modelId,
    getMetaTooltip, formatMetaValue,
  },
  plots: plotBag,
  writable: {
    pcaXAxis, pcaYAxis, scoreColorMode, plsdaLoadingsViewMode, regressionTargetIdx,
    spectraDisplayMode, genericDisplayMode, featureXAxis, featureYAxis, contourClickPoint,
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

.column-left, .column-right {
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
