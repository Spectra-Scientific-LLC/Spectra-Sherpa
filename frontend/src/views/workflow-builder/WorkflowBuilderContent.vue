<template>
  <section class="workflow-builder-content">
    <div class="section-header">
      <div class="section-title-row">
        <h1>Workflow Builder</h1>
        <span
          v-if="workflowBadgeText"
          class="workflow-meta-badge"
          :title="workflowBadgeTitle"
        >
          <i :class="workflowStore.workflowHash ? 'pi pi-lock' : 'pi pi-bookmark'"></i>
          {{ workflowBadgeText }}
        </span>
      </div>

      <div class="header-actions">
        <div class="toolbar-action-group">
          <Button
            :label="isWorkflowStale ? 'Run (Mod)' : 'Run'"
            icon="pi pi-play"
            data-action="run_workflow"
            class="toolbar-btn toolbar-action-btn"
            :loading="isExecuting || isBatchExecuting"
            :disabled="isTrialTabActive || nodes.length === 0 || isExecuting || isBatchExecuting"
            @click="onRunClick"
            :title="runButtonTitle"
          />
          <Button
            label="New"
            icon="pi pi-plus"
            class="toolbar-btn toolbar-action-btn"
            :disabled="isTrialTabActive"
            @click="createNewWorkflow"
          />
          <Button
            :label="saveButtonLabel"
            icon="pi pi-save"
            data-action="save_workflow"
            class="toolbar-btn toolbar-action-btn"
            :disabled="isTrialTabActive || (!hasChanges && autosaveStatus !== 'saving')"
            @click="saveWorkflow"
            title="Save workflow definition"
          />
          <Button
            :label="memoryButtonLabel"
            :icon="isCompactingMemory ? 'pi pi-spin pi-spinner' : 'pi pi-bookmark'"
            class="toolbar-btn toolbar-action-btn"
            :disabled="isTrialTabActive || isCompactingMemory || activeAdvisorNodeId === null"
            @click="onSaveMemoryClick"
            title="Compact this scope's Sherpa Advisor conversation into durable memory"
          />
          <Button
            label="Export"
            icon="pi pi-download"
            class="toolbar-btn toolbar-action-btn"
            :disabled="isTrialTabActive"
            @click="toggleExportMenu"
          />
        </div>
        <Menu ref="exportMenuRef" :model="exportMenuItems" :popup="true" />

        <span v-if="autosaveStatus === 'saved'" class="autosave-indicator">
          <i class="pi pi-check"></i> Saved
        </span>

        <Button
          label="Actions"
          icon="pi pi-bars"
          class="toolbar-btn toolbar-action-btn toolbar-actions-menu-btn"
          @click="toggleActionMenu"
        />
        <TieredMenu ref="actionMenuRef" :model="actionMenuItems" :popup="true" />

        <Button
          icon="pi pi-cog"
          class="toolbar-btn toolbar-action-btn toolbar-settings-btn"
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
            <label class="toolbar-state-control" title="Compact and save the active sheet's Sherpa Advisor memory whenever the workflow is explicitly saved">
              <Checkbox
                v-model="autoSaveMemory"
                binary
                input-id="workflow-auto-save-memory"
              />
              <span>Auto save memory</span>
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
      </div>
    </div>

    <!-- Execution status banner -->
    <div v-if="executionCount > 0" class="execution-banner">
      <i class="pi pi-check-circle"></i>
      <span>Workflow executed {{ executionCount }} time{{ executionCount !== 1 ? 's' : '' }}</span>
      <span v-if="lastExecutionTime" class="execution-time">Last run: {{ lastExecutionTime }}</span>
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
import TieredMenu from "primevue/tieredmenu";
import OverlayPanel from "primevue/overlaypanel";
import { useToast } from "primevue/usetoast";
import { useRoute } from "vue-router";
import { useWorkflowStore, type WorkflowNode, type WorkflowEdge } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import { useProjectStore } from "@/stores/project";
import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowBuilderConfigStore } from "@/stores/workflowBuilderConfig";
import { useClipboardStore, type ClipboardPayload } from "@/stores/clipboard";
import { useAdvisorStore } from "@/stores/advisor";
import WorkbookSheetTabs from "@/components/WorkbookSheetTabs.vue";
import WorkflowToolbar from "./WorkflowToolbar.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import WorkflowInspector from "./WorkflowInspector.vue";
import NodeDetailView from "./NodeDetailView.vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import { downloadText } from "@/utils/download";
import { getErrorMessage } from "@/utils/errors";
import { handleBroadcastMessage as _handleBroadcastMessage } from "./handleBroadcastMessage";

type ParamsMap = Record<string, unknown>;

const toast = useToast();
const route = useRoute();
const workflowStore = useWorkflowStore();
const experimentStore = useExperimentStore();
const projectStore = useProjectStore();
const workbookStore = useWorkbookStore();
const workflowBuilderConfigStore = useWorkflowBuilderConfigStore();
const { autoExecute, autoSaveMemory } = storeToRefs(workflowBuilderConfigStore);
const clipboardStore = useClipboardStore();
const advisorStore = useAdvisorStore();
const isCompactingMemory = ref(false);
const activeAdvisorNodeId = computed(() => advisorStore.activeNodeId);
const memoryButtonLabel = computed(() => (isCompactingMemory.value ? "Saving…" : "Save Memory"));
const canvasRef = ref();
const exportMenuRef = ref();
const actionMenuRef = ref();
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

  if (isCmdOrCtrl && e.key.toLowerCase() === 'c') {
    onCopySelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && e.key.toLowerCase() === 'x') {
    onCutSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && e.key.toLowerCase() === 'v') {
    onPasteSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && e.key.toLowerCase() === 'd') {
    onDuplicateSelection();
    e.preventDefault();
  } else if (isCmdOrCtrl && e.key.toLowerCase() === 'a') {
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

const onDeleteSelection = () => {
  if (!canvasRef.value?.selectedNodeIds) return;
  const selectedIds = canvasRef.value.selectedNodeIds;
  if (selectedIds.size === 0) return;

  const updatedNodes = workflowStore.nodes.filter(n => !selectedIds.has(n.id));
  const updatedEdges = workflowStore.edges.filter(e => !selectedIds.has(e.from) && !selectedIds.has(e.to));

  workflowStore.setNodes(updatedNodes);
  workflowStore.setEdges(updatedEdges);
  
  canvasRef.value.clearSelection();
  workflowStore.hasUnsavedChanges = true;
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
const autosaveStatus = ref<'idle' | 'saving' | 'saved'>('idle');
const autosaveTimer = ref<number | null>(null);
const AUTOSAVE_DELAY = 30000; // 30 seconds

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
  _handleBroadcastMessage(event, nodes, workflowStore.updateNode);

// Load supporting data for the workflow bench
onMounted(async () => {
  // Load experiments for DATA node selection
  if (experimentStore.experiments.length === 0) {
    try {
      await experimentStore.fetchExperiments();
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
});

// Clean up BroadcastChannel and autosave timer on unmount
onUnmounted(() => {
  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
    console.log('[WorkflowBuilder] BroadcastChannel closed');
  }
  if (autosaveTimer.value !== null) {
    window.clearTimeout(autosaveTimer.value);
  }
  
  window.removeEventListener('keydown', handleKeyDown);
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
  if (autosaveTimer.value !== null) {
    clearTimeout(autosaveTimer.value);
    autosaveTimer.value = null;
  }

  // Only autosave if:
  // 1. There are unsaved changes
  // 2. We have an existing workflow (not a brand new workflow)
  if (hasChangesVal && workflowStore.workflowId !== null) {
    autosaveStatus.value = 'idle';

    // Set up debounced autosave
    autosaveTimer.value = window.setTimeout(async () => {
      await triggerAutosave();
    }, AUTOSAVE_DELAY);
  } else if (!hasChangesVal) {
    // No changes, reset status
    autosaveStatus.value = 'idle';
  }
});

// Execution state
const isExecuting = ref(false);
const executionCount = ref(0);
const lastExecutionTime = ref<string | null>(null);

// BroadcastChannel for cross-tab communication with NodeDetailView
const BROADCAST_CHANNEL_NAME = "workflow_node_updates";
const broadcastChannel = ref<BroadcastChannel | null>(null);

// Node type labels for display
const NODE_LABELS: Record<string, string> = {
  'data.source': 'Load Data',
  'preprocess.normalize': 'Normalize',
  'preprocess.scale': 'Scale',
  'baseline.penalized_ls': 'Baseline',
  'preprocess.smooth': 'Smooth',
  'model.pca': 'PCA',
  'model.pls': 'PLS',
  'model.mcr_als': 'MCR-ALS',
  'stats.summary': 'Statistics',
  'output.plot': 'Plot',
  'output.contour': 'Contour Plot',
  'output.export': 'Export',
};

const getNodeLabel = (nodeType: string): string => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.label) {
    return metadata.label;
  }
  return NODE_LABELS[nodeType] || nodeType;
};

// Computed
const selectedNodeOutput = computed(() => {
  if (!selectedNode.value) return null;
  return nodeOutputs.value.get(selectedNode.value.id) || null;
});

const saveButtonLabel = computed(() => {
  if (autosaveStatus.value === 'saving') return 'Saving...';
  if (autosaveStatus.value === 'saved' && !hasChanges.value) return 'Saved';
  return 'Save';
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

const runButtonTitle = computed(() => {
  const sheetName = workbookStore.activeSheet?.name;
  const scope = sheetName ? `Run the active sheet "${sheetName}"` : "Run the active sheet";
  if (isWorkflowStale.value) {
    return `${scope} — modified since last execution`;
  }
  return scope;
});

const buildOutputForNode = (nodeId: string, result: unknown): NodeOutput => {
  const node = nodes.value.find(n => n.id === nodeId);
  const outputPorts = node ? workflowStore.getNodeMetadata(node.type)?.output_ports : undefined;
  return buildNodeOutput(result, outputPorts);
};

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

const createNewWorkflow = () => {
  if (hasChanges.value) {
    if (!window.confirm("Clear this sheet? Unsaved changes will be replaced by an empty canvas.")) {
      return;
    }
  }
  workflowStore.setNodes([]);
  workflowStore.setEdges([]);
  resetCanvasUi();
  toast.add({
    severity: "info",
    summary: "Sheet Cleared",
    detail: "Cleared the active workflow canvas",
    life: 2000,
  });
};

const onSaveMemoryClick = async () => {
  if (isCompactingMemory.value || activeAdvisorNodeId.value === null) return;
  isCompactingMemory.value = true;
  try {
    const result = await advisorStore.compactScope();
    if (result?.compacted) {
      toast.add({
        severity: "success",
        summary: "Memory saved",
        detail: `Compacted ${result.messageCount ?? 0} messages into scope memory v${result.version ?? "?"}.`,
        life: 2500,
      });
    } else {
      toast.add({
        severity: "info",
        summary: "Nothing to save",
        detail: "Not enough new conversation to compact yet.",
        life: 2500,
      });
    }
  } catch (err: unknown) {
    toast.add({
      severity: "warn",
      summary: "Save Memory failed",
      detail: getErrorMessage(err, "Could not compact scope memory"),
      life: 3000,
    });
  } finally {
    isCompactingMemory.value = false;
  }
};

const saveWorkflow = async () => {
  try {
    const savedId = await workflowStore.saveWorkflow();
    if (autoSaveMemory.value && activeAdvisorNodeId.value !== null) {
      // Fire-and-forget: workflow save is the primary user action, so
      // we don't await compaction.  Failures are surfaced via the
      // adapter's own error path; success is silent (no toast spam).
      void advisorStore.compactScope();
    }
    autosaveStatus.value = 'saved';
    toast.add({
      severity: "success",
      summary: "Saved",
      detail: `Workflow saved (ID: ${savedId})`,
      life: 2000,
    });
  } catch (err: unknown) {
    const message = getErrorMessage(err, "Unable to save workflow");
    toast.add({
      severity: "error",
      summary: "Save Failed",
      detail: message,
      life: 3000,
    });
  }
};

const triggerAutosave = async () => {
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
    autosaveStatus.value = 'saved';
    console.log('[WorkflowBuilder] Autosaved workflow');

    // Reset autosave indicator after 5 seconds
    setTimeout(() => {
      if (autosaveStatus.value === 'saved' && !hasChanges.value) {
        autosaveStatus.value = 'idle';
      }
    }, 5000);
  } catch (err: unknown) {
    autosaveStatus.value = 'idle';
    console.error('[WorkflowBuilder] Autosave failed:', err);
    // Don't show error toast for autosave failures to avoid interrupting user
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

  // Cache current outputs before switching
  if (workbookStore.activeSheet && workbookStore.activeSheet.kind !== "trial") {
    workbookStore.activeSheet.nodeOutputsCache = new Map(nodeOutputs.value);
  }

  try {
    await workbookStore.switchSheet(index);
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

const exportToPython = async () => {
  try {
    // Get Python code from backend API
    const pythonCode = await workflowStore.exportToPython();

    // Create download
    downloadText(
      pythonCode,
      `${workflowStore.workflowName.replace(/\s+/g, '_').toLowerCase()}.py`,
      'text/plain',
    );

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: "Python script downloaded",
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
    label: "Python Script (.py)",
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
];

const actionMenuItems = computed(() => [
  {
    label: isWorkflowStale.value ? "Run (Mod)" : "Run",
    icon: "pi pi-play",
    disabled: isTrialTabActive.value || nodes.value.length === 0 || isExecuting.value || isBatchExecuting.value,
    command: onRunClick,
  },
  {
    label: "New",
    icon: "pi pi-plus",
    disabled: isTrialTabActive.value,
    command: createNewWorkflow,
  },
  {
    label: saveButtonLabel.value,
    icon: "pi pi-save",
    disabled: isTrialTabActive.value || (!hasChanges.value && autosaveStatus.value !== "saving"),
    command: saveWorkflow,
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
]);

const toggleExportMenu = (event: Event) => {
  exportMenuRef.value?.toggle(event);
};

const toggleActionMenu = (event: Event) => {
  actionMenuRef.value?.toggle(event);
};

// Auto-execute toggle handler
const onAutoExecuteChange = () => {
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

// Build initial data for workflow execution from DATA nodes
const buildInitialData = async (): Promise<Record<string, unknown>> => {
  const initialData: Record<string, unknown> = {};

  // Find all DATA nodes
  const dataNodes = nodes.value.filter(n => n.type === 'data.source');

  for (const node of dataNodes) {
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
  const defaultExperimentId = experimentStore.experiments.length > 0
    ? experimentStore.experiments[0].id
    : null;

  const defaults: Record<string, ParamsMap> = {
    // Data Source nodes
    'data.source': {
      source: 'file',  // Default to file so users can enter path directly
      file_path: '',
      experiment_id: defaultExperimentId,
      format: 'csv',
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
    'model.pls': { n_components: 3, scale: true },
    'model.mcr_als': { n_components: 3, max_iter: 100 },
    'model.efa': { n_components: 10, direction: 'both' },
    'model.pcr': { n_components: 3, scale: true },
    'model.svr': { kernel: 'rbf', C: 1.0, epsilon: 0.1, gamma: 'scale', degree: 3, coef0: 0.0, scale: true },
    'model.kmeans': { n_clusters: 3, n_init: 10, max_iter: 300, random_state: 42 },
    'model.dbscan': { eps: 0.5, min_samples: 5, metric: 'euclidean' },
    'model.hca': { n_clusters: 3, linkage: 'ward', metric: 'euclidean' },
    'model.simplisma': { n_components: 3, noise: 3 },
    'stats.summary': {},
    // Classification nodes
    'classification.plsda': { n_components: 3, scale: true },
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
  if (autoExecute.value && !isExecuting.value && !isBatchExecuting.value) {
    setTimeout(() => executeWorkflow(), 500); // Debounce slightly
  }
};

const onConnectionError = (errorMessage: string) => {
  toast.add({
    severity: "error",
    summary: "Invalid Connection",
    detail: errorMessage,
    life: 4000,
  });
};

const onUpdateParams = (nodeId: string, params: ParamsMap) => {
  workflowStore.updateNode(nodeId, { params });

  // Auto-execute if enabled (with longer debounce for parameter changes)
  if (autoExecute.value && !isExecuting.value && !isBatchExecuting.value) {
    setTimeout(() => executeWorkflow(), 1000); // Longer debounce for params
  }
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
  workflowStore.removeNode(nodeId);
  if (selectedNode.value?.id === nodeId) {
    selectedNode.value = null;
  }
  nodeOutputs.value.delete(nodeId);
};
</script>

<style scoped>
.workflow-builder-content {
  display: flex;
  flex-direction: column;
  padding: 16px;
  background: #0f172a;
  color: #f8fafc;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.section-header h1 {
  flex: 0 0 auto;
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
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
  gap: 10px;
  padding: 10px 16px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 8px;
  color: #4ade80;
  font-size: 0.9rem;
  margin-bottom: 16px;
}

.execution-banner i {
  font-size: 1.1rem;
}

.execution-time {
  margin-left: auto;
  color: #94a3b8;
  font-size: 0.85rem;
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

@media (max-width: 1200px) {
  .workflow-workspace.inspector-open {
    grid-template-columns: 180px 1fr 280px;
  }
  .workflow-workspace.toolbar-collapsed.inspector-open {
    grid-template-columns: 44px 1fr 280px;
  }
}

@media (max-width: 1280px) {
  .toolbar-action-group {
    display: none;
  }

  .header-actions :deep(.toolbar-actions-menu-btn.p-button) {
    display: inline-flex;
  }
}

@media (max-width: 900px) {
  .workflow-workspace {
    grid-template-columns: 1fr;
  }
  .workflow-workspace.inspector-open {
    grid-template-columns: 1fr;
  }

  .section-header {
    align-items: flex-start;
    flex-direction: column;
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
