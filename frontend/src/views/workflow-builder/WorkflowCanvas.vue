<template>
  <div
    ref="canvasRef"
    class="workflow-canvas"
    @mousemove="handleMouseMove"
    @mouseup="handleCanvasMouseUp"
    @mouseleave="handleCanvasMouseUp"
    @mousedown="handleCanvasMouseDown"
    @contextmenu="handleCanvasContextMenu"
  >
    <div class="canvas-surface" ref="surfaceRef">
      <!-- SVG layer for edges -->
      <svg class="edges-layer">
        <defs>
          <!-- Valid edge arrowhead (emerald, slightly muted from #4ade80) -->
          <marker
            id="arrowhead-valid"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="3"
            orient="auto"
          >
            <polygon points="0 0, 10 3, 0 6" fill="#10b981" />
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
            :stroke="edge.isValid === false ? '#ef4444' : '#10b981'"
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
          stroke="#10b981"
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
      <template v-if="contextMenu.nodeId !== null">
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
        <div class="context-menu-item" @click="cutSelection">
          <i class="pi pi-scissors"></i>
          <span v-if="selectedNodeIds.size > 1">Cut {{ selectedNodeIds.size }} Nodes</span>
          <span v-else>Cut Node</span>
        </div>
        <div class="context-menu-item" @click="copySelection">
          <i class="pi pi-copy"></i>
          <span v-if="selectedNodeIds.size > 1">Copy {{ selectedNodeIds.size }} Nodes</span>
          <span v-else>Copy Node</span>
        </div>
        <div class="context-menu-item" @click="pasteSelection">
          <i class="pi pi-clipboard"></i>
          <span>Paste</span>
        </div>
        <div class="context-menu-item" @click="duplicateSelection">
          <i class="pi pi-clone"></i>
          <span v-if="selectedNodeIds.size > 1">Duplicate {{ selectedNodeIds.size }} Nodes</span>
          <span v-else>Duplicate Node</span>
        </div>
        <div class="context-menu-item danger" @click="deleteSelection">
          <i class="pi pi-trash"></i>
          <span v-if="selectedNodeIds.size > 1">Delete {{ selectedNodeIds.size }} Nodes</span>
          <span v-else>Delete Node</span>
        </div>
      </template>
      <template v-else>
        <!-- Canvas background context menu -->
        <div class="context-menu-item" @click="pasteSelection">
          <i class="pi pi-clipboard"></i>
          <span>Paste</span>
        </div>
      </template>
    </div>

      <!-- Rubber-band selection box -->
      <div
        v-if="isRubberBanding"
        class="rubber-band"
        :style="{
          left: `${Math.min(rubberBandStart.x, rubberBandCurrent.x)}px`,
          top: `${Math.min(rubberBandStart.y, rubberBandCurrent.y)}px`,
          width: `${Math.abs(rubberBandCurrent.x - rubberBandStart.x)}px`,
          height: `${Math.abs(rubberBandCurrent.y - rubberBandStart.y)}px`
        }"
      ></div>

      <!-- Selection Badge -->
      <div v-if="selectedNodeIds.size > 1" class="selection-badge">
        {{ selectedNodeIds.size }} nodes selected
      </div>

      <!-- Nodes layer -->
      <div
        v-for="node in nodes"
        :key="node.id"
        class="workflow-node"
        :class="{
          'is-selected': selectedNodeIds.has(node.id),
          'is-dragging': isDragging && selectedNodeIds.has(node.id),
          'is-connecting-source': connecting === node.id,
          'is-compatible-target': isConnecting && connecting !== node.id && isNodeCompatibleTarget(node.id),
          'is-incompatible-target': isConnecting && connecting !== node.id && !isNodeCompatibleTarget(node.id),
          [`node-type-${getNodeCategory(node.type)}`]: true
        }"
        :style="{ left: `${node.x}px`, top: `${node.y}px` }"
        @mousedown.stop="handleNodeMouseDown($event, node.id)"
        @contextmenu.prevent="handleNodeContextMenu($event, node.id)"
      >
      <!-- Input ports (top edge) — click a compatible port while connecting to complete the edge -->
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
            left: `${30 + idx * 20}px`,
            backgroundColor: getPortColor(getPortCategory(port.type_ref))
          }"
          :title="isConnecting ? getPortCompatibilityReason(node.id, port.name) || `${port.label} (${getTypeName(port.type_ref)})` : `${port.label} (${getTypeName(port.type_ref)})`"
          @click.stop="onInputPortClick(node.id, port.name)"
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

      <!-- Output ports (bottom edge) — click a port to start a connection from it -->
      <div class="output-ports">
        <div
          v-for="(port, idx) in getNodeOutputPorts(node.type)"
          :key="`output-${port.name}`"
          class="port port-output"
          :style="{
            left: `${30 + idx * 20}px`,
            backgroundColor: getPortColor(getPortCategory(port.type_ref))
          }"
          :title="`${port.label} (${getTypeName(port.type_ref)}) — click to start a connection`"
          @click.stop="startConnect(node.id, port.name)"
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
        <span class="node-label" :title="getNodeLabel(node.type)">
          {{ getNodeLabel(node.type) }}
        </span>
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

      <!-- Cancel pill — only when this node is the active connection source. -->
      <button
        v-if="connecting === node.id"
        class="cancel-connect-pill"
        @click.stop="cancelConnect"
      >
        <i class="pi pi-times"></i>
        Cancel
      </button>
      </div>

      <!-- Empty state -->
      <div v-if="nodes.length === 0" class="empty-state">
        <i class="pi pi-share-alt empty-icon" aria-hidden="true"></i>
        <h3 class="empty-title">Start your workflow</h3>
        <p>Drag a node from the toolbar on the left, or pick a starter from the Actions menu.</p>
        <div class="empty-pointer">
          <i class="pi pi-arrow-left"></i>
          <span>Pick a node category to begin</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useWorkflowStore } from "@/stores/workflow";
import { getNodeVisualCategory } from "@/utils/nodeVisuals";
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
  (e: 'cut-selection'): void;
  (e: 'copy-selection'): void;
  (e: 'paste-selection'): void;
  (e: 'duplicate-selection'): void;
  (e: 'delete-selection'): void;
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

const NODE_ICONS: Record<string, string> = {
  'data.source': '📊',
  'data.my_dataset': '🧪',
  'preprocess.normalize': '⚖️',
  'preprocess.scale': '📏',
  'baseline.penalized_ls': '📉',
  'preprocess.smooth': '〰️',
  'model.pca': '🔀',
  'model.pls': '📈',
  'model.mcr_als': '🧩',
  'model.efa': '🔍',
  'model.simplisma': '🎯',
  'analysis.peak_finding': '⛰️',
  'analysis.peak_id': '🔬',
  'analysis.compare_library': '📚',
  'stats.summary': '📊',
  'output.plot': '📈',
  'output.contour': '🗺️',
  'output.export': '💾',
};

const getNodeIcon = (type: string): string => {
  return NODE_ICONS[type] || '📦';
};

const getNodeLabel = (type: string): string => {
  const metadata = workflowStore.getNodeMetadata(type);
  if (metadata?.label) {
    return metadata.label;
  }
  return type;
};

const getNodeCategory = (type: string): string => {
  const metadata = workflowStore.getNodeMetadata(type);
  return getNodeVisualCategory(type, metadata);
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
const surfaceRef = ref<HTMLElement | null>(null);

const selectedNodeIds = ref<Set<string>>(new Set());
const isDragging = ref(false);
const dragOrigin = ref<{ x: number; y: number } | null>(null);
const dragStartPositions = ref<Map<string, { x: number; y: number }>>(new Map());

const isRubberBanding = ref(false);
const rubberBandStart = ref({ x: 0, y: 0 });
const rubberBandCurrent = ref({ x: 0, y: 0 });
const rubberBandInitialSelection = ref<Set<string>>(new Set());
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

// Node coordinates map for O(1) lookups during edge rendering
const nodePositionMap = computed(() => {
  const map = new Map<string, { x: number; y: number }>();
  for (const node of props.nodes) {
    map.set(node.id, { x: node.x, y: node.y });
  }
  return map;
});

// Get node center position for edge drawing
const getNodeCenter = (nodeId: string | null) => {
  if (!nodeId) return { x: 0, y: 0 };
  const pos = nodePositionMap.value.get(nodeId);
  if (!pos) return { x: 0, y: 0 };
  return {
    x: pos.x + 80, // Half of node width
    y: pos.y + 50, // Half of node height
  };
};

// Mouse event handlers
const hasDragged = ref(false);
const DRAG_THRESHOLD = 5; // Pixels before considering it a drag

const handleNodeMouseDown = (event: MouseEvent, nodeId: string) => {
  if (event.button !== 0) {
    return;
  }

  const node = props.nodes.find(n => n.id === nodeId);
  if (!node) return;

  // Skip if clicking on buttons
  if ((event.target as HTMLElement).tagName === 'BUTTON' ||
      (event.target as HTMLElement).closest('button')) {
    return;
  }

  // Handle selection state based on modifiers
  const isCtrlOrCmd = event.ctrlKey || event.metaKey;
  const isShift = event.shiftKey;

  if (isCtrlOrCmd) {
    // Toggle selection
    if (selectedNodeIds.value.has(nodeId)) {
      selectedNodeIds.value.delete(nodeId);
    } else {
      selectedNodeIds.value.add(nodeId);
    }
  } else if (isShift) {
    // Add to selection
    selectedNodeIds.value.add(nodeId);
  } else {
    // If clicking a node that isn't selected without modifiers, select only it
    if (!selectedNodeIds.value.has(nodeId)) {
      selectedNodeIds.value.clear();
      selectedNodeIds.value.add(nodeId);
    }
  }

  // Always emit single node-select for the inspector if we just clicked one
  if (selectedNodeIds.value.has(nodeId)) {
    emit('node-select', node);
  }

  // Prepare for potential dragging of all selected nodes
  isDragging.value = true;
  hasDragged.value = false;
  dragOrigin.value = { x: event.clientX, y: event.clientY };
  
  dragStartPositions.value.clear();
  selectedNodeIds.value.forEach(id => {
    const n = props.nodes.find(x => x.id === id);
    if (n) {
      dragStartPositions.value.set(id, { x: n.x, y: n.y });
    }
  });
};

const handleMouseMove = (event: MouseEvent) => {
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  const localX = event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0);
  const localY = event.clientY - rect.top + (canvasRef.value?.scrollTop || 0);
  mousePos.value = { x: localX, y: localY };

  if (isRubberBanding.value) {
    rubberBandCurrent.value = { x: localX, y: localY };
    
    // Compute intersection
    const rx1 = Math.min(rubberBandStart.value.x, rubberBandCurrent.value.x);
    const ry1 = Math.min(rubberBandStart.value.y, rubberBandCurrent.value.y);
    const rx2 = Math.max(rubberBandStart.value.x, rubberBandCurrent.value.x);
    const ry2 = Math.max(rubberBandStart.value.y, rubberBandCurrent.value.y);

    const isShift = event.shiftKey;
    const newSelection = isShift ? new Set(rubberBandInitialSelection.value) : new Set<string>();

    props.nodes.forEach(n => {
      // Node dimensions: 160px wide, ~100px high (approximate)
      const nx1 = n.x, ny1 = n.y, nx2 = n.x + 160, ny2 = n.y + 100;
      const intersects = !(rx2 < nx1 || rx1 > nx2 || ry2 < ny1 || ry1 > ny2);
      
      if (intersects) {
        newSelection.add(n.id);
      }
    });
    
    selectedNodeIds.value = newSelection;
    return;
  }

  if (!isDragging.value || !dragOrigin.value) return;

  const dx = event.clientX - dragOrigin.value.x;
  const dy = event.clientY - dragOrigin.value.y;

  if (!hasDragged.value && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
    hasDragged.value = true;
  }

  if (hasDragged.value) {
    const updatedNodes = props.nodes.map(n => {
      if (selectedNodeIds.value.has(n.id)) {
        const startPos = dragStartPositions.value.get(n.id);
        if (startPos) {
          return { ...n, x: Math.max(0, startPos.x + dx), y: Math.max(0, startPos.y + dy) };
        }
      }
      return n;
    });
    emit('update:nodes', updatedNodes);
  }
};

const handleCanvasMouseDown = (event: MouseEvent) => {
  if (event.button !== 0) {
    return;
  }

  if ((event.target as HTMLElement).closest('.workflow-node') || 
      (event.target as HTMLElement).closest('.context-menu')) {
    return;
  }
  
  // Clicked on empty canvas -> start rubber banding
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  const localX = event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0);
  const localY = event.clientY - rect.top + (canvasRef.value?.scrollTop || 0);

  isRubberBanding.value = true;
  rubberBandStart.value = { x: localX, y: localY };
  rubberBandCurrent.value = { x: localX, y: localY };
  
  if (event.shiftKey) {
    rubberBandInitialSelection.value = new Set(selectedNodeIds.value);
  } else {
    rubberBandInitialSelection.value = new Set();
    selectedNodeIds.value.clear();
    emit('node-select', null);
  }
};

const handleCanvasMouseUp = () => {
  if (isRubberBanding.value) {
    isRubberBanding.value = false;
    
    // If they just clicked without dragging, clear selection
    if (rubberBandStart.value.x === rubberBandCurrent.value.x && 
        rubberBandStart.value.y === rubberBandCurrent.value.y && 
        !rubberBandInitialSelection.value.size) {
      selectedNodeIds.value.clear();
      emit('node-select', null);
    }
  }

  isDragging.value = false;
  dragOrigin.value = null;
  dragStartPositions.value.clear();
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

// Input-port click: only meaningful while a connection is in flight from another
// node. No-op otherwise (input ports aren't a connection start point).
const onInputPortClick = (nodeId: string, portName: string) => {
  if (!isConnecting.value || connecting.value === nodeId) return;
  if (!isPortCompatible(nodeId, portName)) return;
  completeConnect(nodeId, portName);
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

  if (selectedNodeIds.value.has(nodeId)) {
    selectedNodeIds.value.delete(nodeId);
    if (selectedNodeIds.value.size === 0) {
      emit('node-select', null);
    }
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
const handleCanvasContextMenu = (event: MouseEvent) => {
  // If clicking on a node or an existing context menu, let their handlers run
  if ((event.target as HTMLElement).closest('.workflow-node') || 
      (event.target as HTMLElement).closest('.context-menu')) {
    return;
  }
  
  event.preventDefault();
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  contextMenu.value = {
    show: true,
    x: event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0),
    y: event.clientY - rect.top + (canvasRef.value?.scrollTop || 0),
    nodeId: null, // null means canvas background
  };

  const closeMenu = () => {
    contextMenu.value.show = false;
    document.removeEventListener('click', closeMenu);
  };
  setTimeout(() => document.addEventListener('click', closeMenu), 0);
};

const handleNodeContextMenu = (event: MouseEvent, nodeId: string) => {
  event.preventDefault();
  event.stopPropagation();
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;

  contextMenu.value = {
    show: true,
    x: event.clientX - rect.left + (canvasRef.value?.scrollLeft || 0),
    y: event.clientY - rect.top + (canvasRef.value?.scrollTop || 0),
    nodeId,
  };

  // If node isn't selected, select it (unless right-clicking a multi-selection)
  if (!selectedNodeIds.value.has(nodeId)) {
    selectedNodeIds.value.clear();
    selectedNodeIds.value.add(nodeId);
    const node = props.nodes.find(n => n.id === nodeId);
    if (node) emit('node-select', node);
  }

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

const cutSelection = () => {
  emit('cut-selection');
  contextMenu.value.show = false;
};

const copySelection = () => {
  emit('copy-selection');
  contextMenu.value.show = false;
};

const pasteSelection = () => {
  emit('paste-selection');
  contextMenu.value.show = false;
};

const duplicateSelection = () => {
  emit('duplicate-selection');
  contextMenu.value.show = false;
};

const deleteSelection = () => {
  emit('delete-selection');
  contextMenu.value.show = false;
};

// Watch for external selection changes (if nodes are deleted externally)
watch(() => props.nodes, () => {
  let changed = false;
  for (const id of selectedNodeIds.value) {
    if (!props.nodes.some(n => n.id === id)) {
      selectedNodeIds.value.delete(id);
      changed = true;
    }
  }
  if (changed && selectedNodeIds.value.size === 0) {
    emit('node-select', null);
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

const selectAll = () => {
  selectedNodeIds.value = new Set(props.nodes.map(n => n.id));
};

const clearSelection = () => {
  selectedNodeIds.value.clear();
  emit('node-select', null);
};

defineExpose({ centerNode, selectedNodeIds, selectAll, clearSelection });
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
  fill: #10b981;
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
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.4), 0 0 15px rgba(59, 130, 246, 0.2);
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
.header-synthesis { background: linear-gradient(135deg, #06b6d4, #0891b2); }
.header-preprocess { background: linear-gradient(135deg, #22c55e, #16a34a); }
.header-selection { background: linear-gradient(135deg, #14b8a6, #0d9488); }
.header-exploratory { background: linear-gradient(135deg, #a855f7, #9333ea); }
.header-regression { background: linear-gradient(135deg, #8b5cf6, #7c3aed); }
.header-classify { background: linear-gradient(135deg, #f59e0b, #d97706); }
.header-clustering { background: linear-gradient(135deg, #ec4899, #db2777); }
.header-validation { background: linear-gradient(135deg, #eab308, #ca8a04); }
.header-visualize { background: linear-gradient(135deg, #f97316, #ea580c); }
.header-export { background: linear-gradient(135deg, #64748b, #475569); }
.header-plugin,
.header-default { background: linear-gradient(135deg, #ec4899, #be185d); }

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
  color: #10b981;
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

/* Cancel pill — sits below the node body only while this node is the
   active connection source. Connections themselves start by clicking
   an output dot and complete by clicking a compatible input dot. */
.cancel-connect-pill {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 8px;
  padding: 4px 10px;
  background: #ef4444;
  border: none;
  border-radius: 999px;
  color: white;
  font-size: 0.7rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.cancel-connect-pill:hover {
  background: #dc2626;
}

.empty-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #94a3b8;
  max-width: 28rem;
}

.empty-icon {
  font-size: 2.25rem;
  margin-bottom: 12px;
  color: #94a3b8;
}

.empty-title {
  margin: 0 0 8px;
  color: #e2e8f0;
  font-size: 1.05rem;
  font-weight: 600;
}

.empty-state p {
  margin: 0 0 14px;
  font-size: 0.92rem;
  line-height: 1.5;
}

.empty-pointer {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px dashed #475569;
  border-radius: 999px;
  color: #cbd5e1;
  font-size: 0.8rem;
}

.empty-pointer i {
  color: #60a5fa;
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

/* Port indicators — inputs on the top edge, outputs on the bottom edge.
 * Each port lane spans the full node width so individual port circles
 * position themselves with `left: ${30 + idx * 20}px` from the template. */
.input-ports,
.output-ports {
  position: absolute;
  left: 0;
  right: 0;
  width: 100%;
  pointer-events: none;
}

.input-ports {
  top: -6px;
}

.output-ports {
  bottom: -6px;
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

/* Inputs nudged up so half the circle sits above the node's top edge,
 * outputs nudged down so half the circle sits below the bottom edge —
 * mirrors the previous left/right behaviour after the axis swap. */
.port-input {
  transform: translateY(-50%);
}

.port-output {
  transform: translateY(50%);
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
  color: #10b981;
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

/* Rubber band selection */
.rubber-band {
  position: absolute;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(59, 130, 246, 0.6);
  pointer-events: none;
  z-index: 50;
}

/* Selection Badge */
.selection-badge {
  position: fixed;
  top: 80px;
  right: 20px;
  background: #2563eb;
  color: white;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  pointer-events: none;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
