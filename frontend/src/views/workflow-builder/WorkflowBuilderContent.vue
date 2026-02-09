<template>
  <section class="workflow-builder-content">
    <div class="section-header">
      <div>
        <h1>Workflow Builder</h1>
        <p class="section-subtitle">
          Visual graph-based analysis pipeline for spectral data
          <span
            v-if="workflowStore.workflowHash"
            class="integrity-hash-badge"
            :title="`Integrity Hash: ${workflowStore.workflowHash}`"
          >
            <i class="pi pi-lock"></i>
            {{ workflowStore.workflowHash.slice(0, 12) }}
          </span>
        </p>
      </div>

      <div class="header-actions">
        <Button
          :label="isWorkflowStale ? 'Execute Workflow (Modified)' : 'Execute Workflow'"
          icon="pi pi-play"
          :class="isWorkflowStale ? 'p-button-warning execute-stale' : 'p-button-success'"
          :loading="isExecuting"
          :disabled="nodes.length === 0"
          @click="executeWorkflow"
          :title="isWorkflowStale ? 'Workflow has been modified since last execution' : 'Execute workflow'"
        />
        <div class="auto-execute-toggle">
          <ToggleButton
            v-model="autoExecute"
            onLabel="Auto-Execute: ON"
            offLabel="Auto-Execute: OFF"
            onIcon="pi pi-bolt"
            offIcon="pi pi-bolt"
            class="p-button-sm"
            :title="autoExecute ? 'Workflow will auto-execute when nodes connect or parameters change' : 'Manual execution mode - click Execute Workflow to run'"
            @change="onAutoExecuteChange"
          />
        </div>
        <Button
          label="New"
          icon="pi pi-plus"
          class="p-button-secondary"
          @click="createNewWorkflow"
        />
        <Button
          :label="saveButtonLabel"
          icon="pi pi-save"
          :disabled="!hasChanges && autosaveStatus !== 'saving'"
          @click="saveWorkflow"
        />
        <span v-if="autosaveStatus === 'saved'" class="autosave-indicator">
          <i class="pi pi-check"></i> Autosaved
        </span>
        <Button
          label="Export Python"
          icon="pi pi-download"
          class="p-button-outlined"
          @click="exportToPython"
        />
        <Button
          label="Report"
          icon="pi pi-file"
          class="p-button-outlined"
          :disabled="!workflowStore.lastExecutionResults"
          title="Generate provenance report (requires execution results)"
          @click="generateReport"
        />
      </div>
    </div>

    <!-- Execution status banner -->
    <div v-if="executionCount > 0" class="execution-banner">
      <i class="pi pi-check-circle"></i>
      <span>Workflow executed {{ executionCount }} time{{ executionCount !== 1 ? 's' : '' }}</span>
      <span v-if="lastExecutionTime" class="execution-time">Last run: {{ lastExecutionTime }}</span>
    </div>

    <!-- Three-column layout: Toolbar | Canvas | Inspector Sidebar -->
    <div class="workflow-workspace" :class="{ 'inspector-open': inspectorOpen }">
      <!-- Left Panel: Node Toolbar -->
      <WorkflowToolbar @add-node="onAddNode" />

      <!-- Center: Canvas -->
      <div class="canvas-container">
        <WorkflowCanvas
          ref="canvasRef"
          :nodes="nodes"
          :edges="edges"
          :node-outputs="nodeOutputs"
          @update:nodes="onNodesUpdate"
          @update:edges="onEdgesUpdate"
          @node-select="onNodeSelect"
          @node-connect="onNodeConnect"
          @connection-error="onConnectionError"
        />
      </div>

      <!-- Right Panel: Inspector Sidebar (persistent until closed) -->
      <WorkflowInspector
        :selected-node="selectedNode"
        :node-output="selectedNodeOutput"
        :input-connections="selectedNodeInputConnections"
        :is-open="inspectorOpen"
        @update-params="onUpdateParams"
        @execute-node="onExecuteNode"
        @delete-node="onDeleteNode"
        @close="onCloseInspector"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, provide, watch, onMounted, onUnmounted } from "vue";
import Button from "primevue/button";
import ToggleButton from "primevue/togglebutton";
import { useToast } from "primevue/usetoast";
import { useWorkflowStore, type WorkflowNode, type WorkflowEdge } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import WorkflowToolbar from "./WorkflowToolbar.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import WorkflowInspector from "./WorkflowInspector.vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import { useReportExport } from "@/composables/useReportExport";
import { getErrorMessage } from "@/utils/errors";

type ParamsMap = Record<string, unknown>;

const toast = useToast();
const workflowStore = useWorkflowStore();
const experimentStore = useExperimentStore();
const { exportReport } = useReportExport();
const canvasRef = ref();

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
const nodeOutputs = ref<Map<number, NodeOutput>>(new Map());
const nextNodeId = ref(2);
const inspectorOpen = ref(false);
const autoExecute = ref(false); // Auto-execute workflow when nodes connect or parameters change

// Autosave state
const autosaveStatus = ref<'idle' | 'saving' | 'saved'>('idle');
const autosaveTimer = ref<number | null>(null);
const AUTOSAVE_DELAY = 30000; // 30 seconds

// Handle BroadcastChannel messages from NodeDetailView
const handleBroadcastMessage = async (event: MessageEvent) => {
  const { type, nodeId, params, nodeType, persistParams } = event.data;

  // Handle param updates from DetailView (only on "Save and Exit")
  if (type === 'node_params_updated') {
    const node = nodes.value.find(n => n.id === nodeId);
    if (node && params) {
      console.log('[WorkflowBuilder] Received param update from DetailView:', { nodeId, params });
      workflowStore.updateNode(nodeId, { params });
    }
  }

  // Handle execution requests from DetailView - works for ANY node, not just selected
  if (type === 'execute_node_request') {
    console.log('[WorkflowBuilder] Received execute request from DetailView:', { nodeId, nodeType, persistParams });

    const node = nodes.value.find(n => n.id === nodeId);
    if (!node) {
      console.warn('[WorkflowBuilder] Node not found:', nodeId);
      // Send error back
      if (broadcastChannel.value) {
        broadcastChannel.value.postMessage({
          type: 'node_execution_result',
          nodeId,
          output: null,
          error: `Node ${nodeId} not found in workflow`,
          timestamp: Date.now(),
        });
      }
      return;
    }

    // Save original params if we're not persisting (for restore after execution)
    const originalParams = persistParams === false ? { ...node.params } : null;

    // Temporarily update node params for execution
    if (params) {
      workflowStore.updateNode(nodeId, { params });
    }

    // Execute the node
    try {
      const initialData = await buildInitialData();
      const response = await workflowStore.executeNode(String(nodeId), initialData);

      // Update outputs
      const newOutputs = new Map(nodeOutputs.value);
      let executedNodeOutput: NodeOutput | null = null;

      for (const [nId, result] of Object.entries(response.results)) {
        const resolvedNodeId = workflowStore.resolveFrontendNodeId(nId);
        if (resolvedNodeId === null) {
          console.warn("[WorkflowBuilder] Could not resolve backend node ID:", nId);
          continue;
        }
        const output = buildOutputForNode(resolvedNodeId, result);
        newOutputs.set(resolvedNodeId, output);

        // Track the specific node's output for the broadcast response
        // Use string comparison to handle type mismatches
        if (String(resolvedNodeId) === String(nodeId)) {
          console.log('[WorkflowBuilder] Found matching output for node:', nodeId);
          executedNodeOutput = output;
        }
      }
      nodeOutputs.value = newOutputs;

      // Broadcast result back to DetailView
      if (broadcastChannel.value) {
        console.log('[WorkflowBuilder] Sending execution result back:', {
          nodeId,
          nodeIdType: typeof nodeId,
          hasOutput: !!executedNodeOutput,
          outputDataLength: executedNodeOutput?.data?.length || 0,
          resultKeys: Object.keys(response.results || {}),
        });
        broadcastChannel.value.postMessage({
          type: 'node_execution_result',
          nodeId,
          output: executedNodeOutput,
          error: response.error || null,
          timestamp: Date.now(),
        });
      }

      // Restore original params if we didn't want to persist
      if (originalParams !== null) {
        workflowStore.updateNode(nodeId, { params: originalParams });
        console.log('[WorkflowBuilder] Restored original params (not persisting)');
      }

      if (!response.error) {
        toast.add({
          severity: "success",
          summary: "Node Executed",
          detail: `${node.type} completed (from DetailView)`,
          life: 2000,
        });
      }
    } catch (error: unknown) {
      // Restore original params even on error
      if (originalParams !== null) {
        workflowStore.updateNode(nodeId, { params: originalParams });
        console.log('[WorkflowBuilder] Restored original params after error');
      }

      const message = getErrorMessage(error);

      // Send error back to DetailView
      if (broadcastChannel.value) {
        broadcastChannel.value.postMessage({
          type: 'node_execution_result',
          nodeId,
          output: null,
          error: message,
          timestamp: Date.now(),
        });
      }

      toast.add({
        severity: "error",
        summary: "Node Failed",
        detail: message,
        life: 3000,
      });
    }
  }
};

// Initialize nextNodeId based on existing nodes and load experiments
onMounted(async () => {
  if (workflowStore.nodes.length > 0) {
    const maxId = Math.max(...workflowStore.nodes.map(n => n.id));
    nextNodeId.value = maxId + 1;
  }

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

  // Autoload most recent workflow
  await autoloadMostRecentWorkflow();
});

// Clean up BroadcastChannel and autosave timer on unmount
onUnmounted(() => {
  if (broadcastChannel.value) {
    broadcastChannel.value.close();
    broadcastChannel.value = null;
    console.log('[WorkflowBuilder] BroadcastChannel closed');
  }
  if (autosaveTimer.value !== null) {
    clearTimeout(autosaveTimer.value);
  }
});

// Watch for store changes - only react to node count changes (add/remove)
// NOT param changes which would reset selection during editing
watch(() => workflowStore.nodes.length, (newLength, oldLength) => {
  if (newLength > 0) {
    const maxId = Math.max(...workflowStore.nodes.map(n => n.id));
    nextNodeId.value = maxId + 1;
  }
  // Only clear selection if nodes were removed or workflow was cleared
  if (newLength < oldLength || newLength === 0) {
    nodeOutputs.value.clear();
    selectedNode.value = null;
  }
});

// Autosave watcher - trigger autosave when changes are made
watch(() => hasChanges.value, (hasChanges) => {
  // Clear any existing timer
  if (autosaveTimer.value !== null) {
    clearTimeout(autosaveTimer.value);
    autosaveTimer.value = null;
  }

  // Only autosave if:
  // 1. There are unsaved changes
  // 2. We have an existing workflow (not a brand new workflow)
  if (hasChanges && workflowStore.workflowId !== null) {
    autosaveStatus.value = 'idle';

    // Set up debounced autosave
    autosaveTimer.value = window.setTimeout(async () => {
      await triggerAutosave();
    }, AUTOSAVE_DELAY);
  } else if (!hasChanges) {
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
  'DATA': 'Load Data',
  'NORMALIZE': 'Normalize',
  'SCALE': 'Scale',
  'BASELINE': 'Baseline',
  'SMOOTH': 'Smooth',
  'PCA': 'PCA',
  'PLS': 'PLS',
  'MCR': 'MCR-ALS',
  'STATS': 'Statistics',
  'PLOT': 'Scatter Plot',
  'CONTOUR_PLOT': 'Contour Plot',
  'EXPORT': 'Export',
};

const getNodeLabel = (nodeType: string): string => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.label) {
    return metadata.label;
  }
  const legacyType = workflowStore.getLegacyNodeType(nodeType);
  return NODE_LABELS[legacyType] || nodeType;
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

const buildOutputForNode = (nodeId: number, result: unknown): NodeOutput => {
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
const createNewWorkflow = () => {
  if (hasChanges.value) {
    // TODO: Prompt save confirmation
  }
  workflowStore.clearWorkflow();
  workflowStore.addNode({ id: 1, type: workflowStore.normalizeNodeType('DATA'), x: 50, y: 150, params: { source: 'experiment' } });
  selectedNode.value = null;
  nodeOutputs.value.clear();
  nextNodeId.value = 2;
  executionCount.value = 0;
  toast.add({
    severity: "info",
    summary: "New Workflow",
    detail: "Created new workflow canvas",
    life: 2000,
  });
};

const saveWorkflow = async () => {
  try {
    const savedId = await workflowStore.saveWorkflow();
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
  // Only autosave if we have an existing workflow
  if (workflowStore.workflowId === null) {
    return;
  }

  autosaveStatus.value = 'saving';
  try {
    await workflowStore.saveWorkflow();
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

const autoloadMostRecentWorkflow = async () => {
  try {
    const workflows = await workflowStore.listWorkflows();

    if (workflows.length === 0) {
      console.log('[WorkflowBuilder] No workflows to autoload');
      return;
    }

    // Sort by updated_at or created_at to find most recent
    const sortedWorkflows = workflows.sort((a, b) => {
      const dateA = new Date(a.updated_at || a.created_at).getTime();
      const dateB = new Date(b.updated_at || b.created_at).getTime();
      return dateB - dateA;
    });

    const mostRecent = sortedWorkflows[0];
    console.log('[WorkflowBuilder] Autoloading most recent workflow:', mostRecent.id, mostRecent.name);

    await workflowStore.loadWorkflow(mostRecent.id);

    // Update nextNodeId based on loaded nodes
    if (workflowStore.nodes.length > 0) {
      const maxId = Math.max(...workflowStore.nodes.map(n => n.id));
      nextNodeId.value = maxId + 1;
    }

    toast.add({
      severity: "info",
      summary: "Workflow Loaded",
      detail: `Loaded "${mostRecent.name}"`,
      life: 3000,
    });
  } catch (err: unknown) {
    console.error('[WorkflowBuilder] Autoload failed:', err);
    // Don't show error toast, just log it - user can manually load if needed
  }
};

const generateReport = async () => {
  try {
    await exportReport(nodeOutputs.value);
    toast.add({
      severity: "success",
      summary: "Report Generated",
      detail: "Provenance report downloaded",
      life: 2000,
    });
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Report Failed",
      detail: getErrorMessage(err, "Failed to generate report"),
      life: 3000,
    });
  }
};

const exportToPython = async () => {
  try {
    // Get Python code from backend API
    const pythonCode = await workflowStore.exportToPython();

    // Create download
    const blob = new Blob([pythonCode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${workflowStore.workflowName.replace(/\s+/g, '_').toLowerCase()}.py`;
    a.click();
    URL.revokeObjectURL(url);

    toast.add({
      severity: "success",
      summary: "Exported",
      detail: "Python script downloaded",
      life: 2000,
    });
  } catch (err: unknown) {
    // Fallback to local generation if API fails
    const pythonCode = generateLocalPythonCode();
    const blob = new Blob([pythonCode], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'workflow.py';
    a.click();
    URL.revokeObjectURL(url);

    toast.add({
      severity: "info",
      summary: "Exported (Local)",
      detail: "Python script generated locally",
      life: 2000,
    });
  }
};

// Fallback local Python code generator
const generateLocalPythonCode = (): string => {
  const lines = [
    '"""',
    'Auto-generated workflow script',
    'Generated by SpectraPy Workflow Builder',
    '"""',
    '',
    'import spectrochempy as scp',
    'import numpy as np',
    '',
  ];

  const sortedNodes = topologicalSort();

  for (const node of sortedNodes) {
    lines.push(`# ${node.type}`);
    lines.push(getNodePythonCode(node));
    lines.push('');
  }

  return lines.join('\n');
};

const formatPythonValue = (value: unknown): string => {
  // Format a value for Python code, adding quotes for strings
  if (typeof value === 'string') {
    return `"${value}"`;
  }
  return String(value);
};

const getStringParam = (params: ParamsMap, key: string, fallback: string): string => {
  const value = params[key];
  return typeof value === "string" ? value : fallback;
};

const getNumberParam = (params: ParamsMap, key: string, fallback: number): number => {
  const value = params[key];
  return typeof value === "number" ? value : fallback;
};

const getRangeParam = (params: ParamsMap, key: string, fallback: [number, number]): [number, number] => {
  const value = params[key];
  if (Array.isArray(value) && value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
    return [value[0], value[1]];
  }
  return fallback;
};

const getNodePythonCode = (node: WorkflowNode): string => {
  const codeMap: Record<string, (params: ParamsMap) => string> = {
    'DATA': (p) => `dataset = scp.read("${getStringParam(p, "source", "data.csv")}")`,
    'NORMALIZE': (p) => `dataset = dataset.normalize(method="${getStringParam(p, "method", "mean")}")`,
    'SCALE': (p) => {
      const [rangeStart, rangeEnd] = getRangeParam(p, "range", [0, 1]);
      return `dataset = dataset.scale(range=[${rangeStart}, ${rangeEnd}])`;
    },
    'BASELINE': (p) => `dataset = dataset.baseline_als(lam=${getNumberParam(p, "lam", 100000)}, p=${getNumberParam(p, "p", 0.001)})`,
    'SMOOTH': (p) => `dataset = dataset.savgol(window=${getNumberParam(p, "window", 15)}, poly=${getNumberParam(p, "poly", 2)})`,
    'PCA': (p) => `pca_result = scp.PCA(n_components=${formatPythonValue(p.n_components ?? 2)}).fit(dataset)`,
    'PLS': (p) => `pls_result = scp.PLS(n_components=${formatPythonValue(p.n_components ?? 3)}).fit(dataset, y)`,
    'MCR': (p) => `mcr_result = scp.MCR_ALS(n_components=${formatPythonValue(p.n_components ?? 3)}).fit(dataset)`,
    'STATS': () => `stats = dataset.describe()`,
    'PLOT': (p) => `dataset.plot(x_axis=${getNumberParam(p, "xAxis", 0)}, y_axis=${getNumberParam(p, "yAxis", 1)})`,
    'EXPORT': (p) => `dataset.write("${getStringParam(p, "filename", "output.csv")}")`,
  };
  const legacyType = workflowStore.getLegacyNodeType(node.type);
  return codeMap[legacyType]?.(node.params) || `# Unknown node type: ${node.type}`;
};

const topologicalSort = (): WorkflowNode[] => {
  const sorted: WorkflowNode[] = [];
  const visited = new Set<number>();

  const visit = (nodeId: number) => {
    if (visited.has(nodeId)) return;
    visited.add(nodeId);

    // Find edges leading to this node
    const incomingEdges = edges.value.filter(e => e.to === nodeId);
    for (const edge of incomingEdges) {
      visit(edge.from);
    }

    const node = nodes.value.find(n => n.id === nodeId);
    if (node) sorted.push(node);
  };

  // Visit all nodes
  for (const node of nodes.value) {
    visit(node.id);
  }

  return sorted;
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

// Execute workflow via backend API
const executeWorkflow = async () => {
  isExecuting.value = true;

  try {
    // Build initial data from DATA nodes using experiment store
    const initialData = await buildInitialData();

    // Execute via backend DAG executor
    const response = await workflowStore.executeWorkflow(initialData);

    // Convert backend results to frontend node outputs format
    const outputs = new Map<number, NodeOutput>();
    for (const [nodeId, result] of Object.entries(response.results)) {
      const resolvedNodeId = workflowStore.resolveFrontendNodeId(nodeId);
      if (resolvedNodeId === null) {
        console.warn("[Workflow] Could not resolve backend node ID:", nodeId);
        continue;
      }
      const output = buildOutputForNode(resolvedNodeId, result);
      // Debug: log what we're receiving from backend
      console.log(`[Workflow] Node ${nodeId} result:`, {
        hasData: !!output.data,
        dataType: Array.isArray(output.data) ? 'array' : typeof output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
        keys: Object.keys(result || {}),
      });

      outputs.set(resolvedNodeId, output);
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
  const dataNodes = nodes.value.filter(n => workflowStore.getLegacyNodeType(n.type) === 'DATA');

  for (const node of dataNodes) {
    const experimentId = coerceNumber(node.params.experiment_id);
    if (experimentId !== null) {
      // Load experiment data
      try {
        await experimentStore.selectExperiment(experimentId);
        initialData[String(node.id)] = {
          experiment_id: experimentId,
          source: node.params.source || 'experiment',
        };
      } catch {
        // Continue without this data source
        console.warn(`Failed to load experiment ${experimentId} for node ${node.id}`);
      }
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
  const normalizedType = workflowStore.normalizeNodeType(nodeType);
  const newNode: WorkflowNode = {
    id: nextNodeId.value++,
    type: normalizedType,
    x: 100 + (workflowStore.nodes.length * 40) % 400,
    y: 100 + Math.floor(workflowStore.nodes.length / 4) * 120,
    params: getDefaultParams(normalizedType),
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
    'DATA': {
      source: 'file',  // Default to file so users can enter path directly
      file_path: '',
      experiment_id: defaultExperimentId,
      format: 'csv',
    },
    'NIST_LIBRARY': {
      library_id: null,
      compound_name: '',
    },
    'SYNTHETIC_CURVE': {
      curve_type: 'sigmoid',
      n_points: 100,
      max_concentration: 1.0,
      center: 0.5,
      width: 0.1,
    },
    // Synthesis nodes
    'SPECIES': {
      species_name: 'Species',
      molar_absorptivity: 1.0,
    },
    'BLEND': {
      n_timepoints: 100,
      model_type: 'linear',
      pathlength: 0.01,
      noise_level: 0.01,
    },
    'MERGE_SPECTRA': {
      align_wavenumbers: true,
    },
    // Preprocessing nodes
    'NORMALIZE': { method: 'snv' },
    'SCALE': { range: [0, 1] },
    'BASELINE': { method: 'als', lam: 100000, p: 0.001 },
    'SMOOTH': { method: 'savgol', window: 15, poly: 2 },
    'COSMIC_RAY': { window: 5, zscore: 3.0 },
    'CLIP_RANGE': { min_wn: 400, max_wn: 4000 },
    // Analysis nodes - use backend parameter names directly (n_components)
    'PCA': { n_components: "5", standardized: false, scaled: false },
    'PLS': { n_components: 3, scale: true },
    'MCR': { n_components: 3, max_iter: 100 },
    'EFA': { n_components: 10, direction: 'both' },
    'PCR': { n_components: 3, scale: true },
    'SVR': { kernel: 'rbf', C: 1.0, epsilon: 0.1, gamma: 'scale', degree: 3, coef0: 0.0, scale: true },
    'KMEANS': { n_clusters: 3, n_init: 10, max_iter: 300, random_state: 42 },
    'DBSCAN': { eps: 0.5, min_samples: 5, metric: 'euclidean' },
    'HCA': { n_clusters: 3, linkage: 'ward', metric: 'euclidean' },
    'SIMPLISMA': { n_components: 3, noise: 3 },
    'STATS': { metrics: ['mean', 'std', 'min', 'max'], max_samples: 50 },
    // Classification nodes
    'PLS_DA': { n_components: 3, scale: true },
    'KNN': { n_neighbors: 5, metric: 'euclidean' },
    'SIMCA': { n_components: 3, alpha: 0.05 },
    // Output nodes
    'PLOT': { type: 'spectra', xAxis: 'wavenumber', yAxis: 'absorbance' },
    'CONTOUR_PLOT': { colorscale: 'Viridis', plot_type: 'heatmap', reverse_x: true, transpose: false },
    'EXPORT': { filename: 'output.csv', format: 'csv' },
    // Legacy
    'PEAK': { method: 'find_peaks', prominence: 0.01 },
    'SLICE': { start: 4000, end: 400, unit: 'cm-1' },
  };
  const legacyType = workflowStore.getLegacyNodeType(nodeType);
  return defaults[legacyType] || defaults[nodeType] || {};
};

const onNodesUpdate = (updatedNodes: WorkflowNode[]) => {
  workflowStore.setNodes(updatedNodes);
};

const onEdgesUpdate = (updatedEdges: WorkflowEdge[]) => {
  workflowStore.setEdges(updatedEdges);
};

const onNodeSelect = (node: WorkflowNode | null) => {
  selectedNode.value = node;
  // Open inspector when a node is selected
  if (node) {
    inspectorOpen.value = true;
  }
};

const onCloseInspector = () => {
  inspectorOpen.value = false;
};

const onNodeConnect = (connection: { from: number; to: number; fromPort?: string; toPort?: string }) => {
  workflowStore.addEdge(connection);

  // Auto-execute if enabled
  if (autoExecute.value && !isExecuting.value) {
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

const onUpdateParams = (nodeId: number, params: ParamsMap) => {
  workflowStore.updateNode(nodeId, { params });

  // Auto-execute if enabled (with longer debounce for parameter changes)
  if (autoExecute.value && !isExecuting.value) {
    setTimeout(() => executeWorkflow(), 1000); // Longer debounce for params
  }
};

const onExecuteNode = async (nodeId: number) => {
  const node = nodes.value.find(n => n.id === nodeId);
  if (!node) return;

  try {
    // Always build initial data - any node may depend on DATA nodes
    const initialData = await buildInitialData();

    // Execute single node via backend
    const response = await workflowStore.executeNode(String(nodeId), initialData);

    // Update outputs - create new Map for proper Vue reactivity
    const newOutputs = new Map(nodeOutputs.value);
    for (const [nId, result] of Object.entries(response.results)) {
      const resolvedNodeId = workflowStore.resolveFrontendNodeId(nId);
      if (resolvedNodeId === null) {
        console.warn("[Workflow] Could not resolve backend node ID:", nId);
        continue;
      }
      const output = buildOutputForNode(resolvedNodeId, result);
      // Debug: log what we're receiving from backend
      console.log(`[Workflow] Node ${nId} result:`, {
        hasData: !!output.data,
        dataType: Array.isArray(output.data) ? 'array' : typeof output.data,
        dataLength: Array.isArray(output.data) ? output.data.length : 'N/A',
        firstRowType: Array.isArray(output.data) && output.data[0] ? (Array.isArray(output.data[0]) ? 'array' : typeof output.data[0]) : 'N/A',
        keys: Object.keys(result || {}),
      });
      newOutputs.set(resolvedNodeId, output);
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

const onDeleteNode = (nodeId: number) => {
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
  height: 100%;
  gap: 16px;
  padding: 16px;
  background: #0f172a;
  color: #f8fafc;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.section-subtitle {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 0.95rem;
}

.integrity-hash-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 12px;
  padding: 2px 8px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 4px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.75rem;
  color: #4ade80;
  cursor: help;
  vertical-align: middle;
}

.integrity-hash-badge i {
  font-size: 0.7rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.auto-execute-toggle {
  display: flex;
  align-items: center;
}

.auto-execute-toggle :deep(.p-togglebutton) {
  font-size: 0.85rem;
  padding: 0.5rem 0.75rem;
}

.auto-execute-toggle :deep(.p-togglebutton.p-highlight) {
  background: linear-gradient(135deg, #a855f7, #9333ea);
  border-color: #a855f7;
}

.auto-execute-toggle :deep(.p-togglebutton:not(.p-highlight)) {
  background: #334155;
  border-color: #475569;
  color: #94a3b8;
}

.auto-execute-toggle :deep(.p-togglebutton:not(.p-highlight):hover) {
  background: #475569;
  border-color: #64748b;
}

.autosave-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: rgba(34, 197, 94, 0.15);
  border: 1px solid rgba(34, 197, 94, 0.3);
  border-radius: 6px;
  color: #4ade80;
  font-size: 0.85rem;
  font-weight: 500;
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
  min-height: 0;
  transition: grid-template-columns 0.3s ease;
}

/* Three-column layout when inspector is open */
.workflow-workspace.inspector-open {
  grid-template-columns: 200px 1fr 320px;
}

.canvas-container {
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  overflow: hidden;
  position: relative;
  min-height: 400px;
}

@media (max-width: 1200px) {
  .workflow-workspace.inspector-open {
    grid-template-columns: 180px 1fr 280px;
  }
}

@media (max-width: 900px) {
  .workflow-workspace {
    grid-template-columns: 1fr;
  }
  .workflow-workspace.inspector-open {
    grid-template-columns: 1fr;
  }
}
</style>
