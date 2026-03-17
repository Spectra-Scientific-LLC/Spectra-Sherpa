<template>
  <section class="workflow-builder-content">
    <div class="section-header">
      <div class="section-title-row">
        <h1>Workflow Builder</h1>
        <span
          v-if="workflowStore.workflowHash"
          class="integrity-hash-badge"
          :title="`Integrity Hash: ${workflowStore.workflowHash}`"
        >
          <i class="pi pi-lock"></i>
          {{ workflowStore.workflowHash.slice(0, 12) }}
        </span>
      </div>

      <div class="header-actions">
        <div class="toolbar-action-group">
          <Button
            :label="isWorkflowStale ? 'Run (Modified)' : 'Run'"
            icon="pi pi-play"
            class="toolbar-btn toolbar-action-btn"
            :loading="isExecuting"
            :disabled="nodes.length === 0"
            @click="executeWorkflow"
            :title="isWorkflowStale ? 'Workflow has been modified since last execution' : 'Execute workflow'"
          />
          <Button
            label="New"
            icon="pi pi-plus"
            class="toolbar-btn toolbar-action-btn"
            @click="createNewWorkflow"
          />
          <Button
            :label="saveButtonLabel"
            icon="pi pi-save"
            class="toolbar-btn toolbar-action-btn"
            :disabled="!hasChanges && autosaveStatus !== 'saving'"
            @click="saveWorkflow"
            title="Save workflow definition"
          />
          <SplitButton
            label="Export"
            icon="pi pi-download"
            class="toolbar-btn toolbar-action-btn"
            @click="exportToPython"
            :model="exportMenuItems"
          />
        </div>

        <span v-if="autosaveStatus === 'saved'" class="autosave-indicator">
          <i class="pi pi-check"></i> Saved
        </span>

        <label class="toolbar-state-control" :title="autoExecute ? 'Auto-execute on connect/param change' : 'Manual execution mode'">
          <Checkbox
            v-model="autoExecute"
            binary
            input-id="workflow-auto-update"
            @change="onAutoExecuteChange"
          />
          <span>Auto Update</span>
        </label>
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
/* eslint-disable @typescript-eslint/no-explicit-any -- builder canvas mixes generic node-library metadata with loose drag/drop payloads. */
import { ref, computed, provide, watch, onMounted, onUnmounted } from "vue";
import Button from "primevue/button";
import Checkbox from "primevue/checkbox";
import SplitButton from "primevue/splitbutton";
import { useToast } from "primevue/usetoast";
import { useWorkflowStore, type WorkflowNode, type WorkflowEdge } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import WorkflowToolbar from "./WorkflowToolbar.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import WorkflowInspector from "./WorkflowInspector.vue";
import { buildNodeOutput, type NodeOutput } from "@/utils/nodeOutput";
import { downloadText } from "@/utils/download";
import { getErrorMessage } from "@/utils/errors";

type ParamsMap = Record<string, unknown>;

const toast = useToast();
const workflowStore = useWorkflowStore();
const experimentStore = useExperimentStore();
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
const nodeOutputs = ref<Map<string, NodeOutput>>(new Map());
const inspectorOpen = ref(false);
const autoExecute = ref(false); // Auto-execute workflow when nodes connect or parameters change

// Autosave state
const autosaveStatus = ref<'idle' | 'saving' | 'saved'>('idle');
const autosaveTimer = ref<number | null>(null);
const AUTOSAVE_DELAY = 30000; // 30 seconds

const sanitizeNodeIdSeed = (nodeType: string): string =>
  nodeType.replace(/[^a-zA-Z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "node";

const createNodeId = (nodeType: string): string => {
  const seed = sanitizeNodeIdSeed(nodeType);
  let counter = workflowStore.nodes.filter((node) => node.id.startsWith(`${seed}_`)).length + 1;
  let candidate = `${seed}_${counter}`;
  while (workflowStore.nodes.some((node) => node.id === candidate)) {
    counter += 1;
    candidate = `${seed}_${counter}`;
  }
  return candidate;
};

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
      const response = await workflowStore.executeNode(nodeId, initialData);

      // Update outputs
      const newOutputs = new Map(nodeOutputs.value);
      let executedNodeOutput: NodeOutput | null = null;

      for (const [nId, result] of Object.entries(response.results)) {
        const output = buildOutputForNode(nId, result);
        const diagnostics = response.diagnostics?.[nId];
        if (diagnostics && typeof diagnostics === "object") {
          output.metadata = {
            ...output.metadata,
            diagnostics,
          };
        }
        newOutputs.set(nId, output);

        // Track the specific node's output for the broadcast response
        if (nId === String(nodeId)) {
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
const createNewWorkflow = () => {
  if (hasChanges.value) {
    if (!window.confirm("You have unsaved changes. Discard and create a new workflow?")) {
      return;
    }
  }
  workflowStore.clearWorkflow();
  selectedNode.value = null;
  nodeOutputs.value.clear();
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
      summary: "Workflow Loaded",
      detail: `Loaded "${mostRecent.name}"`,
      life: 3000,
    });
  } catch (err: unknown) {
    console.error('[WorkflowBuilder] Autoload failed:', err);
    // Don't show error toast, just log it - user can manually load if needed
  }
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
  // Open inspector when a node is selected
  if (node) {
    inspectorOpen.value = true;
  }
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

const onUpdateParams = (nodeId: string, params: ParamsMap) => {
  workflowStore.updateNode(nodeId, { params });

  // Auto-execute if enabled (with longer debounce for parameter changes)
  if (autoExecute.value && !isExecuting.value) {
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
  gap: 16px;
  padding: 16px;
  background: #0f172a;
  color: #f8fafc;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.section-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.integrity-hash-badge {
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
  vertical-align: middle;
}

.integrity-hash-badge i {
  font-size: 0.7rem;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.toolbar-action-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

/* Uniform toolbar button styling */
.header-actions :deep(.toolbar-btn) {
  height: 32px;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0 10px;
  border-radius: 6px;
  background: #334155;
  border: 1px solid #475569;
  color: #e2e8f0;
  white-space: nowrap;
}

.header-actions :deep(.toolbar-action-btn) {
  min-width: 92px;
  justify-content: center;
}

.header-actions :deep(.toolbar-btn:hover:not(:disabled)) {
  background: #475569;
  border-color: #64748b;
  color: #f8fafc;
}

.header-actions :deep(.toolbar-btn:disabled) {
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
  align-items: stretch;
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
  display: flex;
  min-width: 0;
}

.canvas-container > * {
  flex: 1 1 auto;
  min-height: 100%;
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
