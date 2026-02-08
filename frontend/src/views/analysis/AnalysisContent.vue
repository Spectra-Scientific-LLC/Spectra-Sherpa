<template>
  <div class="analysis-content">
    <div class="section-header">
      <div>
        <h1>Analysis Workflow</h1>
        <p class="section-subtitle">
          Build visual workflows for spectral analysis using drag-and-drop nodes
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="New Workflow"
          icon="pi pi-plus"
          @click="createNewWorkflow"
        />
        <Button
          label="Save"
          icon="pi pi-save"
          :disabled="!hasChanges"
          @click="saveWorkflow"
        />
        <Button
          label="Export Python"
          icon="pi pi-download"
          class="p-button-secondary"
          @click="exportToPython"
        />
        <Button
          :icon="llmPanelExpanded ? 'pi pi-comment' : 'pi pi-comment-slash'"
          :label="llmPanelExpanded ? 'Hide Assistant' : 'Show Assistant'"
          class="p-button-outlined"
          @click="toggleLLMPanel"
        />
      </div>
    </div>

    <!-- Three-panel layout: NodeLibrary | Canvas | Inspector/LLM Panel -->
    <div class="analysis-workspace" :class="{ 'library-expanded': nodeLibraryExpanded }">
      <!-- Left Panel: Node Library -->
      <NodeLibrary @add-node="onAddNode" @expand="onNodeLibraryExpand" />

      <!-- Center Panel: Workflow Canvas -->
      <div class="canvas-container" :style="{ gridColumn: llmPanelExpanded ? 'span 1' : 'span 2' }">
        <WorkflowCanvas
          v-model:nodes="nodes"
          v-model:edges="edges"
          @node-click="onNodeClick"
          @node-double-click="onNodeDoubleClick"
        />
      </div>

      <!-- Right Panel: LLM Chat (collapsible & resizable) -->
      <div
        v-if="llmPanelExpanded"
        class="llm-panel-container"
        :style="{ width: `${llmPanelWidth}px` }"
      >
        <div class="resize-handle" @mousedown="startResize"></div>
        <LLMChatPanel
          :workflow-context="{ nodes, edges, selectedNode }"
          @close="toggleLLMPanel"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import Button from "primevue/button";
import { useToast } from "primevue/usetoast";
import NodeLibrary from "./NodeLibrary.vue";
import WorkflowCanvas from "./WorkflowCanvas.vue";
import LLMChatPanel from "./LLMChatPanel.vue";

const toast = useToast();

// Workflow state
const nodes = ref<any[]>([]);
const edges = ref<any[]>([]);
const selectedNode = ref<any>(null);
const nodeResults = ref<Map<string, any>>(new Map());
const hasChanges = ref(false);

// LLM Panel state
const llmPanelExpanded = ref(true); // Default: expanded
const llmPanelWidth = ref(500); // Default: ~30% of typical screen
const isResizing = ref(false);
const startX = ref(0);
const startWidth = ref(0);

// Node Library expansion state
const nodeLibraryExpanded = ref(false);

const createNewWorkflow = () => {
  if (hasChanges.value) {
    // TODO: Prompt user to save
  }
  nodes.value = [];
  edges.value = [];
  selectedNode.value = null;
  nodeResults.value.clear();
  hasChanges.value = false;
  toast.add({
    severity: "info",
    summary: "New Workflow",
    detail: "Created new workflow canvas",
    life: 2000,
  });
};

const saveWorkflow = async () => {
  try {
    // TODO: API call to save workflow
    toast.add({
      severity: "success",
      summary: "Saved",
      detail: "Workflow saved successfully",
      life: 2000,
    });
    hasChanges.value = false;
  } catch (error) {
    toast.add({
      severity: "error",
      summary: "Save Failed",
      detail: "Unable to save workflow",
      life: 3000,
    });
  }
};

const exportToPython = async () => {
  try {
    // TODO: API call to export workflow to Python script
    toast.add({
      severity: "info",
      summary: "Export",
      detail: "Python script downloaded",
      life: 2000,
    });
  } catch (error) {
    toast.add({
      severity: "error",
      summary: "Export Failed",
      detail: "Unable to export workflow",
      life: 3000,
    });
  }
};

const onAddNode = (nodeType: string) => {
  const newNode = {
    id: `node_${Date.now()}`,
    type: nodeType,
    position: { x: 100, y: 100 },
    data: {
      label: nodeType,
      parameters: {},
    },
  };
  nodes.value.push(newNode);
  hasChanges.value = true;
};

const onNodeLibraryExpand = (expanded: boolean) => {
  nodeLibraryExpanded.value = expanded;
};

const onNodeClick = (event: any) => {
  selectedNode.value = nodes.value.find((n) => n.id === event.node.id);
};

const onNodeDoubleClick = (event: any) => {
  // TODO: Execute node or show detailed view
  console.log("Double-clicked node:", event.node);
};

const onUpdateParameters = (nodeId: string, parameters: any) => {
  const node = nodes.value.find((n) => n.id === nodeId);
  if (node) {
    node.data.parameters = parameters;
    hasChanges.value = true;
    // TODO: Re-execute node with new parameters
  }
};

// LLM Panel functions
const toggleLLMPanel = () => {
  llmPanelExpanded.value = !llmPanelExpanded.value;
};

const startResize = (event: MouseEvent) => {
  isResizing.value = true;
  startX.value = event.clientX;
  startWidth.value = llmPanelWidth.value;

  document.addEventListener('mousemove', handleResize);
  document.addEventListener('mouseup', stopResize);

  event.preventDefault();
};

const handleResize = (event: MouseEvent) => {
  if (!isResizing.value) return;

  const diff = startX.value - event.clientX;
  const newWidth = startWidth.value + diff;

  // Constrain between 300px and 800px
  llmPanelWidth.value = Math.max(300, Math.min(800, newWidth));
};

const stopResize = () => {
  isResizing.value = false;
  document.removeEventListener('mousemove', handleResize);
  document.removeEventListener('mouseup', stopResize);
};

// Cleanup on unmount
onUnmounted(() => {
  if (isResizing.value) {
    stopResize();
  }
});
</script>

<style scoped>
.analysis-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 16px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.analysis-workspace {
  display: grid;
  grid-template-columns: 250px 1fr auto;
  gap: 16px;
  flex: 1;
  min-height: 0;
  position: relative;
  transition: grid-template-columns 0.3s ease;
}

.analysis-workspace.library-expanded {
  grid-template-columns: 500px 1fr auto;
}

.canvas-container {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  position: relative;
  transition: grid-column 0.3s ease;
}

.llm-panel-container {
  position: relative;
  display: flex;
  min-width: 300px;
  max-width: 800px;
  transition: width 0.1s ease-out;
}

.resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: ew-resize;
  background: transparent;
  z-index: 10;
  transition: background 0.2s ease;
}

.resize-handle:hover {
  background: linear-gradient(to right, transparent, #e2e8f0 50%, transparent);
}

.resize-handle:active {
  background: linear-gradient(to right, transparent, #cbd5e1 50%, transparent);
}

@media (max-width: 1200px) {
  .analysis-workspace {
    grid-template-columns: 200px 1fr auto;
  }
}

@media (max-width: 900px) {
  .analysis-workspace {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr auto;
  }

  .llm-panel-container {
    position: fixed;
    right: 0;
    top: 80px;
    bottom: 0;
    width: 100% !important;
    max-width: 400px;
    z-index: 1000;
    box-shadow: -4px 0 12px rgba(0, 0, 0, 0.1);
  }
}
</style>
