<template>
  <div
    ref="canvasRef"
    class="workflow-canvas"
    @mousemove="handleMouseMove"
    @mouseup="handleMouseUp"
    @mouseleave="handleMouseUp"
  >
    <div class="canvas-surface">
      <!-- SVG layer for edges -->
      <svg class="edges-layer">
        <defs>
          <!-- Valid edge arrowhead (green) -->
          <marker
            id="arrowhead-valid"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 10 3, 0 6" fill="#4ade80" />
          </marker>
          <!-- Invalid edge arrowhead (red) -->
          <marker
            id="arrowhead-invalid"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 10 3, 0 6" fill="#ef4444" />
          </marker>
        </defs>

        <!-- Edge lines with validation coloring -->
        <g v-for="edge in edges" :key="getEdgeKey(edge)" class="edge-group">
          <!-- Invisible thick line for easier clicking -->
          <line
            :x1="getNodeCenter(edge.from).x"
            :y1="getNodeCenter(edge.from).y"
            :x2="getNodeCenter(edge.to).x"
            :y2="getNodeCenter(edge.to).y"
            stroke="transparent"
            stroke-width="20"
            class="edge-hit-area"
            @click="handleEdgeClick(edge)"
            style="cursor: pointer;"
          >
            <title>Click to delete this connection</title>
          </line>

          <!-- Visible edge line -->
          <line
            :x1="getNodeCenter(edge.from).x"
            :y1="getNodeCenter(edge.from).y"
            :x2="getNodeCenter(edge.to).x"
            :y2="getNodeCenter(edge.to).y"
            :stroke="edge.isValid === false ? '#ef4444' : '#4ade80'"
            :stroke-width="edge.isValid === false ? 3 : 2"
            :stroke-dasharray="edge.isValid === false ? '5,5' : 'none'"
            :marker-end="edge.isValid === false ? 'url(#arrowhead-invalid)' : 'url(#arrowhead-valid)'"
            class="edge-line"
            style="pointer-events: none;"
          >
            <!-- Tooltip for invalid edges -->
            <title v-if="edge.isValid === false && edge.validationError">
              {{ edge.validationError }}
            </title>
          </line>

          <!-- Edge type label -->
          <text
            v-if="edge.dataType"
            :x="(getNodeCenter(edge.from).x + getNodeCenter(edge.to).x) / 2"
            :y="(getNodeCenter(edge.from).y + getNodeCenter(edge.to).y) / 2 - 5"
            class="edge-label"
            :class="{ 'edge-label-invalid': edge.isValid === false }"
            text-anchor="middle"
          >
            {{ edge.dataType }}
          </text>

          <!-- Warning icon for invalid edges -->
          <g
            v-if="edge.isValid === false"
            :transform="`translate(${(getNodeCenter(edge.from).x + getNodeCenter(edge.to).x) / 2}, ${(getNodeCenter(edge.from).y + getNodeCenter(edge.to).y) / 2 + 12})`"
            class="edge-warning-icon"
          >
            <circle cx="0" cy="0" r="10" fill="#ef4444" />
            <text x="0" y="4" text-anchor="middle" fill="white" font-size="12" font-weight="bold">!</text>
            <title>{{ edge.validationError }}</title>
          </g>
        </g>

        <!-- Connecting line preview -->
        <line
          v-if="isConnecting && mousePos"
          :x1="getNodeCenter(connecting).x"
          :y1="getNodeCenter(connecting).y"
          :x2="mousePos.x"
          :y2="mousePos.y"
          stroke="#4ade80"
          stroke-width="2"
          stroke-dasharray="5,5"
          opacity="0.6"
        />
      </svg>

    <!-- Context Menu -->
    <div
      v-if="contextMenu.show"
      class="context-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @click.stop
    >
      <div class="context-menu-item" @click="runNode">
        <i class="pi pi-play"></i>
        <span>Run Node</span>
      </div>
      <div
        class="context-menu-item"
        :class="{ disabled: !hasOutput(contextMenu.nodeId) }"
        @click="viewOutput"
      >
        <i class="pi pi-eye"></i>
        <span>View Output</span>
      </div>
      <div class="context-menu-divider"></div>
      <div class="context-menu-item" @click="copyNode">
        <i class="pi pi-copy"></i>
        <span>Copy Node</span>
      </div>
      <div class="context-menu-item danger" @click="deleteNodeFromMenu">
        <i class="pi pi-trash"></i>
        <span>Delete Node</span>
      </div>
    </div>

      <!-- Nodes layer -->
      <div
        v-for="node in nodes"
        :key="node.id"
        class="workflow-node"
        :class="{
          'is-selected': selectedNodeId === node.id,
          'is-dragging': dragging === node.id,
          'is-connecting-source': connecting === node.id,
          'is-compatible-target': isConnecting && connecting !== node.id && isNodeCompatibleTarget(node.id),
          'is-incompatible-target': isConnecting && connecting !== node.id && !isNodeCompatibleTarget(node.id),
          [`node-type-${getNodeCategory(node.type)}`]: true
        }"
        :style="{ left: `${node.x}px`, top: `${node.y}px` }"
        @mousedown.stop="handleNodeMouseDown($event, node.id)"
        @contextmenu.prevent="handleNodeContextMenu($event, node.id)"
      >
      <!-- Input ports (left side) -->
      <div class="input-ports">
        <div
          v-for="(port, idx) in getNodeInputPorts(node.type)"
          :key="`input-${port.name}`"
          class="port port-input"
          :class="{
            'port-compatible': isConnecting && isPortCompatible(node.id, port.name),
            'port-incompatible': isConnecting && !isPortCompatible(node.id, port.name)
          }"
          :style="{
            top: `${30 + idx * 20}px`,
            backgroundColor: getPortColor(getPortCategory(port.type_ref))
          }"
          :title="isConnecting ? getPortCompatibilityReason(node.id, port.name) || `${port.label} (${getTypeName(port.type_ref)})` : `${port.label} (${getTypeName(port.type_ref)})`"
        >
          <span
            v-if="isConnecting"
            class="port-compat-indicator"
            :class="isPortCompatible(node.id, port.name) ? 'ok' : 'bad'"
          >
            {{ isPortCompatible(node.id, port.name) ? "✓" : "✕" }}
          </span>
          <div class="port-tooltip">
            <div class="port-tooltip-label">{{ port.label }}</div>
            <div class="port-tooltip-type">{{ getTypeName(port.type_ref) }}</div>
            <div
              v-if="isConnecting && getPortCompatibilityReason(node.id, port.name)"
              class="port-tooltip-desc"
            >
              {{ getPortCompatibilityReason(node.id, port.name) }}
            </div>
            <div v-if="port.description" class="port-tooltip-desc">{{ port.description }}</div>
          </div>
        </div>
      </div>

      <!-- Output ports (right side) -->
      <div class="output-ports">
        <div
          v-for="(port, idx) in getNodeOutputPorts(node.type)"
          :key="`output-${port.name}`"
          class="port port-output"
          :style="{
            top: `${30 + idx * 20}px`,
            backgroundColor: getPortColor(getPortCategory(port.type_ref))
          }"
          :title="`${port.label} (${getTypeName(port.type_ref)})`"
        >
          <div class="port-tooltip">
            <div class="port-tooltip-label">{{ port.label }}</div>
            <div class="port-tooltip-type">{{ getTypeName(port.type_ref) }}</div>
            <div v-if="port.description" class="port-tooltip-desc">{{ port.description }}</div>
          </div>
        </div>
      </div>

      <!-- Node header -->
      <div class="node-header" :class="`header-${getNodeCategory(node.type)}`">
        <span class="node-icon">{{ getNodeIcon(node.type) }}</span>
        <span class="node-label">{{ getNodeLabel(node.type) }}</span>
        <button
          class="delete-btn"
          @click.stop="deleteNode(node.id)"
          title="Delete node"
        >
          <i class="pi pi-times"></i>
        </button>
      </div>

      <!-- Node body -->
      <div class="node-body">
        <!-- Error state -->
        <div v-if="node.executionState?.status === 'error'" class="node-status error">
          <i class="pi pi-times-circle"></i>
          <span>Error</span>
        </div>
        <!-- Running state -->
        <div v-else-if="node.executionState?.status === 'running'" class="node-status running">
          <i class="pi pi-spin pi-spinner"></i>
          <span>Running</span>
        </div>
        <!-- Completed state -->
        <div v-else-if="node.executionState?.status === 'completed' || nodeOutputs.has(node.id)" class="node-status success">
          <i class="pi pi-check-circle"></i>
          <span>Completed</span>
        </div>
        <!-- Stale state (modified since execution) -->
        <div v-else-if="node.executionState?.status === 'stale'" class="node-status stale">
          <i class="pi pi-exclamation-triangle"></i>
          <span>Stale</span>
        </div>
        <!-- Pending state (default) -->
        <div v-else class="node-status pending">
          <i class="pi pi-circle"></i>
          <span>Pending</span>
        </div>

        <!-- Data shape badge (if available) -->
        <div v-if="node.executionState?.output_shape" class="data-shape-badge">
          <i class="pi pi-database"></i>
          <span>{{ formatShape(node.executionState.output_shape) }}</span>
        </div>

      </div>

      <!-- Node footer with connect button -->
      <div class="node-footer">
        <button
          v-if="connecting === node.id"
          class="connect-btn connecting"
          @click.stop="cancelConnect"
        >
          <i class="pi pi-times"></i>
          Cancel
        </button>
        <!-- Multi-input node: show port selection buttons -->
        <template v-else-if="isConnecting && connecting !== node.id && getInputPorts(node.type).length > 0">
          <div class="port-selection">
            <span class="port-label">Connect to:</span>
            <div class="port-buttons">
              <button
                v-for="port in getAvailablePorts(node.id, node.type)"
                :key="port.name"
                class="port-btn port-btn-letter"
                :title="port.label"
                @click.stop="completeConnect(node.id, port.name)"
              >
                {{ port.label.charAt(0) }}
              </button>
            </div>
            <span v-if="getAvailablePorts(node.id, node.type).length === 0" class="ports-full">
              All ports connected
            </span>
          </div>
        </template>
        <!-- Single-input node: simple connect button -->
        <button
          v-else-if="isConnecting && connecting !== node.id"
          class="connect-btn target"
          @click.stop="completeConnect(node.id)"
        >
          <i class="pi pi-arrow-right"></i>
          Connect Here
        </button>
        <!-- Multi-output node: show output port selection -->
        <template v-else-if="hasMultipleOutputs(node.type)">
          <div class="port-selection">
            <span class="port-label">Connect from:</span>
            <div class="port-buttons">
              <button
                v-for="port in getNodeOutputPorts(node.type)"
                :key="port.name"
                class="port-btn port-btn-letter"
                :style="{ backgroundColor: getPortColor(getPortCategory(port.type_ref)) }"
                :title="port.label"
                @click.stop="startConnect(node.id, port.name)"
              >
                {{ port.label.charAt(0) }}
              </button>
            </div>
          </div>
        </template>
        <!-- Single-output node: simple connect button -->
        <button
          v-else
          class="connect-btn"
          @click.stop="startConnect(node.id)"
        >
          <i class="pi pi-share-alt"></i>
          Connect
        </button>
      </div>
      </div>

      <!-- Empty state -->
      <div v-if="nodes.length === 0" class="empty-state">
        <div class="empty-icon">🔧</div>
        <p>Add nodes from the toolbar to build your workflow</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useWorkflowStore } from "@/stores/workflow";
import type { WorkflowNode, WorkflowEdge } from "@/stores/workflow";
import type { NodeOutput } from "@/utils/nodeOutput";
import type { NodePortMetadata } from "@/types";

interface Props {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  nodeOutputs: Map<string, NodeOutput>;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: 'update:nodes', nodes: WorkflowNode[]): void;
  (e: 'update:edges', edges: WorkflowEdge[]): void;
  (e: 'node-select', node: WorkflowNode | null): void;
  (e: 'node-connect', connection: { from: string; to: string; fromPort?: string; toPort?: string }): void;
  (e: 'connection-error', error: string): void;
  (e: 'run-node', nodeId: string): void;
  (e: 'view-output', nodeId: string): void;
  (e: 'copy-node', nodeId: string): void;
}>();

// Port color scheme by category
const PORT_COLORS: Record<string, string> = {
  dataset: '#3b82f6',  // Blue - spectral data, NDDataset
  array: '#3b82f6',    // Blue - array types
  target: '#f59e0b',   // Orange/amber - y values, labels
  model: '#a855f7',    // Purple - trained models
  number: '#10b981',   // Green - scalar values
  visualization: '#ec4899', // Pink - plots
  config: '#64748b',   // Gray - configuration dicts
  default: '#64748b',  // Fallback gray
};

// Get workflow store for node metadata
const workflowStore = useWorkflowStore();

// Extract the human-readable type name from a type_ref URI (e.g. "SpectralDataset").
const getTypeName = (typeRef: string): string => {
  const match = typeRef.match(/^spectrasherpa:\/\/types\/([A-Za-z0-9_]+)\/\d+\.\d+$/);
  return match ? match[1] : typeRef;
};

// Derive visual category from a type_ref URI using the fetched type registry.
const getPortCategory = (typeRef: string): string => {
  const match = typeRef.match(/^spectrasherpa:\/\/types\/([A-Za-z0-9_]+)\/\d+\.\d+$/);
  if (!match) return 'dataset';
  const typeName = match[1];
  // Look up in the fetched type registry (has category per type)
  const registry = workflowStore.typeRegistry;
  if (registry?.types?.[typeName]?.category) {
    return registry.types[typeName].category;
  }
  return 'dataset'; // safe fallback
};

// Get port color based on type_ref category
const getPortColor = (category: string): string => {
  return PORT_COLORS[category] || PORT_COLORS.default;
};

// Get input ports for a node (from node library metadata)
const getNodeInputPorts = (nodeType: string): NodePortMetadata[] => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.input_ports && metadata.input_ports.length > 0) {
    return metadata.input_ports;
  }
  // Fallback to legacy single-input nodes
  return [];
};

// Get output ports for a node (from node library metadata)
const getNodeOutputPorts = (nodeType: string): NodePortMetadata[] => {
  const metadata = workflowStore.getNodeMetadata(nodeType);
  if (metadata?.output_ports && metadata.output_ports.length > 0) {
    return metadata.output_ports;
  }
  // Fallback for nodes that declare output_type but not output_ports
  return [{
    name: 'default',
    type_ref: 'spectrasherpa://types/Any/1.0',
    required: true,
    label: 'Output',
  }];
};

// Check if a node type has multiple input ports (uses backend metadata)
const getInputPorts = (nodeType: string): NodePortMetadata[] => {
  return getNodeInputPorts(nodeType);
};

// Get available (unconnected) ports for a multi-input node
const getAvailablePorts = (nodeId: string, nodeType: string): NodePortMetadata[] => {
  const allPorts = getInputPorts(nodeType);
  if (!allPorts || allPorts.length === 0) return [];

  // Find which ports are already connected
  const connectedPorts = new Set(
    props.edges
      .filter(e => e.to === nodeId && e.toPort)
      .map(e => e.toPort)
  );

  // Return only unconnected ports
  return allPorts.filter(port => !connectedPorts.has(port.name));
};

// Check if a node has multiple output ports
const hasMultipleOutputs = (nodeType: string): boolean => {
  const outputPorts = getNodeOutputPorts(nodeType);
  return outputPorts.length > 1;
};

const NODE_ICONS: Record<string, string> = {
  'data.source': '📊',
  'preprocess.normalize': '⚖️',
  'preprocess.scale': '📏',
  'baseline.penalized_ls': '📉',
  'preprocess.smooth': '〰️',
  'model.pca': '🔀',
  'model.pls': '📈',
  'model.mcr_als': '🧩',
  'model.efa': '🔍',
  'model.simplisma': '🎯',
  'stats.summary': '📊',
  'output.plot': '📈',
  'output.contour': '🗺️',
  'output.export': '💾',
};

const NODE_LABELS: Record<string, string> = {
  'data.source': 'Load Data',
  'preprocess.normalize': 'Normalize',
  'preprocess.scale': 'Scale',
  'baseline.penalized_ls': 'Baseline',
  'preprocess.smooth': 'Smooth',
  'model.pca': 'PCA',
  'model.pls': 'PLS',
  'model.mcr_als': 'MCR-ALS',
  'model.efa': 'EFA',
  'model.simplisma': 'SIMPLISMA',
  'stats.summary': 'Statistics',
  'output.plot': 'Plot',
  'output.contour': 'Contour Plot',
  'output.export': 'Export',
};

const getNodeIcon = (type: string): string => {
  return NODE_ICONS[type] || '📦';
};

const getNodeLabel = (type: string): string => {
  const metadata = workflowStore.getNodeMetadata(type);
  if (metadata?.label) {
    return metadata.label;
  }
  return NODE_LABELS[type] || type;
};

const getNodeCategory = (type: string): string => {
  const metadata = workflowStore.getNodeMetadata(type);
  if (metadata?.category) {
    const categoryMap: Record<string, string> = {
      data: 'data',
      synthesis: 'data',
      preprocessing: 'preprocess',
      selection: 'selection',
      modeling: 'model',
      analysis: 'analyze',
      classification: 'analyze',
      diagnostics: 'analyze',
      time_series: 'analyze',
      output: 'export',
      stats: 'analyze',
    };
    const mapped = categoryMap[metadata.category.toLowerCase()];
    if (mapped) return mapped;
  }

  if (type.includes(".")) {
    const prefix = type.split(".")[0];
    const prefixMap: Record<string, string> = {
      data: 'data',
      synthesis: 'data',
      preprocess: 'preprocess',
      normalize: 'preprocess',
      baseline: 'preprocess',
      smooth: 'preprocess',
      derivative: 'preprocess',
      selection: 'selection',
      model: 'model',
      analysis: 'analyze',
      classification: 'analyze',
      diagnostics: 'analyze',
      time_series: 'analyze',
      stats: 'analyze',
      output: 'export',
    };
    const mapped = prefixMap[prefix];
    if (mapped) return mapped;
  }

  return 'default';
};

// Format data shape for display
const formatShape = (shape: number[]): string => {
  if (!shape || shape.length === 0) return '';
  if (shape.length === 1) return `${shape[0]} pts`;
  if (shape.length === 2) return `${shape[0]} × ${shape[1]}`;
  return shape.join(' × ');
};

// Canvas state
const canvasRef = ref<HTMLElement | null>(null);
const selectedNodeId = ref<string | null>(null);
const dragging = ref<string | null>(null);
const dragOffset = ref({ x: 0, y: 0 });
const connecting = ref<string | null>(null);
const connectingFromPort = ref<string | null>(null); // Track selected output port
const mousePos = ref<{ x: number; y: number } | null>(null);

// Context menu state
const contextMenu = ref({
  show: false,
  x: 0,
  y: 0,
  nodeId: null as string | null,
});

// Connection compatibility tracking
const isConnecting = computed(() => connecting.value !== null);

const getEdgeValidation = (targetNodeId: string, targetPortName?: string) => {
  if (connecting.value === null) {
    return { isValid: false, error: "No source selected" };
  }
  if (connecting.value === targetNodeId) {
    return { isValid: false, error: "Cannot connect a node to itself" };
  }
  return workflowStore.validateEdge({
    from: connecting.value,
    to: targetNodeId,
    fromPort: connectingFromPort.value || undefined,
    toPort: targetPortName,
  });
};

// Check if a target node/port is compatible with current connection.
const isPortCompatible = (targetNodeId: string, targetPortName?: string): boolean => {
  const validation = getEdgeValidation(targetNodeId, targetPortName);
  return validation.isValid;
};

const getPortCompatibilityReason = (targetNodeId: string, targetPortName?: string): string => {
  const validation = getEdgeValidation(targetNodeId, targetPortName);
  return validation.error || "";
};

// Check if node is a valid connection target
const isNodeCompatibleTarget = (nodeId: string): boolean => {
  if (connecting.value === null || connecting.value === nodeId) return false;

  const targetNode = props.nodes.find(n => n.id === nodeId);
  if (!targetNode) return false;

  const targetMetadata = workflowStore.getNodeMetadata(targetNode.type);
  if (targetMetadata?.input_ports && targetMetadata.input_ports.length > 0) {
    return targetMetadata.input_ports.some((port) => isPortCompatible(nodeId, port.name));
  }

  return isPortCompatible(nodeId);
};

// Get node center position for edge drawing
const getNodeCenter = (nodeId: string | null) => {
  const node = props.nodes.find(n => n.id === nodeId);
  if (!node) return { x: 0, y: 0 };
  return {
    x: node.x + 80, // Half of node width
    y: node.y + 50, // Half of node height
  };
};

// Mouse event handlers
// Track if actual drag movement occurred to avoid opening inspector during drag
const dragStartPos = ref<{ x: number; y: number } | null>(null);
const hasDragged = ref(false);
const DRAG_THRESHOLD = 5; // Pixels before considering it a drag

const handleNodeMouseDown = (event: MouseEvent, nodeId: string) => {
  const node = props.nodes.find(n => n.id === nodeId);
  if (!node) return;

  // Skip if clicking on buttons
  if ((event.target as HTMLElement).tagName === 'BUTTON' ||
      (event.target as HTMLElement).closest('button')) {
    return;
  }

  dragging.value = nodeId;
  selectedNodeId.value = nodeId;
  hasDragged.value = false;
  dragStartPos.value = { x: event.clientX, y: event.clientY };

  dragOffset.value = {
    x: event.clientX - node.x,
    y: event.clientY - node.y,
  };
};

const handleMouseMove = (event: MouseEvent) => {
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  mousePos.value = {
    x: event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0),
    y: event.clientY - rect.top + (canvasRef.value?.scrollTop || 0),
  };

  if (dragging.value === null) return;

  // Check if we've moved enough to consider it a drag
  if (dragStartPos.value && !hasDragged.value) {
    const dx = Math.abs(event.clientX - dragStartPos.value.x);
    const dy = Math.abs(event.clientY - dragStartPos.value.y);
    if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
      hasDragged.value = true;
    }
  }

  const newX = event.clientX - dragOffset.value.x;
  const newY = event.clientY - dragOffset.value.y;

  const updatedNodes = props.nodes.map(n =>
    n.id === dragging.value
      ? { ...n, x: Math.max(0, newX), y: Math.max(0, newY) }
      : n
  );

  emit('update:nodes', updatedNodes);
};

const handleMouseUp = () => {
  // Only open inspector if we didn't drag (just a click)
  if (dragging.value !== null && !hasDragged.value) {
    const node = props.nodes.find(n => n.id === dragging.value);
    if (node) {
      emit('node-select', node);
    }
  }

  dragging.value = null;
  dragStartPos.value = null;
  hasDragged.value = false;
};

// Connection handlers
const startConnect = (nodeId: string, fromPort?: string) => {
  connecting.value = nodeId;
  connectingFromPort.value = fromPort || null;
};

const cancelConnect = () => {
  connecting.value = null;
  connectingFromPort.value = null;
};

const completeConnect = (toNodeId: string, toPort?: string) => {
  if (connecting.value !== null && connecting.value !== toNodeId) {
    const fromNodeId = connecting.value;
    const sourceNode = props.nodes.find((n) => n.id === fromNodeId);
    const targetNode = props.nodes.find((n) => n.id === toNodeId);
    if (!sourceNode || !targetNode) {
      emit('connection-error', 'Source or target node not found');
      connecting.value = null;
      connectingFromPort.value = null;
      return;
    }

    const validation = workflowStore.validateEdge({
      from: fromNodeId,
      to: toNodeId,
      fromPort: connectingFromPort.value || undefined,
      toPort,
    });

    if (!validation.isValid) {
      emit('connection-error', validation.error || '❌ Invalid connection');
      connecting.value = null;
      connectingFromPort.value = null;
      return;
    }

    // Connection is valid, emit the event
    emit('node-connect', {
      from: fromNodeId,
      to: toNodeId,
      fromPort: connectingFromPort.value || undefined,
      toPort
    });
  }
  connecting.value = null;
  connectingFromPort.value = null;
};

const deleteNode = (nodeId: string) => {
  const updatedNodes = props.nodes.filter(n => n.id !== nodeId);
  const updatedEdges = props.edges.filter(e => e.from !== nodeId && e.to !== nodeId);

  emit('update:nodes', updatedNodes);
  emit('update:edges', updatedEdges);

  if (selectedNodeId.value === nodeId) {
    selectedNodeId.value = null;
    emit('node-select', null);
  }
};

const getEdgeKey = (edge: WorkflowEdge): string => {
  const fromPort = edge.fromPort || "default";
  const toPort = edge.toPort || "default";
  return `${edge.from}:${fromPort}->${edge.to}:${toPort}`;
};

const handleEdgeClick = (edge: WorkflowEdge) => {
  const targetKey = getEdgeKey(edge);
  let removed = false;
  const updatedEdges = props.edges.filter((e) => {
    if (!removed && getEdgeKey(e) === targetKey) {
      removed = true;
      return false;
    }
    return true;
  });
  emit('update:edges', updatedEdges);
};

// Context menu handlers
const handleNodeContextMenu = (event: MouseEvent, nodeId: string) => {
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  contextMenu.value = {
    show: true,
    x: event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0),
    y: event.clientY - rect.top + (canvasRef.value?.scrollTop || 0),
    nodeId,
  };

  // Close context menu when clicking elsewhere
  const closeMenu = () => {
    contextMenu.value.show = false;
    document.removeEventListener('click', closeMenu);
  };
  setTimeout(() => document.addEventListener('click', closeMenu), 0);
};

const hasOutput = (nodeId: string | null): boolean => {
  if (nodeId === null) return false;
  return props.nodeOutputs.has(nodeId);
};

const runNode = () => {
  if (contextMenu.value.nodeId !== null) {
    emit('run-node', contextMenu.value.nodeId);
  }
  contextMenu.value.show = false;
};

const viewOutput = () => {
  if (contextMenu.value.nodeId !== null && hasOutput(contextMenu.value.nodeId)) {
    emit('view-output', contextMenu.value.nodeId);
  }
  contextMenu.value.show = false;
};

const copyNode = () => {
  if (contextMenu.value.nodeId !== null) {
    emit('copy-node', contextMenu.value.nodeId);
  }
  contextMenu.value.show = false;
};

const deleteNodeFromMenu = () => {
  if (contextMenu.value.nodeId !== null) {
    deleteNode(contextMenu.value.nodeId);
  }
  contextMenu.value.show = false;
};

// Watch for external selection changes
watch(() => props.nodes, () => {
  if (selectedNodeId.value !== null) {
    const stillExists = props.nodes.some(n => n.id === selectedNodeId.value);
    if (!stillExists) {
      selectedNodeId.value = null;
      emit('node-select', null);
    }
  }
});

const centerNode = (nodeId: string) => {
  const node = props.nodes.find((entry) => entry.id === nodeId);
  const canvas = canvasRef.value;
  if (!node || !canvas) return;

  const nodeCenterX = node.x + 80;
  const nodeCenterY = node.y + 50;
  const targetLeft = Math.max(0, nodeCenterX - canvas.clientWidth / 2);
  const targetTop = Math.max(0, nodeCenterY - canvas.clientHeight / 2);

  canvas.scrollTo({
    left: targetLeft,
    top: targetTop,
    behavior: "smooth",
  });
};

defineExpose({ centerNode });
</script>

<style scoped>
.workflow-canvas {
  width: 100%;
  height: 100%;
  min-height: 100%;
  position: relative;
  overflow: auto;
  min-width: 0;
  background:
    linear-gradient(rgba(51, 65, 85, 0.5) 1px, transparent 1px),
    linear-gradient(90deg, rgba(51, 65, 85, 0.5) 1px, transparent 1px);
  background-size: 20px 20px;
  background-color: #1e293b;
}

.canvas-surface {
  position: relative;
  min-width: var(--workflow-workspace-min-height, 1500px);
  min-height: var(--workflow-workspace-min-height, 1500px);
  width: max(100%, var(--workflow-workspace-min-height, 1500px));
  height: max(100%, var(--workflow-workspace-min-height, 1500px));
}

.edges-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}

/* Edge visual elements */
.edge-group {
  cursor: pointer;
}

.edge-group:hover .edge-line {
  stroke-width: 4;
  filter: brightness(1.3);
}

.edge-hit-area {
  pointer-events: all;
}

.edge-line {
  transition: stroke 0.2s, stroke-width 0.2s, filter 0.2s;
}

.edge-label {
  font-size: 11px;
  font-weight: 600;
  fill: #4ade80;
  font-family: 'SF Mono', Monaco, monospace;
  pointer-events: none;
  text-shadow: 0 0 4px rgba(0, 0, 0, 0.8);
}

.edge-label-invalid {
  fill: #ef4444;
}

.edge-warning-icon {
  cursor: help;
  transition: transform 0.2s;
}

.edge-warning-icon:hover {
  transform: scale(1.2);
}

.workflow-node {
  position: absolute;
  width: 160px;
  background: #0f172a;
  border-radius: 8px;
  border: 2px solid #334155;
  cursor: grab;
  transition: border-color 0.2s, box-shadow 0.2s;
  z-index: 2;
  user-select: none;
}

.workflow-node:hover {
  border-color: #64748b;
}

.workflow-node.is-selected {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.3);
}

.workflow-node.is-dragging {
  cursor: grabbing;
  opacity: 0.9;
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px 6px 0 0;
  font-weight: 600;
  font-size: 0.85rem;
  color: white;
}

.header-data { background: linear-gradient(135deg, #3b82f6, #2563eb); }
.header-preprocess { background: linear-gradient(135deg, #22c55e, #16a34a); }
.header-selection { background: linear-gradient(135deg, #14b8a6, #0d9488); }
.header-model { background: linear-gradient(135deg, #a855f7, #9333ea); }
.header-analyze { background: linear-gradient(135deg, #eab308, #ca8a04); }
.header-visualize { background: linear-gradient(135deg, #f97316, #ea580c); }
.header-export { background: linear-gradient(135deg, #64748b, #475569); }

.node-icon {
  font-size: 1rem;
}

.node-label {
  flex: 1;
  font-size: 0.8rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.delete-btn {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  padding: 2px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s, color 0.2s;
}

.delete-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  color: white;
}

.node-body {
  position: relative;
  padding: 10px;
  border-bottom: 1px solid #334155;
}

.node-status {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.node-status.success {
  color: #4ade80;
}

.node-status.pending {
  color: #64748b;
}

.node-status.error {
  color: #ef4444;
}

.node-status.running {
  color: #3b82f6;
}

.node-status.stale {
  color: #f59e0b;
}

/* Data shape badge */
.data-shape-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  padding: 3px 6px;
  background: rgba(59, 130, 246, 0.1);
  border: 1px solid rgba(59, 130, 246, 0.3);
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 500;
  color: #3b82f6;
  font-family: 'SF Mono', Monaco, monospace;
}

.data-shape-badge i {
  font-size: 0.65rem;
}

.node-footer {
  padding: 8px;
}

.connect-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 10px;
  background: #334155;
  border: none;
  border-radius: 4px;
  color: #e2e8f0;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.connect-btn:hover {
  background: #475569;
}

.connect-btn.connecting {
  background: #ef4444;
}

.connect-btn.connecting:hover {
  background: #dc2626;
}

.connect-btn.target {
  background: #22c55e;
}

.connect-btn.target:hover {
  background: #16a34a;
}

/* Port selection for multi-input nodes */
.port-selection {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.port-label {
  font-size: 0.7rem;
  color: #94a3b8;
  text-align: center;
}

.port-buttons {
  display: flex;
  gap: 4px;
  justify-content: center;
}

.port-btn {
  flex: 1;
  padding: 6px 8px;
  background: #22c55e;
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 0.7rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.port-btn-letter {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  padding: 0;
  font-size: 0.8rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
}

.port-btn:hover {
  background: #16a34a;
}

.ports-full {
  font-size: 0.7rem;
  color: #f59e0b;
  text-align: center;
  padding: 4px;
}

.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #64748b;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 16px;
}

.empty-state p {
  margin: 0;
  font-size: 0.95rem;
}

/* Context Menu */
.context-menu {
  position: absolute;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  z-index: 1000;
  min-width: 160px;
  padding: 4px;
}

.context-menu-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: #e2e8f0;
  font-size: 0.85rem;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  user-select: none;
}

.context-menu-item:hover {
  background: #334155;
}

.context-menu-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.context-menu-item.disabled:hover {
  background: transparent;
}

.context-menu-item.danger {
  color: #ef4444;
}

.context-menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.1);
}

.context-menu-item i {
  font-size: 0.9rem;
  width: 16px;
  text-align: center;
}

.context-menu-divider {
  height: 1px;
  background: #334155;
  margin: 4px 0;
}

/* Port indicators */
.input-ports,
.output-ports {
  position: absolute;
  top: 0;
  height: 100%;
  pointer-events: none;
}

.input-ports {
  left: -6px;
}

.output-ports {
  right: -6px;
}

.port {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid #0f172a;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
  transition: transform 0.2s, box-shadow 0.2s;
  cursor: crosshair;
  pointer-events: all;
  z-index: 10;
}

.port:hover {
  transform: scale(1.3);
  box-shadow: 0 0 8px currentColor;
}

.port-input {
  transform: translateX(-50%);
}

.port-output {
  transform: translateX(50%);
}

.port:hover .port-tooltip {
  display: block;
}

.port-compat-indicator {
  position: absolute;
  top: -9px;
  right: -12px;
  width: 16px;
  height: 16px;
  border-radius: 999px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid rgba(15, 23, 42, 0.8);
  background: #0f172a;
  pointer-events: none;
}

.port-compat-indicator.ok {
  color: #4ade80;
}

.port-compat-indicator.bad {
  color: #ef4444;
}

.port-tooltip {
  display: none;
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -100%);
  margin-top: -10px;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 8px 10px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  white-space: nowrap;
  z-index: 1000;
  pointer-events: none;
}

.port-tooltip-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 2px;
}

.port-tooltip-type {
  font-size: 0.7rem;
  font-weight: 500;
  color: #94a3b8;
  font-family: 'SF Mono', Monaco, monospace;
  letter-spacing: 0.2px;
  word-break: break-all;
}

.port-tooltip-desc {
  font-size: 0.7rem;
  color: #cbd5e1;
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px solid #334155;
  max-width: 200px;
  white-space: normal;
}

/* Connection compatibility highlighting */
.workflow-node.is-connecting-source {
  box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.5);
  z-index: 100;
}

.workflow-node.is-compatible-target {
  box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.8);
  animation: pulse-green 1.5s infinite;
}

.workflow-node.is-incompatible-target {
  opacity: 0.4;
  filter: grayscale(50%);
}

.port-compatible {
  animation: pulse-glow 1s infinite;
  transform: scale(1.4);
  z-index: 20;
}

.port-incompatible {
  opacity: 0.3;
  filter: grayscale(100%);
}

@keyframes pulse-green {
  0%, 100% {
    box-shadow: 0 0 0 3px rgba(74, 222, 128, 0.8);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(74, 222, 128, 0.4);
  }
}

@keyframes pulse-glow {
  0%, 100% {
    box-shadow: 0 0 8px currentColor;
  }
  50% {
    box-shadow: 0 0 16px currentColor;
  }
}
</style>
