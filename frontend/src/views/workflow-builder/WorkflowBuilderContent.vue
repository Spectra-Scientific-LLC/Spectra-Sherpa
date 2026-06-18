<template>
  <section class="workflow-builder-content">
    <header class="tab-header">
      <div class="section-title-row">
        <h1>Workflows</h1>
        <span
          v-if="workflowBadgeText"
          class="workflow-meta-badge"
          :title="workflowBadgeTitle"
        >
          <i :class="workflowStore.workflowHash ? 'pi pi-lock' : 'pi pi-bookmark'"></i>
          {{ workflowBadgeText }}
        </span>
      </div>

      <ResponsiveHeaderActions :items="actionMenuItems">
        <div class="toolbar-action-group">
          <Button
            label="Analysis Starter"
            icon="pi pi-sparkles"
            class="p-button-outlined p-button-sm"
            :disabled="isTrialTabActive"
            @click="templatePickerVisible = true"
          />
          <Button
            :label="isWorkflowStale ? 'Run (Mod)' : 'Run'"
            icon="pi pi-play"
            data-action="run_workflow"
            class="p-button-outlined p-button-sm"
            :loading="isExecuting || isBatchExecuting"
            :disabled="isTrialTabActive || nodes.length === 0 || isExecuting || isBatchExecuting"
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
          <span v-if="autosaveStatus === 'saved'" class="autosave-indicator">
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
              <label class="toolbar-state-control" title="Auto-execute on connect/param change">
                <Checkbox
                  v-model="autoExecute"
                  binary
                  input-id="workflow-auto-update"
                  @change="onAutoExecuteChange"
                />
                <span>Auto update</span>
              </label>
              <label class="toolbar-state-control" title="Run all non-trial sheets in the workbook sequentially">
                <Checkbox
                  v-model="runAllSheets"
                  binary
                  input-id="workflow-run-all"
                />
                <span>Run all sheets</span>
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
      </ResponsiveHeaderActions>
    </header>

    <VersionHistoryDialog
      v-model:visible="versionHistoryVisible"
      :workflow-id="workflowStore.workflowId"
      @sheet-opened="resetDialogOpenedSheetUi"
    />

    <TemplatePickerDialog
      v-model:visible="templatePickerVisible"
      @sheet-opened="resetDialogOpenedSheetUi"
    />

    <!-- Workspace context strip: 4 read-only cells that re-read on every
         sheet switch. "Project Data" reflects the active sheet's bound
         data sources, not the project's total. Project Record / Data
         navigation removed (sidebar handles it). -->
    <div class="workflow-context-strip">
      <div class="workflow-context-item">
        <span>Project</span>
        <strong>{{ activeProjectName }}</strong>
      </div>
      <div class="workflow-context-item">
        <span>Active Sheet</span>
        <strong>{{ activeSheetName }}</strong>
      </div>
      <div class="workflow-context-item">
        <span>Project Data</span>
        <strong>{{ linkedDataLabel }}</strong>
      </div>
      <div class="workflow-context-item">
        <span>Canvas</span>
        <strong>{{ canvasSummaryLabel }}</strong>
      </div>
    </div>

    <!-- Execution status banner -->
    <div v-if="executionCount > 0" class="execution-banner">
      <i class="pi pi-check-circle"></i>
      <span>Workflow executed {{ executionCount }} time{{ executionCount !== 1 ? 's' : '' }}</span>
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
      :class="{ 'inspector-open': inspectorOpen, 'toolbar-collapsed': toolbarCollapsed, 'trial-active': isTrialTabActive }"
    >
      <WorkflowToolbar
        v-show="!isTrialTabActive"
        :class="{ 'trial-hidden': isTrialTabActive }"
        @add-node="onAddNode"
        @toggle-collapsed="onToolbarCollapsedChange"
      />

      <!-- Center: Canvas -->
      <div class="canvas-stack">
        <WorkbookSheetTabs
          v-if="workbookStore.sheets.length > 0"
          class="canvas-sheet-tabs"
          :sheets="workbookStore.sheets"
          :active-index="workbookStore.activeIndex"
          :has-unsaved-changes="workflowStore.hasUnsavedChanges"
          @switch="switchWorkbookSheet"
          @add="addWorkbookSheet"
          @duplicate="duplicateWorkbookSheet"
          @open-template-picker="templatePickerVisible = true"
          @rename="renameWorkbookSheet"
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
          :class="{ 'with-sheet-tabs': workbookStore.sheets.length > 0, 'trial-container': isTrialTabActive }"
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
import { ref, computed, provide, watch, onMounted, onUnmounted } from "vue";
import { storeToRefs } from "pinia";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import Menu from "primevue/menu";
import OverlayPanel from "primevue/overlaypanel";
import { useToast } from "primevue/usetoast";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import { useWorkflowStore, type ExperimentDataset, type WorkflowNode, type WorkflowEdge } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import { useProjectStore } from "@/stores/project";
import { useWorkbookStore } from "@/stores/workbook";
import { useAuthStore } from "@/stores/auth";
import { useWorkflowBuilderConfigStore } from "@/stores/workflowBuilderConfig";
import { useClipboardStore, type ClipboardPayload } from "@/stores/clipboard";
import WorkbookSheetTabs from "@/components/WorkbookSheetTabs.vue";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import VersionHistoryDialog from "@/components/VersionHistoryDialog.vue";
import TemplatePickerDialog from "@/components/TemplatePickerDialog.vue";
import WorkflowToolbar from "./WorkflowToolbar.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import WorkflowInspector from "./WorkflowInspector.vue";
import NodeDetailView from "./NodeDetailView.vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import { downloadText } from "@/utils/download";
import { getErrorMessage } from "@/utils/errors";
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

// Use store for workflow state
const nodes = computed({
  get: () => workflowStore.nodes,
  set: (val) => workflowStore.setNodes(val)
});
const edges = computed({
  get: () => workflowStore.edges,
  set: (val) => workflowStore.setEdges(val)
});
const hasChanges = computed(() => workflowStore.hasUnsavedChanges);
const isWorkflowStale = computed(() => workflowStore.isWorkflowStale);

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
      return typeof localStorage !== 'undefined' && localStorage.getItem('workflow-toolbar-collapsed') === '1';
    } catch {
      return false;
    }
  })()
);
const onToolbarCollapsedChange = (collapsed: boolean) => {
  toolbarCollapsed.value = collapsed;
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
  if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
    return;
  }

  const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
  const isCmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;
  const key = e.key.toLowerCase();
  const browserHasSelectedText = Boolean(window.getSelection()?.toString());

  if (isCmdOrCtrl && key === 'c' && browserHasSelectedText) {
    return;
  }

  if (isCmdOrCtrl && key === 'c') {
    onCopySelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === 'x') {
    onCutSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === 'v') {
    onPasteSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === 'd') {
    onDuplicateSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && key === 'a') {
    canvasRef.value?.selectAll();
    e.preventDefault();
  } else if (e.key === 'Delete' || e.key === 'Backspace') {
    onDeleteSelection();
    e.preventDefault();
  } else if (e.key === 'Escape') {
    canvasRef.value?.clearSelection();
    e.preventDefault();
  }
};

const getSelectedNodes = () => {
  if (!canvasRef.value?.selectedNodeIds) return [];
  const selectedIds = canvasRef.value.selectedNodeIds;
  return workflowStore.nodes.filter(n => selectedIds.has(n.id));
};

const getInternalEdges = (selectedIds: Set<string>) => {
  return workflowStore.edges.filter(e => selectedIds.has(e.from) && selectedIds.has(e.to));
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
    sourceWorkflowId: workflowStore.workflowId
  });

  toast.add({ severity: 'info', summary: 'Copied', detail: `${copiedNodes.length} node(s) copied to clipboard`, life: 2000 });
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
  const existingEdges = new Set(workflowStore.edges.map((edge) => `${edge.from}->${edge.to}:${edge.fromPort || ""}:${edge.toPort || ""}`));
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
    selectedNode.value = workflowStore.nodes.find((node) => node.id === snapshot.selectedNodeId) || null;
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
  const label = deletedNodes.length === 1 ? getNodeLabel(deletedNodes[0].type) : `${deletedNodes.length} nodes`;
  if (requireConfirmation && !window.confirm(`Delete ${label}? You can undo this immediately after deletion.`)) {
    return;
  }
  const deletedEdges = workflowStore.edges.filter((edge) => ids.has(edge.from) || ids.has(edge.to));
  const deletedOutputs = Array.from(nodeOutputs.value.entries()).filter(([nodeId]) => ids.has(nodeId));
  const selectedNodeId = selectedNode.value && ids.has(selectedNode.value.id) ? selectedNode.value.id : null;

  workflowStore.setNodes(workflowStore.nodes.filter((node) => !ids.has(node.id)));
  workflowStore.setEdges(workflowStore.edges.filter((edge) => !ids.has(edge.from) && !ids.has(edge.to)));
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
let lastClipboardHash = '';

const executePaste = (payload: ClipboardPayload, isDuplicate: boolean = false) => {
  if (!payload || payload.nodes.length === 0) return;

  // Track paste count to increment offset
  const hash = payload.nodes.map(n => n.id).join(',');
  if (!isDuplicate) {
    if (hash === lastClipboardHash) {
      lastPasteCount++;
    } else {
      lastClipboardHash = hash;
      lastPasteCount = 1;
    }
  }

  const offsetX = isDuplicate ? 40 : 20 + (lastPasteCount * 20);
  const offsetY = isDuplicate ? 40 : 20 + (lastPasteCount * 20);

  const idMap = new Map<string, string>();
  const newNodes: WorkflowNode[] = [];
  const allNodes = [...workflowStore.nodes];

  payload.nodes.forEach(oldNode => {
    const newId = createNodeId(oldNode.type, allNodes);
    idMap.set(oldNode.id, newId);
    
    const newNode = {
      ...oldNode,
      id: newId,
      x: oldNode.x + offsetX,
      y: oldNode.y + offsetY,
      executionState: undefined // Clear state
    };
    newNodes.push(newNode);
    allNodes.push(newNode); // for next createNodeId iteration
  });

  const newEdges: WorkflowEdge[] = [];
  payload.edges.forEach(oldEdge => {
    const newFrom = idMap.get(oldEdge.from);
    const newTo = idMap.get(oldEdge.to);
    if (newFrom && newTo) {
      newEdges.push({
        ...oldEdge,
        from: newFrom,
        to: newTo
      });
    }
  });

  workflowStore.setNodes(allNodes);
  workflowStore.setEdges([...workflowStore.edges, ...newEdges]);
  workflowStore.hasUnsavedChanges = true;

  canvasRef.value?.clearSelection();
  newNodes.forEach(n => canvasRef.value?.selectedNodeIds.add(n.id));

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
    sourceWorkflowId: workflowStore.workflowId
  };

  executePaste(temporaryPayload, true);
};

const onRunNode = async (_nodeId: string) => {
  // Single-node execution via context menu — not yet wired to API
};

const onViewOutput = (nodeId: string) => {
  const node = workflowStore.nodes.find(n => n.id === nodeId);
  if (node) {
    onNodeSelect(node);
  }
};

// Autosave state
const autosaveStatus = ref<'idle' | 'saving' | 'saved' | 'error'>('idle');
const autosaveErrorMessage = ref("");
const autosaveFailureToastShown = ref(false);
const autosaveTimer = ref<number | null>(null);
const autoExecuteTimer = ref<number | null>(null);
const autoExecuteAcceptedForExpensiveWorkflow = ref(autoExecute.value);
const recentlyDeletedSnapshot = ref<DeletedWorkflowSnapshot | null>(null);
const deleteUndoTimer = ref<number | null>(null);
const AUTOSAVE_DELAY = 30000; // 30 seconds
const WORKFLOW_DRAFT_PREFIX = "spectra_sherpa_workflow_draft_v1";
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

const workflowDraftKey = (projectId: number, workflowId: number): string =>
  `${WORKFLOW_DRAFT_PREFIX}:${authStore.user?.id ?? "local"}:${projectId}:${workflowId}`;

const currentWorkflowDraftKey = (): string | null => {
  const projectId = workbookStore.projectId;
  const currentWorkflowId = workflowStore.workflowId;
  if (projectId === null || currentWorkflowId === null) return null;
  return workflowDraftKey(projectId, currentWorkflowId);
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
      workflowName: workflowStore.workflowName,
      workflowDescription: workflowStore.workflowDescription,
      nodes: workflowStore.nodes,
      edges: workflowStore.edges,
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
    workflowStore.workflowName = draft.workflowName || workflowStore.workflowName;
    workflowStore.workflowDescription = draft.workflowDescription || workflowStore.workflowDescription;
    workflowStore.setNodes(draft.nodes);
    workflowStore.setEdges(draft.edges);
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

onBeforeRouteLeave((_to, _from, next) => {
  if (
    shouldWarnAboutUnsavedWorkflow() &&
    !window.confirm("This workflow has unsaved edits or a failed autosave. Leave this page?")
  ) {
    next(false);
    return;
  }
  next();
});

const sanitizeNodeIdSeed = (nodeType: string): string =>
  nodeType.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "node";

const createNodeId = (nodeType: string, existingNodes: WorkflowNode[] = workflowStore.nodes): string => {
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
const handleBroadcastMessage = (event: MessageEvent) =>
  _handleBroadcastMessage(event, nodes, workflowStore.updateNode, workflowStore.workflowId);

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
    console.log('[WorkflowBuilder] BroadcastChannel initialized');
  } catch (e) {
    console.warn('[WorkflowBuilder] BroadcastChannel not supported:', e);
  }

  await initializeWorkbook();

  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('beforeunload', handleBeforeUnload);
  window.addEventListener('pagehide', flushWorkflowDraftBeforeUnload);
  document.addEventListener('visibilitychange', flushWorkflowDraftBeforeUnload);
});

// Clean up BroadcastChannel and autosave timer on unmount
onUnmounted(() => {
  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
    console.log('[WorkflowBuilder] BroadcastChannel closed');
  }
  if (autosaveTimer.value !== null) {
    clearPendingAutosave();
  }
  clearPendingAutoExecute();
  clearDeleteUndoTimer();
  
  window.removeEventListener('keydown', handleKeyDown);
  window.removeEventListener('beforeunload', handleBeforeUnload);
  window.removeEventListener('pagehide', flushWorkflowDraftBeforeUnload);
  document.removeEventListener('visibilitychange', flushWorkflowDraftBeforeUnload);
});

// Watch for store changes - only react to node count changes (add/remove)
// NOT param changes which would reset selection during editing
watch(() => workflowStore.nodes.length, (newLength, oldLength) => {
  // Only clear selection if nodes were removed or workflow was cleared
  if (newLength < oldLength || newLength === 0) {
    nodeOutputs.value.clear();
    selectedNode.value = null;
  }
});

// Autosave watcher - trigger autosave when changes are made
watch(() => hasChanges.value, (hasChangesVal) => {
  // Clear any existing timer
  clearPendingAutosave();

  // Only autosave if:
  // 1. There are unsaved changes
  // 2. We have an existing workflow (not a brand new workflow)
  if (hasChangesVal && workflowStore.workflowId !== null) {
    autosaveStatus.value = 'idle';
    autosaveErrorMessage.value = "";
    const scheduledWorkflowId = workflowStore.workflowId;
    const scheduledSheetIndex = workbookStore.activeIndex;

    // Set up debounced autosave
    autosaveTimer.value = window.setTimeout(async () => {
      await triggerAutosave(scheduledWorkflowId, scheduledSheetIndex);
    }, AUTOSAVE_DELAY);
  } else if (!hasChangesVal) {
    // No changes, reset status
    autosaveStatus.value = 'idle';
    autosaveErrorMessage.value = "";
  }
});

watch(
  [
    () => workflowStore.nodes,
    () => workflowStore.edges,
    () => workflowStore.workflowName,
    () => workflowStore.workflowDescription,
  ],
  () => {
    persistWorkflowDraftSnapshot();
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

const workflowBadgeText = computed(() => {
  return workbookStore.activeSheet?.name || workflowStore.workflowName || "";
});

const workflowBadgeTitle = computed(() => {
  if (workflowStore.workflowHash) {
    return `${workflowBadgeText.value} — Integrity Hash: ${workflowStore.workflowHash}`;
  }
  return `${workflowBadgeText.value} — no integrity hash yet`;
});
const isTrialTabActive = computed(() => workbookStore.activeSheet?.kind === "trial");

const activeProjectName = computed(() =>
  projectStore.currentProject?.name || "No project selected",
);

const activeSheetName = computed(() =>
  workbookStore.activeSheet?.name || workflowStore.workflowName || "No sheet open",
);

const linkedDataLabel = computed(() => {
  // Per-active-sheet count, not project total: look up the active sheet's
  // workflow in ProjectDetail.workflows and tally the data sources it binds
  // (primary_data_source_id + data_source_ids, deduped). Switching sheets
  // re-runs this computed so the strip reflects the sheet you're on.
  const activeWorkflowId =
    workbookStore.activeSheet?.workflowId ?? workflowStore.workflowId;
  if (activeWorkflowId != null) {
    const wf = projectStore.currentProject?.workflows?.find(
      (entry) => entry.id === activeWorkflowId,
    );
    if (wf) {
      const ids = new Set<number>();
      if (wf.primary_data_source_id != null) ids.add(wf.primary_data_source_id);
      if (wf.data_source_ids) {
        for (const id of wf.data_source_ids) ids.add(id);
      }
      if (ids.size > 0) {
        return `${ids.size} dataset${ids.size === 1 ? "" : "s"} bound`;
      }
      return "No datasets bound";
    }
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
  const sheetName = workbookStore.activeSheet?.name;
  const scope = sheetName ? `Run the active sheet "${sheetName}"` : "Run the active sheet";
  if (isWorkflowStale.value) {
    return `${scope} — modified since last execution`;
  }
  return scope;
});

const hasExpensiveAutoExecuteNodes = computed(() =>
  nodes.value.some((node) => EXPENSIVE_AUTO_EXECUTE_TYPES.some((prefix) => node.type.startsWith(prefix))),
);

const buildOutputForNode = (nodeId: string, result: unknown): NodeOutput => {
  const node = nodes.value.find(n => n.id === nodeId);
  const outputPorts = node ? workflowStore.getNodeMetadata(node.type)?.output_ports : undefined;
  return buildNodeOutput(result, outputPorts);
};

const hasRenderableOutput = (output: NodeOutput): boolean => {
  if (Array.isArray(output.data) && output.data.length > 0) {
    return true;
  }
  if (output.plots && Object.keys(output.plots).length > 0) {
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
  if (!results) {
    return;
  }
  const nextOutputs = new Map(nodeOutputs.value);
  let changed = false;
  for (const [nodeId, result] of Object.entries(results)) {
    const output = buildOutputForNode(nodeId, result);
    if (!hasRenderableOutput(output)) {
      continue;
    }
    nextOutputs.set(nodeId, output);
    changed = true;
  }
  if (changed) {
    nodeOutputs.value = nextOutputs;
    if (workbookStore.activeSheet && workbookStore.activeSheet.kind !== "trial") {
      workbookStore.activeSheet.nodeOutputsCache = new Map(nextOutputs);
    }
  }
};

watch(
  () => workflowStore.lastExecutionResults,
  (results) => hydrateNodeOutputsFromRunResults(results as Record<string, unknown> | null),
);

// Compute input connections for selected node
const selectedNodeInputConnections = computed(() => {
  if (!selectedNode.value) return [];

  // Find edges pointing to this node (edge.to is the target node id)
  const incomingEdges = edges.value.filter(e => e.to === selectedNode.value!.id);

  return incomingEdges.map(edge => {
    const sourceNode = nodes.value.find(n => n.id === edge.from);
    const sourceOutput = sourceNode ? nodeOutputs.value.get(sourceNode.id) : null;
    const fromPort = edge.fromPort || sourceOutput?.primary_port || "default";
    const portOutput = sourceOutput?.ports?.[fromPort] || sourceOutput;

    return {
      nodeId: edge.from,
      nodeType: sourceNode?.type || 'Unknown',
      nodeLabel: sourceNode ? getNodeLabel(sourceNode.type) : 'Unknown',
      port: fromPort,
      toPort: edge.toPort || 'default',  // Include input port name for multi-input nodes
      data: portOutput || null,
    };
  });
});

// Provide workflow context to child components
provide('workflowContext', {
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

const triggerAutosave = async (expectedWorkflowId?: number | null, expectedSheetIndex?: number) => {
  autosaveTimer.value = null;
  if (
    expectedWorkflowId != null &&
    (workflowStore.workflowId !== expectedWorkflowId || workbookStore.activeIndex !== expectedSheetIndex)
  ) {
    autosaveStatus.value = 'idle';
    return;
  }
  if (workflowStore.workflowId === null && nodes.value.length === 0 && edges.value.length === 0) {
    return;
  }

  const isNewWorkflow = workflowStore.workflowId === null;
  autosaveStatus.value = 'saving';
  try {
    const savedId = await workflowStore.saveWorkflow({
      createVersion: false,
      projectId: workbookStore.projectId,
    });
    if (isNewWorkflow && workbookStore.projectId !== null) {
      await workbookStore.refreshSheets();
      await workbookStore.selectWorkflowSheet(savedId);
    }
    clearWorkflowDraftSnapshot();
    autosaveStatus.value = 'saved';
    autosaveErrorMessage.value = "";
    autosaveFailureToastShown.value = false;
    console.log('[WorkflowBuilder] Autosaved workflow');

    // Reset autosave indicator after 5 seconds
    setTimeout(() => {
      if (autosaveStatus.value === 'saved' && !hasChanges.value) {
        autosaveStatus.value = 'idle';
      }
    }, 5000);
  } catch (err: unknown) {
    autosaveStatus.value = 'error';
    autosaveErrorMessage.value = getErrorMessage(err, "Autosave failed");
    console.error('[WorkflowBuilder] Autosave failed:', err);
    if (!autosaveFailureToastShown.value) {
      toast.add({
        severity: "error",
        summary: "Autosave Failed",
        detail: "Your edits are kept as a local draft. Run or save again before leaving.",
        life: 6000,
      });
      autosaveFailureToastShown.value = true;
    }
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
    await workbookStore.loadSheets(targetProjectId);
    restoreWorkflowDraftSnapshot();
    resetCanvasUi();

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
    console.error('[WorkflowBuilder] Workbook load failed:', err);
    toast.add({
      severity: "error",
      summary: "Workbook Load Failed",
      detail: message,
      life: 5000,
    });
  }
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
  const wasDirty =
    workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null;
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
      
      const lastSelectedId = workbookStore.activeSheet?.lastSelectedNodeId;
      if (lastSelectedId) {
        const restoredNode = nodes.value.find(n => n.id === lastSelectedId);
        if (restoredNode) {
          selectedNode.value = restoredNode;
        }
      }

      // Restore cached outputs for this sheet
      if (workbookStore.activeSheet?.nodeOutputsCache) {
        nodeOutputs.value = new Map(workbookStore.activeSheet.nodeOutputsCache);
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
    await workbookStore.openTrialTab(nodeData, sourceWorkflowId, workbookStore.activeSheet?.tabColor ?? null);
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
  workflowStore.updateNode(nodeId, { params });
  await closeActiveTrialTab();
};

const exportToPython = async (mode: "sdk" | "standalone" = "sdk") => {
  try {
    const pythonCode = await workflowStore.exportToPython(mode);

    // Create download
    const suffix = mode === "standalone" ? "_standalone" : "";
    downloadText(
      pythonCode,
      `${workflowStore.workflowName.replace(/\s+/g, "_").toLowerCase()}${suffix}.py`,
      'text/plain',
    );

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: mode === "standalone" ? "Standalone Python script downloaded" : "SDK Python script downloaded",
      life: 2000,
    });
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: getErrorMessage(err, "Export failed — check that the workflow is saved and the backend is running"),
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

const exportMenuItems = [
  {
    label: "Python Script - SDK (.py)",
    icon: "pi pi-file",
    command: () => exportToPython("sdk"),
  },
  {
    label: "Python Script - Standalone (.py)",
    icon: "pi pi-file-export",
    command: () => exportToPython("standalone"),
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
];

const actionMenuItems = computed(() => [
  {
    label: "Analysis Starter",
    icon: "pi pi-sparkles",
    disabled: isTrialTabActive.value,
    command: () => {
      templatePickerVisible.value = true;
    },
  },
  {
    label: isWorkflowStale.value ? "Run (Mod)" : "Run",
    icon: "pi pi-play",
    disabled: isTrialTabActive.value || nodes.value.length === 0 || isExecuting.value || isBatchExecuting.value,
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
    items: exportMenuItems,
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

// Auto-execute toggle handler
const onAutoExecuteChange = () => {
  if (autoExecute.value && hasExpensiveAutoExecuteNodes.value) {
    const confirmed = window.confirm(
      "Auto update reruns modeling and selection workflows after connections or parameter edits. Enable it for this workflow?",
    );
    if (!confirmed) {
      autoExecute.value = false;
      autoExecuteAcceptedForExpensiveWorkflow.value = false;
      toast.add({
        severity: "info",
        summary: "Auto-Execute Disabled",
        detail: "Manual execution mode - click Run when you are ready.",
        life: 3000,
      });
      return;
    }
  }
  autoExecuteAcceptedForExpensiveWorkflow.value = autoExecute.value;
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
  if (!autoExecute.value || isExecuting.value || isBatchExecuting.value) return;
  if (hasExpensiveAutoExecuteNodes.value && !autoExecuteAcceptedForExpensiveWorkflow.value) {
    toast.add({
      severity: "warn",
      summary: "Auto-Execute Paused",
      detail: "This workflow includes modeling or selection nodes. Enable Auto update from settings to rerun automatically.",
      life: 4000,
    });
    return;
  }
  clearPendingAutoExecute();
  autoExecuteTimer.value = window.setTimeout(() => {
    autoExecuteTimer.value = null;
    void executeWorkflow();
  }, delayMs);
};

const onRunClick = async () => {
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

    const workflowSheets = workbookStore.sheets.filter((sheet) => sheet.kind !== "trial");
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
        summary: continueWorkbookOnError.value ? "Workbook Complete With Errors" : "Workbook Stopped",
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
  isExecuting.value = true;

  try {
    // Build initial data from DATA nodes using experiment store
    const initialData = await buildInitialData();

    // Execute via backend DAG executor
    const response = await workflowStore.executeWorkflow(initialData);

    // Convert backend results to frontend node outputs format
    const outputs = new Map<string, NodeOutput>();
    for (const [nodeId, result] of Object.entries(response.results)) {
      const output = buildOutputForNode(nodeId, result);
      const diagnostics = response.diagnostics?.[nodeId];
      if (diagnostics && typeof diagnostics === "object") {
        output.metadata = {
          ...output.metadata,
          diagnostics,
        };
      }
      // Debug: log what we're receiving from backend
      console.log(`[Workflow] Node ${nodeId} result:`, {
        hasData: !!output.data,
        dataType: Array.isArray(output.data) ? 'array' : typeof output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
        keys: Object.keys(result || {}),
      });

      outputs.set(nodeId, output);
    }

    // Assign new Map for proper Vue reactivity
    nodeOutputs.value = outputs;
    if (workbookStore.activeSheet && workbookStore.activeSheet.kind !== "trial") {
      workbookStore.activeSheet.nodeOutputsCache = new Map(outputs);
    }
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

const coerceNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const availableExperimentForDataset = (datasetId: number | null): ExperimentDataset | null => {
  if (datasetId === null) return null;
  return workflowStore.availableDatasets?.experiments.find(exp => exp.id === datasetId) ?? null;
};

const defaultMyDatasetTargetParams = (datasetId: number | null): Partial<ParamsMap> => {
  const exp = availableExperimentForDataset(datasetId);
  const targetNames = Array.isArray(exp?.target_names)
    ? exp.target_names.map(name => String(name)).filter(Boolean)
    : [];
  if (targetNames.length <= 1) {
    return { target_mode: "dataset_default", selected_target: null };
  }
  const mode = exp?.target_mode === "multi" ? "multi" : "single";
  const selected = exp?.selected_target && targetNames.includes(exp.selected_target)
    ? exp.selected_target
    : targetNames[0];
  return {
    target_mode: mode,
    selected_target: mode === "single" ? selected : null,
  };
};

// Build initial data for workflow execution from DATA nodes
const buildInitialData = async (): Promise<Record<string, unknown>> => {
  const initialData: Record<string, unknown> = {};

  // Find source DATA nodes
  const dataNodes = nodes.value.filter(n => n.type === 'data.source' || n.type === 'data.my_dataset');

  for (const node of dataNodes) {
    if (node.type === 'data.my_dataset') {
      const datasetId = coerceNumber(node.params.dataset_id);
      if (datasetId !== null) {
        initialData[String(node.id)] = {
          dataset_id: datasetId,
          source: 'experiment',
          target_mode: node.params.target_mode,
          selected_target: node.params.selected_target,
        };
      }
      continue;
    }
    const experimentId = coerceNumber(node.params.experiment_id);
    if (experimentId !== null) {
      initialData[String(node.id)] = {
        experiment_id: experimentId,
        source: node.params.source || 'experiment',
      };
    } else if (node.params.source) {
      // Pass all node params to the backend, including file_path
      initialData[String(node.id)] = {
        source: typeof node.params.source === "string" ? node.params.source : "file",
        file_path: typeof node.params.file_path === "string" ? node.params.file_path : "",
        format: typeof node.params.format === "string" ? node.params.format : "csv",
      };
    }
  }

  return initialData;
};

// Event handlers
const onAddNode = (nodeType: string) => {
  const newNode: WorkflowNode = {
    id: createNodeId(nodeType),
    type: nodeType,
    x: 100 + (workflowStore.nodes.length * 40) % 400,
    y: 100 + Math.floor(workflowStore.nodes.length / 4) * 120,
    params: getDefaultParams(nodeType),
  };
  workflowStore.addNode(newNode);
  selectedNode.value = newNode;
};

const getDefaultParams = (nodeType: string): ParamsMap => {
  // Get first available experiment ID for DATA nodes
  const projectExperiments = projectStore.currentProjectId == null
    ? experimentStore.experiments
    : experimentStore.experiments.filter(
        (experiment) => experiment.project_id === projectStore.currentProjectId,
      );
  const defaultExperimentId = projectExperiments.length > 0
    ? projectExperiments[0].id
    : null;

  const defaults: Record<string, ParamsMap> = {
    // Data Source nodes
    'data.source': {
      source: 'file',  // Default to file so users can enter path directly
      file_path: '',
      experiment_id: defaultExperimentId,
      format: 'csv',
    },
    'data.my_dataset': {
      dataset_id: defaultExperimentId,
      ...defaultMyDatasetTargetParams(defaultExperimentId),
    },
    'data.nist_library': {
      library_id: null,
      compound_name: '',
    },
    'data.synthetic_curve': {
      curve_type: 'sigmoid',
      n_points: 100,
      max_concentration: 1.0,
      center: 0.5,
      width: 0.1,
    },
    // Synthesis nodes
    'synthesis.species': {
      species_name: 'Species',
      molar_absorptivity: 1.0,
    },
    'synthesis.blend': {
      n_timepoints: 100,
      model_type: 'linear',
      pathlength: 0.01,
      noise_level: 0.01,
    },
    'synthesis.merge': {
      align_wavenumbers: true,
    },
    // Preprocessing nodes
    'preprocess.normalize': { method: 'snv' },
    'preprocess.scale': { method: 'mean_center' },
    'baseline.penalized_ls': { method: 'als', lam: 100000, p: 0.001 },
    'preprocess.smooth': { method: 'savitzky_golay', size: 15, order: 2 },
    'preprocess.cosmic_ray': { window: 5, zscore: 3.0 },
    'preprocess.clip_range': { min_wavenumber: 400, max_wavenumber: 4000 },
    // Analysis nodes - use backend parameter names directly (n_components)
    'model.pca': { n_components: "5", standardized: false, scaled: false },
    'model.pls': { n_components: 3, scale: false },
    'model.mcr_als': {
      n_components: 3,
      max_iter: 200,
      tol: 0.00001,
      normSpec: 'euclid',
      non_negative_C: true,
      non_negative_St: true,
    },
    'model.efa': { n_components: 10, direction: 'both' },
    'model.pcr': { n_components: 3, scale: true },
    'model.svr': { kernel: 'rbf', C: 1.0, epsilon: 0.1, gamma: 'scale', degree: 3, coef0: 0.0, scale: true },
    'model.kmeans': { n_clusters: 3, n_init: 10, max_iter: 300, random_state: 42 },
    'model.dbscan': { eps: 0.5, min_samples: 5, metric: 'euclidean' },
    'model.hca': { n_clusters: 3, linkage: 'ward', metric: 'euclidean' },
    'model.simplisma': { n_components: 3, noise: 3 },
    'stats.summary': {},
    'analysis.peak_id': { compound: '' },
    'analysis.compare_library': { top_n: 10, library_filter: '' },
    // Classification nodes
    'classification.plsda': { n_components: 3, scale: false },
    'classification.knn': { n_neighbors: 5, metric: 'euclidean' },
    'classification.simca': { n_components: 3, confidence_level: 0.95 },
    // Output nodes
    'output.plot': { plot_type: 'spectra' },
    'output.contour': { colorscale: 'Viridis', plot_type: 'heatmap', reverse_x: false, transpose: false },
    'output.export': { filename: 'output.csv', format: 'csv' },
    // Legacy
    'analysis.peak_finding': { method: 'find_peaks', prominence: 0.01 },
  };
  return defaults[nodeType] || {};
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
  }
);

const onNodeConnect = (connection: { from: string; to: string; fromPort?: string; toPort?: string }) => {
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

const stripUndefinedAndDefaultParams = (
  nodeType: string,
  params: ParamsMap,
): ParamsMap => {
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
  const node = nodes.value.find(n => n.id === nodeId);
  if (!node) return;

  try {
    // Always build initial data - any node may depend on DATA nodes
    const initialData = await buildInitialData();

    // Execute single node via backend
    const response = await workflowStore.executeNode(nodeId, initialData);

    // Update outputs - create new Map for proper Vue reactivity
    const newOutputs = new Map(nodeOutputs.value);
    for (const [nId, result] of Object.entries(response.results)) {
      const output = buildOutputForNode(nId, result);
      const diagnostics = response.diagnostics?.[nId];
      if (diagnostics && typeof diagnostics === "object") {
        output.metadata = {
          ...output.metadata,
          diagnostics,
        };
      }
      // Debug: log what we're receiving from backend
      console.log(`[Workflow] Node ${nId} result:`, {
        hasData: !!output.data,
        dataType: Array.isArray(output.data) ? 'array' : typeof output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
        firstRowType: Array.isArray(output.data) && output.data[0] ? (Array.isArray(output.data[0]) ? 'array' : typeof output.data[0]) : 'N/A',
        keys: Object.keys(result || {}),
      });
      newOutputs.set(nId, output);
    }
    nodeOutputs.value = newOutputs;

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

.section-title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

/* Context strip: 4 read-only cells, hairline-only — no boxed background,
   vertical hairlines between cells, hairline below. */
.workflow-context-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  align-items: center;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--surface-border);
  margin-bottom: 1rem;
}

.workflow-context-item {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
  padding: 0 1rem;
  border-right: 1px solid var(--surface-border);
}

.workflow-context-item:first-child {
  padding-left: 0;
}

.workflow-context-item span {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.workflow-context-item strong {
  overflow: hidden;
  color: var(--text-color);
  font-size: 1rem;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}


.workflow-meta-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
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

.header-actions :deep(.toolbar-settings-btn.p-button) {
  width: 34px;
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
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.canvas-container.trial-container {
  min-height: 0;
  overflow: auto;
}

.canvas-container > * {
  flex: 1 1 auto;
  min-height: 100%;
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
}

@media (max-width: 900px) {
  .workflow-context-strip {
    grid-template-columns: 1fr;
  }

  .workflow-workspace {
    grid-template-columns: 1fr;
  }
  .workflow-workspace.inspector-open {
    grid-template-columns: 1fr;
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
