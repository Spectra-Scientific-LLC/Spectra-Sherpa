<template>
  <section class="workflow-builder-content">
    <WorkspaceHeader title="Workflow" :actions="actionMenuItems">
      <template #badge>
        <span
          v-if="isManagedCandidateAuthority"
          class="workflow-meta-badge"
          title="Persisted candidate DAG for governed Harness execution; inspectable but not runnable from the canvas"
        >
          <i class="pi pi-shield"></i>
          Harness authority
        </span>
      </template>
        <div class="toolbar-action-group">
          <Button
            label="Analysis Starter"
            icon="pi pi-sparkles"
            class="p-button-outlined p-button-sm"
            :disabled="isTrialTabActive || (pendingDataSelection && !dataSelectionReceipt)"
            :title="
              pendingDataSelection && !dataSelectionReceipt
                ? 'Return to My Dataset to restore the missing selection receipt'
                : undefined
            "
            @click="openTemplatePicker"
          />
          <Button
            :label="isWorkflowStale ? 'Run (Mod)' : 'Run'"
            icon="pi pi-play"
            data-action="run_workflow"
            class="p-button-outlined p-button-sm"
            :loading="isExecuting || isBatchExecuting"
            :disabled="
              isTrialTabActive ||
              isManagedCandidateAuthority ||
              pendingDataSelection ||
              nodes.length === 0 ||
              workflowParameterErrors.length > 0 ||
              isExecuting ||
              isBatchExecuting
            "
            @click="onRunClick"
            :title="runButtonTitle"
          />
          <Button
            label="Export"
            icon="pi pi-download"
            class="p-button-outlined p-button-sm"
            :disabled="isTrialTabActive"
            @click="toggleExportMenu"
          />
          <Button
            label="Audit"
            icon="pi pi-shield"
            class="p-button-outlined p-button-sm"
            :disabled="isTrialTabActive || workflowStore.workflowId === null"
            @click="openWorkflowAudit"
            title="Open audit trail for this workflow"
          />
        </div>
        <Menu ref="exportMenuRef" :model="exportMenuItems" :popup="true" />

        <template #after>
          <span v-if="autosaveStatus === 'saving'" class="autosave-indicator">
            <i class="pi pi-spin pi-spinner"></i> Saving
          </span>
          <span v-else-if="autosaveStatus === 'saved'" class="autosave-indicator">
            <i class="pi pi-check"></i> Saved
          </span>
          <span
            v-else-if="autosaveStatus === 'error'"
            class="autosave-indicator autosave-indicator-error"
            :title="autosaveErrorMessage"
          >
            <i class="pi pi-exclamation-triangle"></i> Save failed
          </span>

          <Button
            icon="pi pi-cog"
            class="p-button-outlined p-button-sm toolbar-settings-btn"
            title="Settings"
            aria-label="Settings"
            @click="toggleSettingsPanel"
          />
          <OverlayPanel ref="settingsPanelRef">
            <div class="settings-panel-content">
              <label
                v-if="!hasExpensiveAutoExecuteNodes"
                class="toolbar-state-control"
                title="Auto-execute on connect/param change for descriptive workflows"
              >
                <Checkbox
                  v-model="autoExecute"
                  binary
                  input-id="workflow-auto-update"
                  :disabled="isManagedCandidateAuthority"
                  @change="onAutoExecuteChange"
                />
                <span>Auto update</span>
              </label>
              <small v-else class="toolbar-settings-note">
                Modeling and selection workflows require an explicit Run.
              </small>
              <label
                class="toolbar-state-control"
                title="Run all scientist-facing analysis sheets in the workbook sequentially"
              >
                <Checkbox v-model="runAllSheets" binary input-id="workflow-run-all" />
                <span>Run all analysis sheets</span>
              </label>
              <label
                v-if="runAllSheets"
                class="toolbar-state-control"
                title="Continue running remaining sheets if one sheet fails"
              >
                <Checkbox
                  v-model="continueWorkbookOnError"
                  binary
                  input-id="workflow-run-all-continue"
                />
                <span>Continue on error</span>
              </label>
            </div>
          </OverlayPanel>
        </template>
    </WorkspaceHeader>

    <p v-if="workflowContextLoading" role="status" aria-label="Loading workflow">Loading workflow…</p>
    <p v-if="!workflowContextLoading && workflowStore.hasFoldValidationPlan" role="status" aria-label="Validated workflow export">
      This campaign-derived sheet has a cross-validation plan. A project archive preserves the sheet, but is not a deployable campaign winner. For an application, use a signed Model package when Optimize offers one for a selected, refitted winner. Standalone Python, notebook, and ZIP exports cannot preserve this validation plan.
    </p>
    <aside v-if="!workflowContextLoading && workflowStore.workflowWarnings.length" role="status" aria-label="Workflow warnings">
      <p v-for="warning in workflowStore.workflowWarnings" :key="warning">{{ warning }}</p>
    </aside>

    <section
      v-if="!workflowContextLoading && pendingDataSelection && !dataSelectionReceipt"
      class="workflow-data-selection pending invalid"
      aria-label="My Dataset selection unavailable"
      role="alert"
    >
      <i class="pi pi-exclamation-triangle" aria-hidden="true" />
      <div>
        <strong>The incoming data selection is unavailable</strong>
        <span>
          Its navigation receipt is missing, expired, or belongs to another browser tab. Return to
          My Dataset and choose Next: Workflow again.
        </span>
      </div>
      <Button
        label="Return to My Dataset"
        icon="pi pi-arrow-left"
        class="p-button-sm p-button-outlined"
        @click="router.push('/data?tab=my-dataset')"
      />
    </section>

    <section
      v-else-if="dataSelectionReceipt"
      class="workflow-data-selection"
      :class="{ pending: pendingDataSelection }"
      aria-label="My Dataset selection"
    >
      <i :class="pendingDataSelection ? 'pi pi-clock' : 'pi pi-check-circle'" aria-hidden="true" />
      <div>
        <strong
          >{{ dataSelectionFileCount }} selected file{{
            dataSelectionFileCount === 1 ? "" : "s"
          }}
          selected</strong
        >
        <span>
          From {{ dataSelectionReceipt.datasets.length }} dataset{{
            dataSelectionReceipt.datasets.length === 1 ? "" : "s"
          }}. This exact selection is waiting for Analysis Starter to create a bound sheet{{
            dataSelectionReceipt.group
              ? `, with ${dataSelectionReceipt.group} requested for grouping`
              : ""
          }}.
        </span>
      </div>
      <Button
        label="Choose Analysis Starter"
        icon="pi pi-sparkles"
        class="p-button-sm p-button-outlined"
        @click="openTemplatePicker"
      />
    </section>

    <VersionHistoryDialog
      v-model:visible="versionHistoryVisible"
      :workflow-id="workflowStore.workflowId"
      @sheet-opened="resetDialogOpenedSheetUi"
    />

    <TemplatePickerDialog
      v-model:visible="templatePickerVisible"
      :data-selection="dataSelectionReceipt"
      :preferred-template-slug="preferredAnalysisStarterSlug"
      @sheet-opened="onTemplateSheetOpened"
    />

    <WorkspaceContext label="Workflow workspace context" layout="workflow">
      <WorkspaceContextItem label="Active Sheet" :value="activeSheetName" />
      <WorkspaceContextItem label="Active Data" :value="linkedDataLabel" :detail="linkedDataTitle" />
      <WorkspaceContextItem label="Canvas" :value="canvasSummaryLabel" />
    </WorkspaceContext>

    <!-- Execution status banner -->
    <div v-if="executionCount > 0" class="execution-banner">
      <i class="pi pi-check-circle"></i>
      <span>Workflow executed {{ executionCount }} time{{ executionCount !== 1 ? "s" : "" }}</span>
      <span v-if="lastExecutionTime" class="execution-time">Last run: {{ lastExecutionTime }}</span>
    </div>

    <div v-if="recentlyDeletedSnapshot" class="node-undo-banner" role="status">
      <span>{{ recentlyDeletedSnapshot.label }} deleted</span>
      <Button
        label="Undo"
        icon="pi pi-undo"
        class="p-button-text p-button-sm"
        @click="restoreDeletedNodes"
      />
    </div>

    <!-- Three-column layout: Toolbar | Canvas | Inspector Sidebar -->
    <div
      class="workflow-workspace"
      :class="{
        'inspector-open': inspectorOpen,
        'toolbar-collapsed': toolbarCollapsed,
        'catalog-open': toolbarCatalogOpen,
        'trial-active': isTrialTabActive,
      }"
    >
      <WorkflowToolbar
        v-show="!isTrialTabActive"
        :class="{ 'trial-hidden': isTrialTabActive }"
        @add-node="onAddNode"
        @toggle-collapsed="onToolbarCollapsedChange"
        @view-mode="onToolbarViewModeChange"
      />

      <!-- Center: Canvas -->
      <div class="canvas-stack">
        <WorkbookSheetTabs
          v-if="workbookStore.sheets.length > 0"
          class="canvas-sheet-tabs"
          :sheets="workbookStore.sheets"
          :active-index="workbookStore.activeIndex"
          :has-unsaved-changes="workflowStore.hasUnsavedChanges"
          :active-workflow-hash="workflowStore.workflowHash"
          @switch="switchWorkbookSheet"
          @add="addWorkbookSheet"
          @duplicate="duplicateWorkbookSheet"
          @open-template-picker="openTemplatePicker"
          @rename="renameWorkbookSheet"
          @copy-integrity="copyWorkflowIntegrity"
          @export-png="exportSheetPng"
          @color="colorWorkbookSheet"
          @reorder="reorderWorkbookSheets"
          @delete="deleteWorkbookSheet"
        />
        <div
          v-else-if="workbookStore.isLoading"
          class="canvas-sheet-tabs sheet-tabs-skeleton"
          aria-hidden="true"
        >
          <div class="skeleton-tab"></div>
          <div class="skeleton-tab skeleton-tab-narrow"></div>
        </div>
        <div
          class="canvas-container"
          :class="{
            'with-sheet-tabs': workbookStore.sheets.length > 0,
            'trial-container': isTrialTabActive,
          }"
        >
          <NodeDetailView
            v-if="workbookStore.activeTrialSheet"
            :key="workbookStore.activeTrialSheet.trialId"
            embedded
            :initial-node-data="workbookStore.activeTrialSheet.trialData"
            @save="saveTrialParams"
            @close="closeActiveTrialTab"
          />
          <WorkflowCanvas
            v-else
            ref="canvasRef"
            :nodes="nodes"
            :edges="edges"
            :node-outputs="nodeOutputs"
            @update:nodes="onNodesUpdate"
            @update:edges="onEdgesUpdate"
            @node-select="onNodeSelect"
            @node-connect="onNodeConnect"
            @connection-error="onConnectionError"
            @run-node="onRunNode"
            @view-output="onViewOutput"
            @cut-selection="onCutSelection"
            @copy-selection="onCopySelection"
            @paste-selection="onPasteSelection"
            @duplicate-selection="onDuplicateSelection"
            @delete-selection="onDeleteSelection"
          />
        </div>
      </div>

      <!-- Right Panel: Inspector Sidebar (persistent until closed). Hidden during trial tabs.
           v-show (not v-if) keeps it pre-mounted so there is no mount delay on the first click;
           display:none from v-show removes it from grid flow when hidden, preventing the phantom
           third-row that appeared with the old v-show="!isTrialTabActive" approach. -->
      <WorkflowInspector
        v-show="inspectorOpen && !isTrialTabActive"
        :class="{ 'trial-hidden': isTrialTabActive }"
        :selected-node="selectedNode"
        :node-output="selectedNodeOutput"
        :input-connections="selectedNodeInputConnections"
        :is-open="inspectorOpen"
        :execution-disabled="isManagedCandidateAuthority || pendingDataSelection"
        :execution-disabled-reason="
          pendingDataSelection
            ? 'Choose an Analysis Starter to bind the incoming My Dataset selection before running.'
            : 'Managed candidate authority is inspectable here, but only the governed Harness may execute it.'
        "
        @update-params="onUpdateParams"
        @execute-node="onExecuteNode"
        @delete-node="onDeleteNode"
        @open-trial="openTrialTab"
        @close="onCloseInspector"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- builder canvas mixes generic node-library metadata with loose drag/drop payloads. */
import { ref, computed, provide, watch, onMounted, onUnmounted, nextTick } from "vue";
import { storeToRefs } from "pinia";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Menu from "primevue/menu";
import OverlayPanel from "primevue/overlaypanel";
import { useToast } from "primevue/usetoast";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import { useWorkflowStore, type WorkflowNode, type WorkflowEdge } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import { useProjectStore } from "@/stores/project";
import { useWorkbookStore } from "@/stores/workbook";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowBuilderConfigStore } from "@/stores/workflowBuilderConfig";
import { useClipboardStore, type ClipboardPayload } from "@/stores/clipboard";
import WorkbookSheetTabs from "@/components/WorkbookSheetTabs.vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import VersionHistoryDialog from "@/components/VersionHistoryDialog.vue";
import TemplatePickerDialog from "@/components/TemplatePickerDialog.vue";
import WorkflowToolbar from "./WorkflowToolbar.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import WorkflowInspector from "./WorkflowInspector.vue";
import NodeDetailView from "./NodeDetailView.vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import { downloadText } from "@/utils/download";
import { getErrorMessage } from "@/utils/errors";
import { activeWorkflowQuery } from "@/utils/workflowDeepLink";
import {
  editableWorkflowGraph,
  workflowDraftKey,
  workflowDraftSignature,
} from "@/utils/workflowDraft";
import {
  consumeDataSelectionReceipt,
  loadDataSelectionReceipt,
  type DataSelectionReceipt,
} from "@/utils/workflowDataSelection";
import { handleBroadcastMessage as _handleBroadcastMessage } from "./handleBroadcastMessage";

type ParamsMap = Record<string, unknown>;

type DeletedWorkflowSnapshot = {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  outputs: Array<[string, NodeOutput]>;
  selectedNodeId: string | null;
  label: string;
};

const toast = useToast();
const route = useRoute();
const router = useRouter();
const workflowStore = useWorkflowStore();
const experimentStore = useExperimentStore();
const projectStore = useProjectStore();
const workbookStore = useWorkbookStore();
const authStore = useAuthStore();
const workflowBuilderConfigStore = useWorkflowBuilderConfigStore();
const { autoExecute } = storeToRefs(workflowBuilderConfigStore);
const clipboardStore = useClipboardStore();
const versionHistoryVisible = ref(false);
const templatePickerVisible = ref(false);
const canvasRef = ref();
const exportMenuRef = ref();
const settingsPanelRef = ref();
const RETIRED_DATA_SELECTION_STORAGE_KEY = "spectra-my-dataset-workflow-selection-v1";
const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";
const DATA_ENTRY_DATASET_KEY = "sherpa:data-entry-dataset-intent";

type AnalysisStarterDatasetIntent = {
  schema_version: "spectra-analysis-starter-dataset-intent/1";
  project_id: number;
  dataset_id: string;
  source: string;
  name: string;
  label: string;
  template_slug: string | null;
  imported_experiment_id?: number | null;
};

function readDataSelectionReceipt(
  options: { requireRouteFlag?: boolean } = {},
): DataSelectionReceipt | null {
  window.sessionStorage.removeItem(RETIRED_DATA_SELECTION_STORAGE_KEY);
  if (options.requireRouteFlag && route.query.fromDataSelection !== "1") return null;
  try {
    const routeReceiptId =
      typeof route.query.selection === "string" ? route.query.selection : null;
    if (options.requireRouteFlag && !routeReceiptId) return null;
    const value = loadDataSelectionReceipt(
      options.requireRouteFlag ? routeReceiptId : null,
    );
    if (
      value?.schema_version !== "spectra-my-dataset-workflow-selection/3" ||
      typeof value.receipt_id !== "string" ||
      !value.receipt_id ||
      !Array.isArray(value.datasets) ||
      value.datasets.length === 0 ||
      !value.datasets.every((dataset) =>
        ["raw", "preprocessed", "synthetic"].includes(dataset.stage),
      ) ||
      value.project_id !== projectStore.currentProjectId
    ) {
      return null;
    }
    if (
      options.requireRouteFlag &&
      routeReceiptId !== value.receipt_id
    ) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

const dataSelectionReceipt = ref<DataSelectionReceipt | null>(
  readDataSelectionReceipt({ requireRouteFlag: true }),
);
// A missing receipt cannot be diagnosed until the routed project has loaded.
// Also suppress notices retained from the previous sheet during navigation.
const workbookContextReady = ref(false);
const workflowContextLoading = computed(() =>
  !workbookContextReady.value || workbookStore.isLoading || workflowStore.isLoading,
);
const preferredAnalysisStarterSlug = ref<string | null>(null);
const dataSelectionFileCount = computed(() =>
  (dataSelectionReceipt.value?.datasets ?? []).reduce(
    (total, dataset) => total + dataset.selected_file_count,
    0,
  ),
);
const pendingDataSelection = computed(() => route.query.fromDataSelection === "1");

const openTemplatePicker = () => {
  preferredAnalysisStarterSlug.value = null;
  dataSelectionReceipt.value = readDataSelectionReceipt({
    requireRouteFlag: pendingDataSelection.value,
  });
  if (pendingDataSelection.value && !dataSelectionReceipt.value) return;
  templatePickerVisible.value = true;
};

function readAnalysisStarterIntent(): AnalysisStarterDatasetIntent | null {
  if (
    window.sessionStorage.getItem(DATA_ENTRY_MODE_KEY) !== "analysis-starter" ||
    window.sessionStorage.getItem(DATA_ENTRY_PROJECT_KEY) !==
      String(projectStore.currentProjectId ?? "")
  ) {
    return null;
  }
  try {
    const parsed = JSON.parse(window.sessionStorage.getItem(DATA_ENTRY_DATASET_KEY) || "null");
    if (
      parsed?.schema_version !== "spectra-analysis-starter-dataset-intent/1" ||
      parsed.project_id !== projectStore.currentProjectId ||
      typeof parsed.dataset_id !== "string" ||
      typeof parsed.source !== "string" ||
      typeof parsed.name !== "string" ||
      typeof parsed.label !== "string" ||
      (parsed.template_slug !== null && typeof parsed.template_slug !== "string")
    ) {
      return null;
    }
    return parsed as AnalysisStarterDatasetIntent;
  } catch {
    return null;
  }
}

function clearAnalysisStarterIntent(): void {
  if (window.sessionStorage.getItem(DATA_ENTRY_MODE_KEY) !== "analysis-starter") return;
  window.sessionStorage.removeItem(DATA_ENTRY_MODE_KEY);
  window.sessionStorage.removeItem(DATA_ENTRY_PROJECT_KEY);
  window.sessionStorage.removeItem(DATA_ENTRY_DATASET_KEY);
}

async function onTemplateSheetOpened(): Promise<void> {
  resetDialogOpenedSheetUi();
  clearAnalysisStarterIntent();
  const query = { ...route.query };
  if (query.fromDataSelection === "1") {
    delete query.fromDataSelection;
    delete query.selection;
    await router.replace({ query });
  }
  if (dataSelectionReceipt.value) {
    consumeDataSelectionReceipt(dataSelectionReceipt.value.receipt_id);
  }
  dataSelectionReceipt.value = null;
  if (projectStore.currentProjectId != null) {
    try {
      await projectStore.fetchProject(projectStore.currentProjectId);
    } catch {
      // The starter has already created and bound its sheet. A transient
      // project-summary refresh must not leave that completed handoff marked
      // pending or restore its one-time navigation receipt.
      console.warn("Failed to refresh project summary after opening workflow sheet");
    }
  }
}

// Use store for workflow state
const nodes = computed({
  get: () => workflowStore.nodes,
  set: (val) => workflowStore.setNodes(val),
});
const edges = computed({
  get: () => workflowStore.edges,
  set: (val) => workflowStore.setEdges(val),
});
const hasChanges = computed(() => workflowStore.hasUnsavedChanges);
const isWorkflowStale = computed(() => workflowStore.isWorkflowStale);
const workflowParameterErrors = computed(() =>
  workflowStore.nodes.flatMap((node) =>
    workflowStore
      .validateNodeParams(node.type, node.params)
      .filter((error) => error.param_name !== "_metadata")
      .map((error) => ({ ...error, nodeId: node.id })),
  ),
);

// Local state
const selectedNode = ref<WorkflowNode | null>(null);
const nodeOutputs = ref<Map<string, NodeOutput>>(new Map());
const inspectorOpen = ref(false);
// Mirrors WorkflowToolbar's collapsed state so the workspace grid can shrink the
// toolbar column to just the chevron strip. Initialized from localStorage so the
// layout matches the toolbar on first paint (no flash of expanded column).
const toolbarCollapsed = ref<boolean>(
  (() => {
    try {
      return (
        typeof localStorage !== "undefined" &&
        localStorage.getItem("workflow-toolbar-collapsed") === "1"
      );
    } catch {
      return false;
    }
  })(),
);
const onToolbarCollapsedChange = (collapsed: boolean) => {
  toolbarCollapsed.value = collapsed;
};
const toolbarCatalogOpen = ref(false);
const onToolbarViewModeChange = (mode: "add" | "catalog") => {
  toolbarCatalogOpen.value = mode === "catalog";
};
const runAllSheets = ref(false); // Run all sheets on clicking 'Run'
const continueWorkbookOnError = ref(true);
const isBatchExecuting = ref(false);

const toggleSettingsPanel = (event: Event) => {
  settingsPanelRef.value?.toggle(event);
};

// ----------------------------------------------------------------------------
// Keyboard & Clipboard Actions
// ----------------------------------------------------------------------------

const handleKeyDown = (e: KeyboardEvent) => {
  // skip if the focused element is an input, textarea, or contenteditable
  const target = e.target as HTMLElement;
  if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable) {
    return;
  }

  const isMac = navigator.platform.toUpperCase().indexOf("MAC") >= 0;
  const isCmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;
  const key = e.key.toLowerCase();
  const browserHasSelectedText = Boolean(window.getSelection()?.toString());

  if (isCmdOrCtrl && key === "c" && browserHasSelectedText) {
    return;
  }

  if (isCmdOrCtrl && key === "c") {
    onCopySelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === "x") {
    onCutSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === "v") {
    onPasteSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === "d") {
    onDuplicateSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === "a") {
    canvasRef.value?.selectAll();
    e.preventDefault();
  } else if (e.key === "Delete" || e.key === "Backspace") {
    onDeleteSelection();
    e.preventDefault();
  } else if (e.key === "Escape") {
    canvasRef.value?.clearSelection();
    e.preventDefault();
  }
};

const getSelectedNodes = () => {
  if (!canvasRef.value?.selectedNodeIds) return [];
  const selectedIds = canvasRef.value.selectedNodeIds;
  return workflowStore.nodes.filter((n) => selectedIds.has(n.id));
};

const getInternalEdges = (selectedIds: Set<string>) => {
  return workflowStore.edges.filter((e) => selectedIds.has(e.from) && selectedIds.has(e.to));
};

const onCopySelection = () => {
  if (!canvasRef.value?.selectedNodeIds) return;
  const selectedIds = canvasRef.value.selectedNodeIds;
  if (selectedIds.size === 0) return;

  const copiedNodes = getSelectedNodes();
  const copiedEdges = getInternalEdges(selectedIds);

  clipboardStore.set({
    nodes: copiedNodes,
    edges: copiedEdges,
    sourceWorkflowId: workflowStore.workflowId,
  });

  toast.add({
    severity: "info",
    summary: "Copied",
    detail: `${copiedNodes.length} node(s) copied to clipboard`,
    life: 2000,
  });
};

const onCutSelection = () => {
  onCopySelection();
  onDeleteSelection();
};

const saveDeletedSnapshot = (snapshot: DeletedWorkflowSnapshot) => {
  clearDeleteUndoTimer();
  recentlyDeletedSnapshot.value = snapshot;
  deleteUndoTimer.value = window.setTimeout(() => {
    recentlyDeletedSnapshot.value = null;
    deleteUndoTimer.value = null;
  }, 8000);
};

const restoreDeletedNodes = () => {
  const snapshot = recentlyDeletedSnapshot.value;
  if (!snapshot) return;
  clearDeleteUndoTimer();
  const existingNodeIds = new Set(workflowStore.nodes.map((node) => node.id));
  const restoredNodes = snapshot.nodes.filter((node) => !existingNodeIds.has(node.id));
  if (restoredNodes.length === 0) {
    recentlyDeletedSnapshot.value = null;
    return;
  }
  const restoredNodeIds = new Set(restoredNodes.map((node) => node.id));
  const existingEdges = new Set(
    workflowStore.edges.map(
      (edge) => `${edge.from}->${edge.to}:${edge.fromPort || ""}:${edge.toPort || ""}`,
    ),
  );
  const restoredEdges = snapshot.edges.filter((edge) => {
    if (!restoredNodeIds.has(edge.from) && !restoredNodeIds.has(edge.to)) return false;
    const key = `${edge.from}->${edge.to}:${edge.fromPort || ""}:${edge.toPort || ""}`;
    return !existingEdges.has(key);
  });
  workflowStore.setNodes([...workflowStore.nodes, ...restoredNodes]);
  workflowStore.setEdges([...workflowStore.edges, ...restoredEdges]);
  const restoredOutputs = new Map(nodeOutputs.value);
  for (const [nodeId, output] of snapshot.outputs) {
    restoredOutputs.set(nodeId, output);
  }
  nodeOutputs.value = restoredOutputs;
  if (snapshot.selectedNodeId) {
    selectedNode.value =
      workflowStore.nodes.find((node) => node.id === snapshot.selectedNodeId) || null;
    inspectorOpen.value = selectedNode.value !== null;
  }
  workflowStore.hasUnsavedChanges = true;
  recentlyDeletedSnapshot.value = null;
  toast.add({
    severity: "success",
    summary: "Node Restored",
    detail: `${snapshot.label} restored to the canvas.`,
    life: 2500,
  });
};

const deleteNodesById = (ids: Set<string>, options: { requireConfirmation?: boolean } = {}) => {
  const requireConfirmation = options.requireConfirmation ?? true;
  if (ids.size === 0) return;
  const deletedNodes = workflowStore.nodes.filter((node) => ids.has(node.id));
  if (deletedNodes.length === 0) return;
  const label =
    deletedNodes.length === 1 ? getNodeLabel(deletedNodes[0].type) : `${deletedNodes.length} nodes`;
  if (
    requireConfirmation &&
    !window.confirm(`Delete ${label}? You can undo this immediately after deletion.`)
  ) {
    return;
  }
  const deletedEdges = workflowStore.edges.filter((edge) => ids.has(edge.from) || ids.has(edge.to));
  const deletedOutputs = Array.from(nodeOutputs.value.entries()).filter(([nodeId]) =>
    ids.has(nodeId),
  );
  const selectedNodeId =
    selectedNode.value && ids.has(selectedNode.value.id) ? selectedNode.value.id : null;

  workflowStore.setNodes(workflowStore.nodes.filter((node) => !ids.has(node.id)));
  workflowStore.setEdges(
    workflowStore.edges.filter((edge) => !ids.has(edge.from) && !ids.has(edge.to)),
  );
  const nextOutputs = new Map(nodeOutputs.value);
  for (const nodeId of ids) nextOutputs.delete(nodeId);
  nodeOutputs.value = nextOutputs;
  if (selectedNodeId) {
    selectedNode.value = null;
    inspectorOpen.value = false;
  }
  canvasRef.value?.clearSelection?.();
  workflowStore.hasUnsavedChanges = true;
  saveDeletedSnapshot({
    nodes: deletedNodes,
    edges: deletedEdges,
    outputs: deletedOutputs,
    selectedNodeId,
    label,
  });
};

const onDeleteSelection = () => {
  if (!canvasRef.value?.selectedNodeIds) return;
  const selectedIds = canvasRef.value.selectedNodeIds;
  if (selectedIds.size === 0) return;

  deleteNodesById(new Set(selectedIds));
};

let lastPasteCount = 0;
let lastClipboardHash = "";

const executePaste = (payload: ClipboardPayload, isDuplicate: boolean = false) => {
  if (!payload || payload.nodes.length === 0) return;

  // Track paste count to increment offset
  const hash = payload.nodes.map((n) => n.id).join(",");
  if (!isDuplicate) {
    if (hash === lastClipboardHash) {
      lastPasteCount++;
    } else {
      lastClipboardHash = hash;
      lastPasteCount = 1;
    }
  }

  const offsetX = isDuplicate ? 40 : 20 + lastPasteCount * 20;
  const offsetY = isDuplicate ? 40 : 20 + lastPasteCount * 20;

  const idMap = new Map<string, string>();
  const newNodes: WorkflowNode[] = [];
  const allNodes = [...workflowStore.nodes];

  payload.nodes.forEach((oldNode) => {
    const newId = createNodeId(oldNode.type, allNodes);
    idMap.set(oldNode.id, newId);

    const newNode = {
      ...oldNode,
      id: newId,
      x: oldNode.x + offsetX,
      y: oldNode.y + offsetY,
      executionState: undefined, // Clear state
    };
    newNodes.push(newNode);
    allNodes.push(newNode); // for next createNodeId iteration
  });

  const newEdges: WorkflowEdge[] = [];
  payload.edges.forEach((oldEdge) => {
    const newFrom = idMap.get(oldEdge.from);
    const newTo = idMap.get(oldEdge.to);
    if (newFrom && newTo) {
      newEdges.push({
        ...oldEdge,
        from: newFrom,
        to: newTo,
      });
    }
  });

  workflowStore.setNodes(allNodes);
  workflowStore.setEdges([...workflowStore.edges, ...newEdges]);
  workflowStore.hasUnsavedChanges = true;

  canvasRef.value?.clearSelection();
  newNodes.forEach((n) => canvasRef.value?.selectedNodeIds.add(n.id));

  if (newNodes.length === 1) {
    onNodeSelect(newNodes[0]);
  } else {
    onNodeSelect(null);
  }
};

const onPasteSelection = () => {
  const payload = clipboardStore.get();
  if (payload) {
    executePaste(payload, false);
  }
};

const onDuplicateSelection = () => {
  if (!canvasRef.value?.selectedNodeIds) return;
  const selectedIds = canvasRef.value.selectedNodeIds;
  if (selectedIds.size === 0) return;

  const duplicatedNodes = getSelectedNodes();
  const duplicatedEdges = getInternalEdges(selectedIds);

  const temporaryPayload: ClipboardPayload = {
    nodes: duplicatedNodes,
    edges: duplicatedEdges,
    sourceWorkflowId: workflowStore.workflowId,
  };

  executePaste(temporaryPayload, true);
};

const onRunNode = async (_nodeId: string) => {
  // Single-node execution via context menu — not yet wired to API
};

const onViewOutput = (nodeId: string) => {
  const node = workflowStore.nodes.find((n) => n.id === nodeId);
  if (node) {
    onNodeSelect(node);
  }
};

// Autosave state
const autosaveStatus = ref<"idle" | "saving" | "saved" | "error">("idle");
const autosaveErrorMessage = ref("");
const autosaveFailureToastShown = ref(false);
const autosaveTimer = ref<number | null>(null);
let autosaveInFlight: Promise<boolean> | null = null;
const autoExecuteTimer = ref<number | null>(null);
const recentlyDeletedSnapshot = ref<DeletedWorkflowSnapshot | null>(null);
const deleteUndoTimer = ref<number | null>(null);
const AUTOSAVE_DELAY = 30000; // 30 seconds
const EXPENSIVE_AUTO_EXECUTE_TYPES = [
  "model.",
  "classification.",
  "selection.",
  "baseline.",
  "preprocess.osc",
  "preprocess.msc",
  "transfer.",
  "synthesis.",
];

type WorkflowDraftSnapshot = {
  projectId: number;
  workflowId: number;
  savedAt: string;
  workflowName: string;
  workflowDescription: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
};

const currentWorkflowDraftKey = (): string | null => {
  const projectId = workbookStore.projectId;
  const currentWorkflowId = workflowStore.workflowId;
  if (projectId === null || currentWorkflowId === null) return null;
  return workflowDraftKey(authStore.user?.id, projectId, currentWorkflowId);
};

const clearPendingAutosave = () => {
  if (autosaveTimer.value !== null) {
    window.clearTimeout(autosaveTimer.value);
    autosaveTimer.value = null;
  }
};

const clearPendingAutoExecute = () => {
  if (autoExecuteTimer.value !== null) {
    window.clearTimeout(autoExecuteTimer.value);
    autoExecuteTimer.value = null;
  }
};

const clearDeleteUndoTimer = () => {
  if (deleteUndoTimer.value !== null) {
    window.clearTimeout(deleteUndoTimer.value);
    deleteUndoTimer.value = null;
  }
};

const persistWorkflowDraftSnapshot = () => {
  if (!workflowStore.hasUnsavedChanges) return;
  if (workbookStore.activeSheet?.kind === "trial") return;
  const key = currentWorkflowDraftKey();
  if (!key || workbookStore.projectId === null || workflowStore.workflowId === null) return;
  try {
    const draft: WorkflowDraftSnapshot = {
      projectId: workbookStore.projectId,
      workflowId: workflowStore.workflowId,
      savedAt: new Date().toISOString(),
      ...editableWorkflowGraph(workflowStore),
    };
    localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // Draft persistence is best-effort; server autosave remains primary.
  }
};

const clearWorkflowDraftSnapshot = () => {
  const key = currentWorkflowDraftKey();
  if (!key) return;
  try {
    localStorage.removeItem(key);
  } catch {
    // ignore
  }
};

const restoreWorkflowDraftSnapshot = () => {
  if (workbookStore.activeSheet?.kind === "trial") return;
  const key = currentWorkflowDraftKey();
  if (!key) return;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return;
    const draft = JSON.parse(raw) as Partial<WorkflowDraftSnapshot>;
    if (
      draft.projectId !== workbookStore.projectId ||
      draft.workflowId !== workflowStore.workflowId ||
      !Array.isArray(draft.nodes) ||
      !Array.isArray(draft.edges)
    ) {
      return;
    }
    const restoredGraph = editableWorkflowGraph({
      workflowName: draft.workflowName ?? workflowStore.workflowName,
      workflowDescription: draft.workflowDescription ?? workflowStore.workflowDescription,
      nodes: draft.nodes,
      edges: draft.edges,
    });
    if (workflowDraftSignature(restoredGraph) === workflowDraftSignature(workflowStore)) {
      clearWorkflowDraftSnapshot();
      return;
    }
    workflowStore.workflowName = restoredGraph.workflowName;
    workflowStore.workflowDescription = restoredGraph.workflowDescription;
    workflowStore.setNodes(restoredGraph.nodes);
    workflowStore.setEdges(restoredGraph.edges);
    workflowStore.hasUnsavedChanges = true;
    workflowStore.markWorkflowStale();
    autosaveStatus.value = "idle";
    toast.add({
      severity: "info",
      summary: "Draft restored",
      detail: "Recovered unsaved workflow edits from this browser.",
      life: 2500,
    });
  } catch {
    // Corrupt drafts should not block loading the server copy.
  }
};

const flushWorkflowDraftBeforeUnload = () => {
  persistWorkflowDraftSnapshot();
};

const shouldWarnAboutUnsavedWorkflow = () =>
  workflowStore.hasUnsavedChanges || autosaveStatus.value === "error";

const handleBeforeUnload = (event: BeforeUnloadEvent) => {
  persistWorkflowDraftSnapshot();
  if (!shouldWarnAboutUnsavedWorkflow()) return;
  event.preventDefault();
  event.returnValue = "";
};

onBeforeRouteLeave(async () => {
  persistWorkflowDraftSnapshot();
  if (!shouldWarnAboutUnsavedWorkflow()) return true;
  if (workflowParameterErrors.value.length > 0) return true;

  clearPendingAutosave();
  if (workflowStore.hasUnsavedChanges) {
    const saved = await triggerAutosave(workflowStore.workflowId, workbookStore.activeIndex);
    if (saved && !workflowStore.hasUnsavedChanges) return true;
  }

  return window.confirm(
    "Autosave failed. Your edits are preserved in this browser but are not saved to the server. Leave this page?",
  );
});

const sanitizeNodeIdSeed = (nodeType: string): string =>
  nodeType.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "node";

const createNodeId = (
  nodeType: string,
  existingNodes: WorkflowNode[] = workflowStore.nodes,
): string => {
  const seed = sanitizeNodeIdSeed(nodeType);
  let counter = existingNodes.filter((node) => node.id.startsWith(`${seed}_`)).length + 1;
  let candidate = `${seed}_${counter}`;
  while (existingNodes.some((node) => node.id === candidate)) {
    counter += 1;
    candidate = `${seed}_${counter}`;
  }
  return candidate;
};

// Handle BroadcastChannel messages from NodeDetailView.
// DetailView is send-only for `node_params_updated` (fired on Save and Exit).
const handleBroadcastMessage = (event: MessageEvent) => {
  const result = _handleBroadcastMessage(
    event,
    nodes,
    workflowStore.updateNode,
    workflowStore.workflowId,
  );
  if (
    event.data?.type === "node_params_updated" &&
    event.data?.requestId &&
    broadcastChannel.value
  ) {
    broadcastChannel.value.postMessage({
      type: "node_params_applied",
      requestId: event.data.requestId,
      nodeId: event.data.nodeId,
      workflowId: event.data.workflowId ?? null,
      applied: result.applied,
      reason: result.reason ?? null,
    });
  }
};

// Load supporting data for the workflow bench
onMounted(async () => {
  // Load experiments for DATA node selection
  if (experimentStore.experiments.length === 0) {
    try {
      await experimentStore.fetchExperiments(projectStore.currentProjectId);
    } catch {
      console.warn("Failed to load experiments for workflow builder");
    }
  }

  // Set up BroadcastChannel for cross-tab communication with NodeDetailView
  try {
    broadcastChannel.value = new BroadcastChannel(BROADCAST_CHANNEL_NAME);
    broadcastChannel.value.onmessage = handleBroadcastMessage;
    console.log("[WorkflowBuilder] BroadcastChannel initialized");
  } catch (e) {
    console.warn("[WorkflowBuilder] BroadcastChannel not supported:", e);
  }

  await initializeWorkbook();
  workbookReadyForProjectSwitches = true;

  // A copied or cold-opened workflow tab can hydrate its project only during
  // workbook initialization. Resolve the route-scoped receipt again after
  // that project authority is established; never accept it against a null or
  // previously active project during module setup.
  if (pendingDataSelection.value) {
    dataSelectionReceipt.value = readDataSelectionReceipt({ requireRouteFlag: true });
  }
  workbookContextReady.value = true;

  if (dataSelectionReceipt.value && route.query.fromDataSelection === "1") {
    const starterIntent = readAnalysisStarterIntent();
    preferredAnalysisStarterSlug.value = starterIntent?.template_slug ?? null;
    templatePickerVisible.value = starterIntent?.template_slug !== null;
    if (starterIntent?.template_slug === null) {
      clearAnalysisStarterIntent();
    }
  }

  if (route.query.addNode === "preprocess.wavenumber_align") {
    onAddNode("preprocess.wavenumber_align");
    const query = { ...route.query };
    delete query.addNode;
    await router.replace({ query });
    toast.add({
      severity: "info",
      summary: "Wavenumber Align added",
      detail:
        "Connect the spectra to align and the reference spectrum whose grid should be retained.",
      life: 6000,
    });
  }

  window.addEventListener("keydown", handleKeyDown);
  window.addEventListener("beforeunload", handleBeforeUnload);
  window.addEventListener("pagehide", flushWorkflowDraftBeforeUnload);
  document.addEventListener("visibilitychange", flushWorkflowDraftBeforeUnload);
});

// Clean up BroadcastChannel and autosave timer on unmount
onUnmounted(() => {
  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
    console.log("[WorkflowBuilder] BroadcastChannel closed");
  }
  if (autosaveTimer.value !== null) {
    clearPendingAutosave();
  }
  clearPendingAutoExecute();
  clearDeleteUndoTimer();

  window.removeEventListener("keydown", handleKeyDown);
  window.removeEventListener("beforeunload", handleBeforeUnload);
  window.removeEventListener("pagehide", flushWorkflowDraftBeforeUnload);
  document.removeEventListener("visibilitychange", flushWorkflowDraftBeforeUnload);
});

// Watch for store changes - only react to node count changes (add/remove)
// NOT param changes which would reset selection during editing
watch(
  () => workflowStore.nodes.length,
  (newLength, oldLength) => {
    // Only clear selection if nodes were removed or workflow was cleared
    if (newLength < oldLength || newLength === 0) {
      const nodeIds = new Set(workflowStore.nodes.map((node) => node.id));
      if (selectedNode.value && !nodeIds.has(selectedNode.value.id)) {
        selectedNode.value = null;
      }
    }
  },
);

const scheduleAutosave = () => {
  clearPendingAutosave();
  if (!workflowStore.hasUnsavedChanges || workflowStore.workflowId === null) return;

  autosaveStatus.value = "idle";
  autosaveErrorMessage.value = "";
  if (workflowParameterErrors.value.length > 0) return;

  autosaveFailureToastShown.value = false;
  const scheduledWorkflowId = workflowStore.workflowId;
  const scheduledSheetIndex = workbookStore.activeIndex;
  autosaveTimer.value = window.setTimeout(() => {
    void triggerAutosave(scheduledWorkflowId, scheduledSheetIndex);
  }, AUTOSAVE_DELAY);
};

watch(
  () => hasChanges.value,
  (hasChangesVal) => {
    if (hasChangesVal) return;
    clearPendingAutosave();
    autosaveStatus.value = "idle";
    autosaveErrorMessage.value = "";
  },
);

watch(
  [
    () => workflowStore.nodes,
    () => workflowStore.edges,
    () => workflowStore.workflowName,
    () => workflowStore.workflowDescription,
  ],
  () => {
    persistWorkflowDraftSnapshot();
    scheduleAutosave();
  },
  { deep: true },
);

// Execution state
const isExecuting = ref(false);
const executionCount = ref(0);
const lastExecutionTime = ref<string | null>(null);

// BroadcastChannel for cross-tab communication with NodeDetailView
const BROADCAST_CHANNEL_NAME = "workflow_node_updates";
const broadcastChannel = ref<BroadcastChannel | null>(null);

const getNodeLabel = (nodeType: string): string => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.label) {
    return metadata.label;
  }
  return nodeType;
};

// Computed
const selectedNodeOutput = computed(() => {
  if (!selectedNode.value) return null;
  return nodeOutputs.value.get(selectedNode.value.id) || null;
});

const isTrialTabActive = computed(() => workbookStore.activeSheet?.kind === "trial");
const isManagedCandidateAuthority = computed(
  () => workbookStore.activeSheet?.purpose === "managed_candidate_authority",
);



const activeSheetName = computed(
  () => workbookStore.activeSheet?.name || workflowStore.workflowName || "No sheet open",
);

const activeWorkflowDataSourceIds = computed(() => {
  // Per-active-sheet count, not project total: look up the active sheet's
  // workflow in ProjectDetail.workflows and tally the data sources it binds
  // (primary_data_source_id + data_source_ids, deduped). Switching sheets
  // re-runs this computed so the strip reflects the sheet you're on.
  const activeWorkflowId = workbookStore.activeSheet?.workflowId ?? workflowStore.workflowId;
  if (activeWorkflowId == null) return null;
  const workflow = projectStore.currentProject?.workflows?.find(
    (entry) => entry.id === activeWorkflowId,
  );
  if (!workflow) return null;

  const ids = new Set<number>();
  if (workflow.primary_data_source_id != null) ids.add(workflow.primary_data_source_id);
  for (const id of workflow.data_source_ids ?? []) ids.add(id);
  return [...ids];
});

const activeWorkflowDataSourceNames = computed(() => {
  const ids = activeWorkflowDataSourceIds.value;
  if (!ids?.length) return [];
  const namesById = new Map(
    (projectStore.currentProject?.data_sources ?? []).map((source) => [
      source.id,
      source.display_name,
    ]),
  );
  return ids.map((id) => namesById.get(id)).filter((name): name is string => !!name);
});

const linkedDataTitle = computed(() => {
  if (pendingDataSelection.value) {
    const names = (dataSelectionReceipt.value?.datasets ?? [])
      .map((dataset) => dataset.dataset_name)
      .join(", ");
    return names || "Incoming My Dataset selection is unavailable";
  }
  const names = activeWorkflowDataSourceNames.value;
  return names.length > 0 ? names.join(", ") : linkedDataLabel.value;
});

const linkedDataLabel = computed(() => {
  if (pendingDataSelection.value) {
    const datasets = dataSelectionReceipt.value?.datasets ?? [];
    if (!datasets.length) return "Pending selection unavailable";
    if (datasets.length === 1) return `Pending: ${datasets[0].dataset_name}`;
    return `${datasets.length} datasets pending binding`;
  }
  const ids = activeWorkflowDataSourceIds.value;
  if (ids) {
    if (ids.length === 0) return "No datasets bound";
    const names = activeWorkflowDataSourceNames.value;
    if (names.length === ids.length) {
      return names.length === 1 ? names[0] : `${names[0]} + ${names.length - 1} more`;
    }
    return `${ids.length} dataset${ids.length === 1 ? "" : "s"} bound`;
  }
  // No active sheet yet — fall back to the project's total.
  const total = projectStore.currentProject?.experiment_count ?? 0;
  return total > 0 ? `${total} in project` : "No linked datasets";
});

const canvasSummaryLabel = computed(() => {
  const nodeCount = nodes.value.length;
  const edgeCount = edges.value.length;
  return `${nodeCount} node${nodeCount === 1 ? "" : "s"} · ${edgeCount} link${edgeCount === 1 ? "" : "s"}`;
});

const runButtonTitle = computed(() => {
  if (pendingDataSelection.value) {
    return "Choose an Analysis Starter to bind the incoming My Dataset selection before running";
  }
  if (isManagedCandidateAuthority.value) {
    return "Inspection only: execution requires this workflow's declared runtime";
  }
  const parameterError = workflowParameterErrors.value[0];
  if (parameterError) {
    return `Fix ${parameterError.nodeId}: ${parameterError.message}`;
  }
  const sheetName = workbookStore.activeSheet?.name;
  const scope = sheetName ? `Run the active sheet "${sheetName}"` : "Run the active sheet";
  if (isWorkflowStale.value) {
    return `${scope} — modified since last execution`;
  }
  return scope;
});

const hasExpensiveAutoExecuteNodes = computed(() =>
  nodes.value.some((node) =>
    EXPENSIVE_AUTO_EXECUTE_TYPES.some((prefix) => node.type.startsWith(prefix)),
  ),
);

watch(
  hasExpensiveAutoExecuteNodes,
  (hasExpensiveNodes) => {
    if (!hasExpensiveNodes) return;
    if (autoExecute.value) {
      autoExecute.value = false;
      clearPendingAutoExecute();
    }
  },
  { immediate: true },
);

const buildOutputForNode = (
  nodeId: string,
  result: unknown,
  diagnostics?: Record<string, unknown> | null,
): NodeOutput => {
  const node = nodes.value.find((n) => n.id === nodeId);
  const outputPorts = node ? workflowStore.getNodeMetadata(node.type)?.output_ports : undefined;
  return buildNodeOutput(
    result,
    outputPorts,
    diagnostics,
    workflowStore.lastExecutionResultDescriptors[nodeId],
    (() => {
      const record = workflowStore.lastExecutionPresentations[nodeId];
      return record ? { digest: record.contract_digest, payload: record.contract } : null;
    })(),
  );
};

const hasRenderableOutput = (output: NodeOutput): boolean => {
  if (Array.isArray(output.data) && output.data.length > 0) {
    return true;
  }
  if (output.plots && Object.keys(output.plots).length > 0) {
    return true;
  }
  if (output.descriptor || Object.values(output.ports || {}).some((port) => port.descriptor)) {
    return true;
  }
  for (const port of Object.values(output.ports || {})) {
    if (Array.isArray(port.data) && port.data.length > 0) {
      return true;
    }
    if (port.plots && Object.keys(port.plots).length > 0) {
      return true;
    }
  }
  return false;
};

const hydrateNodeOutputsFromRunResults = (results: Record<string, unknown> | null | undefined) => {
  if (workbookStore.activeSheet?.kind === "trial") return;
  const currentNodeIds = new Set(nodes.value.map((node) => node.id));
  const nextOutputs = new Map<string, NodeOutput>();
  for (const [nodeId, result] of Object.entries(results ?? {})) {
    if (!currentNodeIds.has(nodeId)) {
      continue;
    }
    const diagnostics = workflowStore.lastExecutionDiagnostics?.[nodeId] ?? null;
    const output = buildOutputForNode(nodeId, result, diagnostics);
    if (!hasRenderableOutput(output)) {
      continue;
    }
    nextOutputs.set(nodeId, output);
  }
  {
    nodeOutputs.value = nextOutputs;
    if (workbookStore.activeSheet) {
      workbookStore.activeSheet.nodeOutputsCache = new Map(nextOutputs);
    }
  }
};

const restoreNodeOutputsForActiveSheet = () => {
  const currentNodeIds = new Set(nodes.value.map((node) => node.id));
  const restoredOutputs = new Map<string, NodeOutput>();
  const cachedOutputs =
    workbookStore.activeSheet?.kind !== "trial"
      ? workbookStore.activeSheet?.nodeOutputsCache
      : null;

  for (const [nodeId, output] of cachedOutputs ?? []) {
    if (currentNodeIds.has(nodeId)) {
      restoredOutputs.set(nodeId, output);
    }
  }

  nodeOutputs.value = restoredOutputs;
  hydrateNodeOutputsFromRunResults(
    workflowStore.lastExecutionResults as Record<string, unknown> | null,
  );
};

watch(
  [
    () => workflowStore.lastExecutionResults,
    () => workflowStore.lastExecutionDiagnostics,
    () => workflowStore.lastExecutionResultDescriptors,
    () => workflowStore.lastExecutionPresentations,
  ],
  ([results]) => hydrateNodeOutputsFromRunResults(results as Record<string, unknown> | null),
  { deep: true },
);

// Compute input connections for selected node
const selectedNodeInputConnections = computed(() => {
  if (!selectedNode.value) return [];

  // Find edges pointing to this node (edge.to is the target node id)
  const incomingEdges = edges.value.filter((e) => e.to === selectedNode.value!.id);

  return incomingEdges.map((edge) => {
    const sourceNode = nodes.value.find((n) => n.id === edge.from);
    const sourceOutput = sourceNode ? nodeOutputs.value.get(sourceNode.id) : null;
    const fromPort = edge.fromPort || sourceOutput?.primary_port || "default";
    // Never substitute a different primary output for an unavailable named port.
    const portOutput = sourceOutput?.ports && Object.keys(sourceOutput.ports).length > 0
      ? sourceOutput.ports[fromPort] ?? null
      : sourceOutput;

    return {
      nodeId: edge.from,
      nodeType: sourceNode?.type || "Unknown",
      nodeLabel: sourceNode ? getNodeLabel(sourceNode.type) : "Unknown",
      port: fromPort,
      toPort: edge.toPort || "default", // Include input port name for multi-input nodes
      data: portOutput || null,
    };
  });
});

// Provide workflow context to child components
provide("workflowContext", {
  nodes,
  edges,
  selectedNode,
  nodeOutputs,
});

// Workflow actions
const resetCanvasUi = () => {
  selectedNode.value = null;
  nodeOutputs.value.clear();
  executionCount.value = 0;
  lastExecutionTime.value = null;
};

const resetDialogOpenedSheetUi = () => {
  resetCanvasUi();
  inspectorOpen.value = false;
};

const triggerAutosave = async (
  expectedWorkflowId?: number | null,
  expectedSheetIndex?: number,
): Promise<boolean> => {
  autosaveTimer.value = null;
  if (autosaveInFlight) return autosaveInFlight;
  if (
    expectedWorkflowId != null &&
    (workflowStore.workflowId !== expectedWorkflowId ||
      workbookStore.activeIndex !== expectedSheetIndex)
  ) {
    autosaveStatus.value = "idle";
    return true;
  }
  if (workflowStore.workflowId === null && nodes.value.length === 0 && edges.value.length === 0) {
    return true;
  }

  autosaveInFlight = (async () => {
    const isNewWorkflow = workflowStore.workflowId === null;
    autosaveStatus.value = "saving";
    try {
      const savedId = await workflowStore.saveWorkflow({
        createVersion: false,
        projectId: workbookStore.projectId,
      });
      if (isNewWorkflow && workbookStore.projectId !== null) {
        await workbookStore.refreshSheets();
        await workbookStore.selectWorkflowSheet(savedId);
      }
      autosaveStatus.value = "saved";
      autosaveErrorMessage.value = "";
      autosaveFailureToastShown.value = false;
      console.log("[WorkflowBuilder] Autosaved workflow");

      setTimeout(() => {
        if (autosaveStatus.value === "saved" && !hasChanges.value) {
          autosaveStatus.value = "idle";
        }
      }, 5000);
      return true;
    } catch (err: unknown) {
      autosaveStatus.value = "error";
      autosaveErrorMessage.value = getErrorMessage(err, "Autosave failed");
      console.error("[WorkflowBuilder] Autosave failed:", err);
      if (!autosaveFailureToastShown.value) {
        toast.add({
          severity: "error",
          summary: "Autosave Failed",
          detail: "Your edits are kept as a local draft. Edit again to retry saving.",
          life: 6000,
        });
        autosaveFailureToastShown.value = true;
      }
      return false;
    }
  })();

  try {
    return await autosaveInFlight;
  } finally {
    autosaveInFlight = null;
  }
};

const initializeWorkbook = async () => {
  try {
    const queryProjectId = Number(route.query.project_id);
    let targetProjectId: number | null =
      Number.isFinite(queryProjectId) && queryProjectId > 0
        ? queryProjectId
        : projectStore.currentProjectId;

    // Prefer the user's last active project before falling back to "any recent" or
    // auto-creating a placeholder. Without this, a cold reload on /workflow with
    // no query param drops the user into a different project than they left.
    if (targetProjectId === null) {
      const remembered = projectStore.getLastActiveProjectId?.();
      if (remembered) {
        await projectStore.fetchProjects();
        const stillExists = projectStore.projects.some((p) => p.id === remembered);
        if (stillExists) {
          targetProjectId = remembered;
        }
      }
    }

    if (targetProjectId === null) {
      if (projectStore.projects.length === 0) {
        await projectStore.fetchProjects();
      }
      targetProjectId = projectStore.recentProjects[0]?.id ?? null;
    }

    if (targetProjectId === null) {
      const project = await projectStore.createProject({
        name: "My Project",
        description: "Default project for workflow sheets",
      });
      targetProjectId = project?.id ?? null;
    }

    if (targetProjectId === null) {
      throw new Error("Unable to create or select a project for workflow sheets");
    }

    await projectStore.selectProject(targetProjectId);
    const pendingStarter = readAnalysisStarterIntent();
    await workbookStore.loadSheets(targetProjectId, {
      createIfEmpty: pendingStarter?.template_slug == null,
    });
    if (route.query.workflow_id !== undefined) {
      const requestedId = Number(route.query.workflow_id);
      const requestedIndex = workbookStore.sheets.findIndex(sheet => sheet.workflowId === requestedId);
      if (!Number.isSafeInteger(requestedId) || requestedIndex < 0) {
        throw new Error("The requested workflow is not available in this project.");
      }
      await workbookStore.switchSheet(requestedIndex);
    }
    restoreWorkflowDraftSnapshot();
    resetCanvasUi();
    restoreNodeOutputsForActiveSheet();

    if (workflowStore.workflowWarnings.length > 0) {
      for (const warning of workflowStore.workflowWarnings) {
        toast.add({
          severity: "warn",
          summary: "Workflow Warning",
          detail: warning,
          life: 6000,
        });
      }
    }

    toast.add({
      severity: "info",
      summary: "Workbook Loaded",
      detail: `Loaded "${workbookStore.activeSheet?.name || workflowStore.workflowName}"`,
      life: 3000,
    });
  } catch (err: unknown) {
    const message = getErrorMessage(err, "Unable to load workflow sheets");
    console.error("[WorkflowBuilder] Workbook load failed:", err);
    toast.add({
      severity: "error",
      summary: "Workbook Load Failed",
      detail: message,
      life: 5000,
    });
  }
};

let workbookReadyForProjectSwitches = false;
let projectWorkbookLoadGeneration = 0;

watch(
  () => projectStore.currentProjectId,
  async (projectId) => {
    if (
      !workbookReadyForProjectSwitches ||
      projectId === null ||
      projectId === workbookStore.projectId
    ) {
      return;
    }

    const loadGeneration = ++projectWorkbookLoadGeneration;
    clearPendingAutosave();
    clearPendingAutoExecute();
    resetDialogOpenedSheetUi();
    workflowStore.clearWorkflow();

    try {
      await workbookStore.loadSheets(projectId);
      if (
        loadGeneration !== projectWorkbookLoadGeneration ||
        projectStore.currentProjectId !== projectId
      ) {
        return;
      }
      try {
        await experimentStore.fetchExperiments(projectId);
      } catch {
        console.warn("Failed to load experiments for selected workflow project");
      }
      restoreWorkflowDraftSnapshot();
      restoreNodeOutputsForActiveSheet();
      toast.add({
        severity: "info",
        summary: "Workbook Loaded",
        detail: `Loaded "${workbookStore.activeSheet?.name || workflowStore.workflowName}"`,
        life: 3000,
      });
    } catch (err: unknown) {
      if (loadGeneration !== projectWorkbookLoadGeneration) return;
      const message = getErrorMessage(err, "Unable to load workflow sheets");
      console.error("[WorkflowBuilder] Project workbook load failed:", err);
      toast.add({
        severity: "error",
        summary: "Workbook Load Failed",
        detail: message,
        life: 5000,
      });
    }
  },
);

const exportingPng = ref(false);
const exportSheetPng = async (index: number) => {
  if (exportingPng.value) return;
  const sheet = workbookStore.sheets[index];
  if (!sheet || sheet.kind === "trial") return;
  exportingPng.value = true;
  try {
    if (index !== workbookStore.activeIndex) await switchWorkbookSheet(index);
    await nextTick();
    if (workbookStore.activeSheet?.workflowId !== sheet.workflowId || !canvasRef.value) {
      throw new Error("Open this workflow sheet before exporting its canvas.");
    }
    await canvasRef.value.exportPng(sheet.name);
    toast.add({ severity: "success", summary: "Canvas exported", detail: "PNG download started.", life: 3000 });
  } catch (error) {
    toast.add({ severity: "error", summary: "PNG export failed", detail: error instanceof Error ? error.message : String(error), life: 5000 });
  } finally { exportingPng.value = false; }
};

const switchWorkbookSheet = async (index: number) => {
  if (isBatchExecuting.value) {
    toast.add({
      severity: "info",
      summary: "Workbook Running",
      detail: "Wait for the workbook run to finish before switching sheets.",
      life: 2500,
    });
    return;
  }

  // Capture dirtiness + previous sheet name before the switch — switchSheet()
  // autosaves silently with createVersion=false, so without this the user would
  // see no feedback that their edits were persisted before navigation.
  const wasDirty = workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null;
  const previousSheetName = workbookStore.activeSheet?.name ?? "previous sheet";
  clearPendingAutosave();

  // Cache current outputs before switching
  if (workbookStore.activeSheet && workbookStore.activeSheet.kind !== "trial") {
    workbookStore.activeSheet.nodeOutputsCache = new Map(nodeOutputs.value);
  }

  try {
    await workbookStore.switchSheet(index);
    restoreWorkflowDraftSnapshot();
    if (workbookStore.activeSheet?.kind !== "trial") {
      resetCanvasUi();
      restoreNodeOutputsForActiveSheet();

      const lastSelectedId = workbookStore.activeSheet?.lastSelectedNodeId;
      if (lastSelectedId) {
        const restoredNode = nodes.value.find((n) => n.id === lastSelectedId);
        if (restoredNode) {
          selectedNode.value = restoredNode;
        }
      }
    }
    if (wasDirty) {
      toast.add({
        severity: "success",
        summary: "Auto-saved",
        detail: `Saved "${previousSheetName}" before switching`,
        life: 2000,
      });
    }
    const nextQuery = activeWorkflowQuery(
      route.query,
      workbookStore.projectId,
      workbookStore.activeSheet?.workflowId ?? null,
    );
    if (nextQuery) {
      try {
        await router.replace({ path: route.path, query: nextQuery });
      } catch {
        toast.add({
          severity: "warn",
          summary: "Workflow Link Not Updated",
          detail: "The sheet changed, but this URL may still open the previous sheet after a reload.",
          life: 5000,
        });
      }
    }
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Switch Failed",
      detail: getErrorMessage(err, "Unable to switch sheets"),
      life: 4000,
    });
  }
};

const addWorkbookSheet = async () => {
  try {
    await workbookStore.addSheet();
    resetCanvasUi();
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Add Sheet Failed",
      detail: getErrorMessage(err, "Unable to add sheet"),
      life: 4000,
    });
  }
};

const duplicateWorkbookSheet = async (workflowId: number) => {
  try {
    await workbookStore.duplicateSheet(workflowId);
    resetCanvasUi();
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Duplicate Failed",
      detail: getErrorMessage(err, "Unable to duplicate sheet"),
      life: 4000,
    });
  }
};

const renameWorkbookSheet = async (workflowId: number, name: string) => {
  try {
    await workbookStore.renameSheet(workflowId, name);
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Rename Failed",
      detail: getErrorMessage(err, "Unable to rename sheet"),
      life: 4000,
    });
  }
};

const colorWorkbookSheet = async (workflowId: number, color: string | null) => {
  try {
    await workbookStore.setSheetColor(workflowId, color);
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Color Failed",
      detail: getErrorMessage(err, "Unable to update sheet color"),
      life: 4000,
    });
  }
};

const reorderWorkbookSheets = async (orderedIds: number[]) => {
  try {
    await workbookStore.reorderSheets(orderedIds);
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Reorder Failed",
      detail: getErrorMessage(err, "Unable to reorder sheets"),
      life: 4000,
    });
  }
};

const deleteWorkbookSheet = async (workflowId: number) => {
  try {
    await workbookStore.deleteSheet(workflowId);
    resetCanvasUi();
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: getErrorMessage(err, "Unable to delete sheet"),
      life: 4000,
    });
  }
};

const openTrialTab = async (nodeData: any) => {
  const sourceWorkflowId = workflowStore.workflowId;
  if (sourceWorkflowId === null) {
    toast.add({
      severity: "error",
      summary: "Trial Unavailable",
      detail: "Save or load a workflow before opening a trial sheet",
      life: 4000,
    });
    return;
  }
  try {
    await workbookStore.openTrialTab(
      nodeData,
      sourceWorkflowId,
      workbookStore.activeSheet?.tabColor ?? null,
    );
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Trial Failed",
      detail: getErrorMessage(err, "Unable to open trial sheet"),
      life: 4000,
    });
  }
};

const closeActiveTrialTab = async () => {
  const trialId = workbookStore.activeTrialSheet?.trialId;
  if (!trialId) return;

  // Capture the selected node ID before closing so we can re-anchor it to the
  // freshly-loaded nodes array that loadWorkflow sets on closeTrialTab.
  const prevNodeId = selectedNode.value?.id ?? null;
  await workbookStore.closeTrialTab(trialId);

  // After closeTrialTab, the workflow store reloads the source workflow and
  // replaces nodes.value with a new array. Re-find the node by ID so the
  // inspector holds a live reference and re-shows immediately.
  if (prevNodeId && inspectorOpen.value) {
    const restoredNode = nodes.value.find((n) => n.id === prevNodeId) ?? null;
    selectedNode.value = restoredNode;
  }
};

const saveTrialParams = async (nodeId: string, params: Record<string, unknown>) => {
  try {
    workflowStore.updateNode(nodeId, { params });
    if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
      await workflowStore.saveWorkflow({ createVersion: false });
    }
    toast.add({
      severity: "success",
      summary: "Saved",
      detail: "Settings applied to the workflow",
      life: 1500,
    });
    await closeActiveTrialTab();
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Save Failed",
      detail: getErrorMessage(err, "Unable to save trial settings"),
      life: 4000,
    });
  }
};

const exportToPython = async () => {
  try {
    const pythonCode = await workflowStore.exportToPython();

    downloadText(
      pythonCode,
      `${workflowStore.workflowName.replace(/\s+/g, "_").toLowerCase()}.py`,
      "text/plain",
    );

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: "Canonical workflow Python script downloaded",
      life: 2000,
    });
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: getErrorMessage(
        err,
        "Export failed — check that the workflow is saved and the backend is running",
      ),
      life: 5000,
    });
  }
};

const exportToNotebook = async () => {
  try {
    const notebook = await workflowStore.exportToNotebook();
    const content = JSON.stringify(notebook, null, 1);
    const safeName = workflowStore.workflowName.replace(/\s+/g, "_").toLowerCase();
    downloadText(content, `${safeName}_workflow.ipynb`, "application/x-ipynb+json");

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: "Jupyter notebook downloaded",
      life: 2000,
    });
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: getErrorMessage(err, "Could not generate notebook"),
      life: 3000,
    });
  }
};

const downloadZip = async () => {
  try {
    await workflowStore.downloadExport("zip");
    toast.add({
      severity: "success",
      summary: "Export",
      detail: "Zip bundle downloaded",
      life: 3000,
    });
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: getErrorMessage(err, "Failed to download zip bundle"),
      life: 5000,
    });
  }
};

const exportValidatedProject = async () => {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) {
    toast.add({ severity: "error", summary: "Export Failed", detail: "Select a project before exporting this validated sheet.", life: 5000 });
    return;
  }
  await projectStore.exportProject(projectId);
  if (projectStore.error) {
    toast.add({ severity: "error", summary: "Export Failed", detail: projectStore.error, life: 5000 });
  } else if (projectStore.lastExportOmittedModels > 0) {
    toast.add({ severity: "warn", summary: "Partial project archive exported", detail: `${projectStore.lastExportOmittedModels} saved model artifact(s) lacked portable training-source provenance and were omitted. The sheet remains, but workflows using those models may need retraining. This is not a deployable winner package.`, life: 9000 });
  } else {
    toast.add({ severity: "success", summary: "Project archive exported", detail: "This preserves the sheet, not a campaign winner application.", life: 4000 });
  }
};

const exportMenuItems = computed(() => workflowStore.hasFoldValidationPlan ? [
  {
    label: "Project archive (.sherpa) — not a winner package",
    icon: "pi pi-download",
    command: exportValidatedProject,
  },
] : [
  {
    label: "Canonical Workflow Python (.py)",
    icon: "pi pi-file",
    command: exportToPython,
  },
  {
    label: "Jupyter Notebook (.ipynb)",
    icon: "pi pi-book",
    command: exportToNotebook,
  },
  {
    separator: true,
  },
  {
    label: "Download Bundle (.zip)",
    icon: "pi pi-box",
    command: downloadZip,
  },
]);

const actionMenuItems = computed(() => [
  {
    label: "Analysis Starter",
    icon: "pi pi-sparkles",
    disabled:
      isTrialTabActive.value || (pendingDataSelection.value && !dataSelectionReceipt.value),
    command: openTemplatePicker,
  },
  {
    label: isWorkflowStale.value ? "Run (Mod)" : "Run",
    icon: "pi pi-play",
    disabled:
      isTrialTabActive.value ||
      isManagedCandidateAuthority.value ||
      pendingDataSelection.value ||
      nodes.value.length === 0 ||
      workflowParameterErrors.value.length > 0 ||
      isExecuting.value ||
      isBatchExecuting.value,
    command: onRunClick,
  },
  {
    label: "Version history…",
    icon: "pi pi-history",
    disabled: isTrialTabActive.value || workflowStore.workflowId === null,
    command: () => {
      versionHistoryVisible.value = true;
    },
  },
  {
    separator: true,
  },
  {
    label: "Export",
    icon: "pi pi-download",
    disabled: isTrialTabActive.value,
    items: exportMenuItems.value,
  },
  {
    label: "Audit",
    icon: "pi pi-shield",
    disabled: isTrialTabActive.value || workflowStore.workflowId === null,
    command: openWorkflowAudit,
  },
]);

const openWorkflowAudit = () => {
  if (workflowStore.workflowId === null) return;
  void router.push({
    path: "/audit",
    query: {
      scope_type: "Workflow",
      scope_id: String(workflowStore.workflowId),
      target_type: "Workflow",
      target_id: String(workflowStore.workflowId),
    },
  });
};

const toggleExportMenu = (event: Event) => {
  exportMenuRef.value?.toggle(event);
};

const copyWorkflowIntegrity = async (hash: string) => {
  try {
    await navigator.clipboard.writeText(hash);
    toast.add({
      severity: "success",
      summary: "Integrity SHA Copied",
      detail: hash,
      life: 2500,
    });
  } catch {
    toast.add({
      severity: "error",
      summary: "Copy Failed",
      detail: "The workflow integrity SHA could not be copied.",
      life: 3500,
    });
  }
};

// Auto-execute toggle handler
const onAutoExecuteChange = () => {
  if (isManagedCandidateAuthority.value || hasExpensiveAutoExecuteNodes.value) {
    autoExecute.value = false;
    return;
  }
  toast.add({
    severity: "info",
    summary: autoExecute.value ? "Auto-Execute Enabled" : "Auto-Execute Disabled",
    detail: autoExecute.value
      ? "Workflow will automatically execute when nodes connect or parameters change"
      : "Manual execution mode - click Execute Workflow to run",
    life: 3000,
  });

  // Mark as having unsaved changes
  workflowStore.hasUnsavedChanges = true;
};

const scheduleAutoExecute = (delayMs: number) => {
  if (
    !autoExecute.value ||
    hasExpensiveAutoExecuteNodes.value ||
    isManagedCandidateAuthority.value ||
    pendingDataSelection.value ||
    isExecuting.value ||
    isBatchExecuting.value ||
    workflowParameterErrors.value.length > 0
  )
    return;
  clearPendingAutoExecute();
  autoExecuteTimer.value = window.setTimeout(() => {
    autoExecuteTimer.value = null;
    void executeWorkflow();
  }, delayMs);
};

const focusFirstWorkflowParameterError = (): boolean => {
  const parameterError = workflowParameterErrors.value[0];
  if (!parameterError) return false;
  selectedNode.value =
    workflowStore.nodes.find((node) => node.id === parameterError.nodeId) ?? selectedNode.value;
  inspectorOpen.value = true;
  toast.add({
    severity: "warn",
    summary: "Fix Workflow Parameters",
    detail: `${parameterError.nodeId}: ${parameterError.message}`,
    life: 4000,
  });
  return true;
};

const onRunClick = async () => {
  if (pendingDataSelection.value) {
    toast.add({
      severity: "info",
      summary: "Data selection is waiting for a sheet",
      detail: "Choose an Analysis Starter to bind the selected dataset, views, target, and groups.",
      life: 4500,
    });
    return;
  }
  if (focusFirstWorkflowParameterError()) return;
  if (runAllSheets.value) {
    await executeWorkbook();
  } else {
    await executeWorkflow();
  }
};

const executeWorkbook = async () => {
  if (workbookStore.sheets.length === 0) return;

  isBatchExecuting.value = true;
  const failures: string[] = [];
  let completed = 0;
  try {
    if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
      await workflowStore.saveWorkflow({ createVersion: false });
    }

    const workflowSheets = workbookStore.sheets.filter(
      (sheet) => sheet.kind !== "trial" && sheet.purpose === "analysis",
    );
    toast.add({
      severity: "info",
      summary: "Running Workbook",
      detail: `Executing ${workflowSheets.length} sheets in the background...`,
      life: 3000,
    });

    for (const sheet of workflowSheets) {
      try {
        if (sheet.workflowId === workflowStore.workflowId) {
          await executeWorkflow();
        } else {
          await workflowStore.executeStoredWorkflow(sheet.workflowId);
        }
        completed += 1;
      } catch {
        failures.push(sheet.name);
        toast.add({
          severity: "error",
          summary: continueWorkbookOnError.value ? "Sheet Run Failed" : "Workbook Run Failed",
          detail: `Failed on sheet "${sheet.name}"`,
          life: 5000,
        });
        if (!continueWorkbookOnError.value) {
          break;
        }
      }
    }

    if (failures.length > 0) {
      toast.add({
        severity: continueWorkbookOnError.value ? "warn" : "error",
        summary: continueWorkbookOnError.value
          ? "Workbook Complete With Errors"
          : "Workbook Stopped",
        detail: `${completed} succeeded, ${failures.length} failed: ${failures.join(", ")}`,
        life: 6000,
      });
    } else {
      toast.add({
        severity: "success",
        summary: "Workbook Complete",
        detail: `${completed} sheet${completed === 1 ? "" : "s"} executed successfully.`,
        life: 3000,
      });
    }
  } finally {
    isBatchExecuting.value = false;
  }
};

// Execute workflow via backend API
const executeWorkflow = async () => {
  if (isManagedCandidateAuthority.value || pendingDataSelection.value) return;
  if (focusFirstWorkflowParameterError()) return;
  isExecuting.value = true;

  try {
    // Execute via backend DAG executor
    const response = await workflowStore.executeWorkflow({});

    // The run-results watcher owns outputs/cache from the accepted store snapshot.
    executionCount.value++;
    lastExecutionTime.value = new Date().toLocaleTimeString();

    if (response.error) {
      toast.add({
        severity: "warn",
        summary: "Execution Completed with Warnings",
        detail: response.error,
        life: 4000,
      });
    } else {
      toast.add({
        severity: "success",
        summary: "Execution Complete",
        detail: `Workflow executed successfully (status: ${response.status})`,
        life: 2000,
      });
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    const message = getErrorMessage(error);
    toast.add({
      severity: "error",
      summary: "Execution Failed",
      detail: message,
      life: 4000,
    });
  } finally {
    isExecuting.value = false;
  }
};

// Event handlers
const onAddNode = (nodeType: string) => {
  const newNode: WorkflowNode = {
    id: createNodeId(nodeType),
    type: nodeType,
    x: 100 + ((workflowStore.nodes.length * 40) % 400),
    y: 100 + Math.floor(workflowStore.nodes.length / 4) * 120,
    params: getDefaultParams(nodeType),
  };
  workflowStore.addNode(newNode);
  selectedNode.value = newNode;
};

const getDefaultParams = (nodeType: string): ParamsMap => {
  const defaults: ParamsMap = {};
  for (const parameter of workflowStore.getNodeMetadata(nodeType)?.parameters ?? []) {
    if (parameter.default != null) {
      defaults[parameter.name] = JSON.parse(JSON.stringify(parameter.default));
    }
  }
  return defaults;
};

const onNodesUpdate = (updatedNodes: WorkflowNode[]) => {
  workflowStore.setNodes(updatedNodes);
};

const onEdgesUpdate = (updatedEdges: WorkflowEdge[]) => {
  workflowStore.setEdges(updatedEdges);
};

const onNodeSelect = (node: WorkflowNode | null) => {
  selectedNode.value = node;
  if (workbookStore.activeSheet?.workflowId) {
    workbookStore.setLastSelectedNodeId(workbookStore.activeSheet.workflowId, node?.id || null);
  }
  inspectorOpen.value = !!node;
};

const onCloseInspector = () => {
  inspectorOpen.value = false;
};

watch(
  () => [selectedNode.value?.id || null, inspectorOpen.value] as const,
  ([nodeId, isOpen]) => {
    if (!nodeId || !isOpen) {
      return;
    }

    setTimeout(() => {
      canvasRef.value?.centerNode?.(nodeId);
    }, 0);

    setTimeout(() => {
      canvasRef.value?.centerNode?.(nodeId);
    }, 320);
  },
);

const onNodeConnect = (connection: {
  from: string;
  to: string;
  fromPort?: string;
  toPort?: string;
}) => {
  workflowStore.addEdge(connection);

  // Auto-execute if enabled
  scheduleAutoExecute(500);
};

const onConnectionError = (errorMessage: string) => {
  toast.add({
    severity: "error",
    summary: "Invalid Connection",
    detail: errorMessage,
    life: 4000,
  });
};

const stableStringify = (value: unknown): string => {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
};

const stripUndefinedAndDefaultParams = (nodeType: string, params: ParamsMap): ParamsMap => {
  const metadataDefaults: ParamsMap = {};
  const metadata = workflowStore.getNodeMetadata(nodeType);
  for (const param of metadata?.parameters || []) {
    if (param.default !== undefined) {
      metadataDefaults[param.name] = param.default;
    }
  }
  const defaults = { ...getDefaultParams(nodeType), ...metadataDefaults };
  const normalized: ParamsMap = {};
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined) {
      continue;
    }
    if (
      Object.prototype.hasOwnProperty.call(defaults, key) &&
      stableStringify(value) === stableStringify(defaults[key])
    ) {
      continue;
    }
    normalized[key] = value;
  }
  return normalized;
};

const onUpdateParams = (nodeId: string, params: ParamsMap) => {
  const node = workflowStore.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) {
    return;
  }
  const previous = stripUndefinedAndDefaultParams(node.type, node.params || {});
  const next = stripUndefinedAndDefaultParams(node.type, params || {});
  if (stableStringify(previous) === stableStringify(next)) {
    return;
  }

  workflowStore.updateNode(nodeId, { params });

  // Auto-execute if enabled (with longer debounce for parameter changes)
  scheduleAutoExecute(1000);
};

const onExecuteNode = async (nodeId: string) => {
  if (isManagedCandidateAuthority.value || pendingDataSelection.value) return;
  const node = nodes.value.find((n) => n.id === nodeId);
  if (!node) return;

  try {
    // Execute single node via backend
    const response = await workflowStore.executeNode(nodeId, {});

    // The run-results watcher replaces all outputs/cache, including partial runs.

    if (response.error) {
      toast.add({
        severity: "warn",
        summary: "Node Completed with Warning",
        detail: response.error,
        life: 3000,
      });
    } else {
      toast.add({
        severity: "success",
        summary: "Node Executed",
        detail: `${node.type} completed`,
        life: 2000,
      });
    }
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    const message = getErrorMessage(error);
    toast.add({
      severity: "error",
      summary: "Node Failed",
      detail: message,
      life: 3000,
    });
  }
};

const onDeleteNode = (nodeId: string) => {
  deleteNodesById(new Set([nodeId]));
};
</script>

<style scoped>
/*
  Page-level chrome adopts the canonical Zen vocabulary used on Project /
  Dashboard / Data / Models: 0.9375rem base font, 1.75rem h1 at weight 500,
  hairline section dividers, restrained accent. The dark slate background
  was removed so the workflow page reads as part of the same app surface
  as everything else. The canvas, Add-Nodes toolbar, sheet tabs, and
  inspector live in their own components and own their internal styling.
*/

.workflow-builder-content {
  display: flex;
  flex-direction: column;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

:global(.content:has(.workflow-builder-content)) {
  background: #e4e0fa;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}



.workflow-meta-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 4px;
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: 0.75rem;
  color: #4ade80;
  cursor: help;
  max-width: 18rem;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.workflow-meta-badge i {
  font-size: 0.7rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  min-width: 0;
}

.toolbar-action-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
}

.header-actions :deep(.toolbar-action-btn.p-button) {
  width: 108px;
}

.header-actions :deep(.toolbar-action-btn.p-button) {
  height: 34px;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0 10px;
  border-radius: 6px;
  background: #334155;
  border: 1px solid #475569;
  color: #e2e8f0;
  white-space: nowrap;
  box-sizing: border-box;
}

.header-actions :deep(.toolbar-action-btn.p-button) {
  justify-content: center;
}

.header-actions :deep(.toolbar-actions-menu-btn.p-button) {
  display: none;
}

.workflow-builder-content :deep(.toolbar-settings-btn.p-button) {
  width: 2.25rem;
  min-height: 2.25rem;
  padding: 0;
}

.header-actions :deep(.toolbar-action-btn.p-button:hover:not(:disabled)) {
  background: #475569;
  border-color: #64748b;
  color: #f8fafc;
}

.header-actions :deep(.toolbar-action-btn.p-button:disabled) {
  opacity: 0.45;
}

.autosave-indicator {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 6px;
  color: #4ade80;
  font-size: 0.75rem;
  font-weight: 500;
}

.autosave-indicator-error {
  background: rgba(239, 68, 68, 0.14);
  border-color: rgba(239, 68, 68, 0.35);
  color: #fecaca;
}

.toolbar-state-control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid #334155;
  background: rgba(15, 23, 42, 0.55);
  color: #cbd5e1;
  font-size: 0.82rem;
  font-weight: 500;
}

.toolbar-state-control span {
  user-select: none;
}

.toolbar-state-control :deep(.p-checkbox) {
  width: 18px;
  height: 18px;
}

.toolbar-state-control :deep(.p-checkbox-box) {
  border-color: #64748b;
  background: #0f172a;
}

.toolbar-state-control :deep(.p-checkbox-box.p-highlight) {
  border-color: #60a5fa;
  background: #2563eb;
}

.settings-panel-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 8px 4px;
}

.toolbar-settings-note {
  max-width: 240px;
  color: #94a3b8;
  font-size: 0.78rem;
  line-height: 1.35;
}

.execution-banner {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  border-bottom: 1px solid var(--surface-border);
  margin-bottom: 1rem;
}

.execution-banner i {
  color: var(--primary-color);
  font-size: 0.95rem;
}

.execution-time {
  margin-left: auto;
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-variant-numeric: tabular-nums;
}

.node-undo-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0;
  color: var(--text-color);
  font-size: 0.875rem;
  border-bottom: 1px solid var(--surface-border);
  margin-bottom: 1rem;
}

.workflow-workspace {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 16px;
  flex: 1;
  align-items: stretch;
}

/* All direct grid children must be able to shrink below their content's intrinsic width. */
.workflow-workspace > * {
  min-width: 0;
}

/* Three-column layout when inspector is open */
.workflow-workspace.inspector-open {
  grid-template-columns: 200px 1fr 320px;
}

/* The canonical catalog carries complete scientific detail and therefore
   expands deliberately; the compact Add palette retains its 200px column. */
.workflow-workspace.catalog-open:not(.toolbar-collapsed) {
  grid-template-columns: minmax(360px, 34vw) 1fr;
}

.workflow-workspace.catalog-open.inspector-open:not(.toolbar-collapsed) {
  grid-template-columns: minmax(340px, 30vw) 1fr 320px;
}

/* Collapsed toolbar: shrink the left column to just the chevron strip. */
.workflow-workspace.toolbar-collapsed {
  grid-template-columns: 44px 1fr;
}

.workflow-workspace.toolbar-collapsed.inspector-open {
  grid-template-columns: 44px 1fr 320px;
}

/* Trial active: canvas-stack is the only visible item — collapse to a single
   column so the canvas fills the full width without a 0px ghost column. */
.workflow-workspace.trial-active,
.workflow-workspace.trial-active.inspector-open,
.workflow-workspace.trial-active.toolbar-collapsed,
.workflow-workspace.trial-active.toolbar-collapsed.inspector-open {
  grid-template-columns: 1fr;
}

/* Remove hidden items from the grid flow entirely during a trial tab.
   display:none takes the item out of the grid; the canvas-stack then
   occupies the single 1fr column with no leftover ghost space. */
.trial-hidden {
  display: none !important;
}

.canvas-stack {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.canvas-container {
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  overflow: hidden;
  position: relative;
  display: flex;
  min-width: 0;
}

.canvas-container.with-sheet-tabs {
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}

.sheet-tabs-skeleton {
  display: flex;
  align-items: flex-end;
  gap: 0.25rem;
  background: #1e293b;
  border: 1px solid #334155;
  border-bottom: 0;
  border-radius: 8px 8px 0 0;
  min-height: 40px;
  padding: 0.35rem 0.5rem 0;
}

.skeleton-tab {
  background: linear-gradient(90deg, #334155 0%, #475569 50%, #334155 100%);
  background-size: 200% 100%;
  border-radius: 6px 6px 0 0;
  height: 30px;
  margin-bottom: 4px;
  width: 7.5rem;
  animation: sheet-skeleton-shimmer 1.4s infinite linear;
}

.skeleton-tab.skeleton-tab-narrow {
  width: 5rem;
}

@keyframes sheet-skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.canvas-container.trial-container {
  min-height: 0;
  overflow: auto;
}

.canvas-container > * {
  flex: 1 1 auto;
  min-height: 100%;
}

.workflow-data-selection {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 0 0 0.8rem;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--surface-border);
  border-left: 4px solid var(--green-500);
  border-radius: 8px;
  background: var(--surface-card);
}

.workflow-data-selection > i {
  color: var(--green-600);
}

.workflow-data-selection.pending {
  border-left-color: var(--orange-500);
}

.workflow-data-selection.pending > i {
  color: var(--orange-600);
}

.workflow-data-selection > div {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 0.12rem;
}

.workflow-data-selection span {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}

.run-name-form {
  display: grid;
  gap: 0.65rem;
}

.run-name-form label {
  color: var(--text-secondary);
  font-size: 0.82rem;
  font-weight: 600;
}

@media (max-width: 1200px) {
  .workflow-workspace.inspector-open {
    grid-template-columns: 180px 1fr 280px;
  }
  .workflow-workspace.toolbar-collapsed.inspector-open {
    grid-template-columns: 44px 1fr 280px;
  }
  .workflow-workspace.catalog-open.inspector-open:not(.toolbar-collapsed) {
    grid-template-columns: 320px 1fr 280px;
  }
}

@media (max-width: 900px) {

  .workflow-workspace {
    grid-template-columns: minmax(120px, 180px) minmax(120px, 1fr);
    overflow-x: auto;
  }

  .workflow-workspace.inspector-open {
    grid-template-columns: minmax(120px, 180px) minmax(120px, 1fr) 260px;
  }

  .workflow-workspace.toolbar-collapsed {
    grid-template-columns: 44px minmax(120px, 1fr);
  }

  .workflow-workspace.toolbar-collapsed.inspector-open {
    grid-template-columns: 44px minmax(120px, 1fr) 260px;
  }

  .workflow-workspace.catalog-open:not(.toolbar-collapsed),
  .workflow-workspace.catalog-open.inspector-open:not(.toolbar-collapsed) {
    grid-template-columns: minmax(220px, 280px) minmax(120px, 1fr);
  }

  .workflow-workspace.catalog-open.inspector-open:not(.toolbar-collapsed) {
    grid-template-columns: minmax(220px, 280px) minmax(120px, 1fr) 260px;
  }
}

/* Template drawer header (Sidebar renders outside scoped context) */
.drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.drawer-header-icon {
  font-size: 1.1rem;
  color: #3b82f6;
}

.drawer-header-title {
  font-size: 1.05rem;
  font-weight: 600;
  color: #1e293b;
}
</style>
