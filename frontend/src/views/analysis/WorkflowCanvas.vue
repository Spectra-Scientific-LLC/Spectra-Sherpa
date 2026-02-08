<template>
  <div class="workflow-canvas">
    <VueFlow
      v-model:nodes="nodes"
      v-model:edges="edges"
      :default-zoom="1"
      :min-zoom="0.2"
      :max-zoom="4"
      @node-click="onNodeClick"
      @node-double-click="onNodeDoubleClick"
      @edge-update="onEdgeUpdate"
      @connect="onConnect"
    >
      <!-- Background pattern -->
      <Background pattern-color="#e2e8f0" :gap="16" />

      <!-- Minimap for navigation -->
      <MiniMap />

      <!-- Controls (zoom, fit view, etc.) -->
      <Controls />

      <!-- Custom node template -->
      <template #node-custom="{ data }">
        <div class="custom-node">
          <div class="node-header" :class="`node-type-${data.nodeType}`">
            <i :class="getNodeIcon(data.nodeType)" />
            <span>{{ data.label }}</span>
          </div>
          <div class="node-body">
            <div v-if="data.status" class="node-status">
              <i
                :class="getStatusIcon(data.status)"
                :style="{ color: getStatusColor(data.status) }"
              />
            </div>
          </div>
          <Handle type="target" :position="Position.Left" />
          <Handle type="source" :position="Position.Right" />
        </div>
      </template>
    </VueFlow>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { VueFlow, Handle, Position } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { MiniMap } from "@vue-flow/minimap";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import "@vue-flow/controls/dist/style.css";
import "@vue-flow/minimap/dist/style.css";

interface Props {
  nodes: any[];
  edges: any[];
}

interface Emits {
  (e: "update:nodes", nodes: any[]): void;
  (e: "update:edges", edges: any[]): void;
  (e: "node-click", event: any): void;
  (e: "node-double-click", event: any): void;
}

const props = defineProps<Props>();
const emit = defineEmits<Emits>();

const nodes = ref(props.nodes);
const edges = ref(props.edges);

watch(
  () => props.nodes,
  (newNodes) => {
    nodes.value = newNodes;
  }
);

watch(
  () => props.edges,
  (newEdges) => {
    edges.value = newEdges;
  }
);

watch(nodes, (newNodes) => {
  emit("update:nodes", newNodes);
});

watch(edges, (newEdges) => {
  emit("update:edges", newEdges);
});

const onNodeClick = (event: any) => {
  emit("node-click", event);
};

const onNodeDoubleClick = (event: any) => {
  emit("node-double-click", event);
};

const onEdgeUpdate = ({ edge, connection }: any) => {
  const index = edges.value.findIndex((e) => e.id === edge.id);
  if (index !== -1) {
    edges.value[index] = { ...edge, ...connection };
  }
};

const onConnect = (connection: any) => {
  edges.value.push({
    id: `edge_${Date.now()}`,
    ...connection,
  });
};

const getNodeIcon = (nodeType: string) => {
  const iconMap: Record<string, string> = {
    preprocessing: "pi pi-cog",
    modeling: "pi pi-chart-line",
    diagnostics: "pi pi-check-circle",
    export: "pi pi-download",
    input: "pi pi-file",
  };
  return iconMap[nodeType] || "pi pi-box";
};

const getStatusIcon = (status: string) => {
  const statusIconMap: Record<string, string> = {
    pending: "pi pi-clock",
    running: "pi pi-spin pi-spinner",
    completed: "pi pi-check",
    error: "pi pi-times",
  };
  return statusIconMap[status] || "";
};

const getStatusColor = (status: string) => {
  const colorMap: Record<string, string> = {
    pending: "#64748b",
    running: "#3b82f6",
    completed: "#22c55e",
    error: "#ef4444",
  };
  return colorMap[status] || "#64748b";
};
</script>

<style scoped>
.workflow-canvas {
  width: 100%;
  height: 100%;
}

.custom-node {
  background: #ffffff;
  border: 2px solid #e2e8f0;
  border-radius: 8px;
  min-width: 180px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.custom-node:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #e2e8f0;
  font-weight: 500;
  font-size: 0.9rem;
}

.node-type-preprocessing .node-header {
  background: #eff6ff;
  color: #1e40af;
}

.node-type-modeling .node-header {
  background: #f0fdf4;
  color: #15803d;
}

.node-type-diagnostics .node-header {
  background: #fef3c7;
  color: #92400e;
}

.node-type-export .node-header {
  background: #f3e8ff;
  color: #6b21a8;
}

.node-body {
  padding: 12px;
  min-height: 40px;
}

.node-status {
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
