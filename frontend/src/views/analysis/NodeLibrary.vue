<template>
  <div class="node-library">
    <div class="library-header">
      <h3>Node Library</h3>
      <InputText
        v-model="searchQuery"
        placeholder="Search nodes..."
        class="search-input"
      />
    </div>

    <div v-if="loading" class="library-content">
      <div class="loading-message">Loading nodes...</div>
    </div>

    <div v-else-if="error" class="library-content">
      <div class="error-message">{{ error }}</div>
    </div>

    <div v-else class="library-content-horizontal">
      <!-- Left panel: Categories -->
      <div class="categories-panel">
        <div
          v-for="category in categories"
          :key="category"
          class="category-item"
          :class="{ 'category-item-hovered': hoveredCategory === category }"
          @mouseenter="onCategoryHover(category)"
          @mouseleave="onCategoryLeave"
        >
          <i :class="categoryMetadata[category]?.icon || 'pi pi-circle'"></i>
          <span>{{ categoryMetadata[category]?.label || category }}</span>
        </div>

        <div v-if="categories.length === 0" class="no-results">
          No nodes found
        </div>
      </div>

      <!-- Right panel: Nodes for hovered category -->
      <div class="nodes-panel">
        <div v-if="hoveredCategory && nodesByCategory[hoveredCategory]" class="nodes-grid">
          <div
            v-for="node in nodesByCategory[hoveredCategory]"
            :key="node.node_type"
            class="node-item"
            draggable="true"
            @click="addNode(node.node_type)"
            :title="node.description"
          >
            <i :class="node.icon"></i>
            <span>{{ node.label }}</span>
          </div>
        </div>
        <div v-else class="nodes-placeholder">
          Hover over a category to see nodes
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import InputText from "primevue/inputtext";
import axios from "axios";

interface NodeDefinition {
  node_type: string;
  label: string;
  icon: string;
  category: string;
  description: string;
}

interface Emits {
  (e: "add-node", nodeType: string): void;
  (e: "expand", expanded: boolean): void;
}

const emit = defineEmits<Emits>();

const searchQuery = ref("");
const allNodes = ref<NodeDefinition[]>([]);
const loading = ref(true);
const error = ref<string | null>(null);
const hoveredCategory = ref<string | null>(null);

// Category metadata
const categoryMetadata: Record<string, { icon: string; label: string }> = {
  preprocessing: { icon: "pi pi-cog", label: "Preprocessing" },
  modeling: { icon: "pi pi-chart-line", label: "Modeling" },
  classification: { icon: "pi pi-sitemap", label: "Classification" },
  analysis: { icon: "pi pi-calculator", label: "Analysis" },
  data: { icon: "pi pi-database", label: "Data" },
  output: { icon: "pi pi-chart-bar", label: "Output" },
  synthesis: { icon: "pi pi-flask", label: "Synthesis" },
};

// Fetch nodes from backend API
const fetchNodes = async () => {
  try {
    loading.value = true;
    error.value = null;
    const response = await axios.get("/api/v1/workflows/nodes/library");

    // Map backend nodes to frontend format with default icons
    allNodes.value = response.data.nodes.map((node: any) => ({
      node_type: node.node_type,
      label: node.label,
      category: node.category,
      description: node.description,
      icon: getCategoryIcon(node.category, node.node_type),
    }));
  } catch (err: any) {
    error.value = err.message || "Failed to fetch node library";
    console.error("Error fetching node library:", err);
  } finally {
    loading.value = false;
  }
};

// Get icon based on category or node type
const getCategoryIcon = (category: string, nodeType: string): string => {
  // Node-specific icons
  if (nodeType.includes("baseline")) return "pi pi-minus";
  if (nodeType.includes("smooth")) return "pi pi-wave-pulse";
  if (nodeType.includes("normalize")) return "pi pi-arrows-v";
  if (nodeType.includes("derivative")) return "pi pi-chart-line";
  if (nodeType.includes("filter")) return "pi pi-filter";
  if (nodeType.includes("pca") || nodeType.includes("pls")) return "pi pi-sitemap";
  if (nodeType.includes("knn")) return "pi pi-users";
  if (nodeType.includes("peak")) return "pi pi-chart-bar";
  if (nodeType.includes("outlier")) return "pi pi-exclamation-triangle";
  if (nodeType.includes("cross_validation")) return "pi pi-calculator";
  if (nodeType.includes("plot") || nodeType.includes("image")) return "pi pi-image";
  if (nodeType.includes("export") || nodeType.includes("save")) return "pi pi-save";
  if (nodeType.includes("load") || nodeType.includes("file")) return "pi pi-file";

  // Default category icons
  return categoryMetadata[category]?.icon || "pi pi-circle";
};

// Group nodes by category
const nodesByCategory = computed(() => {
  const filtered = allNodes.value.filter((node) => {
    if (!searchQuery.value) return true;
    const query = searchQuery.value.toLowerCase();
    return (
      node.label.toLowerCase().includes(query) ||
      node.description.toLowerCase().includes(query) ||
      node.node_type.toLowerCase().includes(query)
    );
  });

  const grouped: Record<string, NodeDefinition[]> = {};
  filtered.forEach((node) => {
    if (!grouped[node.category]) {
      grouped[node.category] = [];
    }
    grouped[node.category].push(node);
  });

  return grouped;
});

// Get sorted category list
const categories = computed(() => {
  return Object.keys(nodesByCategory.value).sort((a, b) => {
    const order = ["data", "preprocessing", "modeling", "classification", "analysis", "synthesis", "output"];
    const aIndex = order.indexOf(a);
    const bIndex = order.indexOf(b);
    if (aIndex === -1 && bIndex === -1) return a.localeCompare(b);
    if (aIndex === -1) return 1;
    if (bIndex === -1) return -1;
    return aIndex - bIndex;
  });
});

const onCategoryHover = (category: string) => {
  hoveredCategory.value = category;
  emit("expand", true);
};

const onCategoryLeave = () => {
  hoveredCategory.value = null;
  emit("expand", false);
};

const addNode = (nodeType: string) => {
  emit("add-node", nodeType);
  // Collapse after selection
  hoveredCategory.value = null;
  emit("expand", false);
};

onMounted(() => {
  fetchNodes();
});
</script>

<style scoped>
.node-library {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}

.library-header {
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.library-header h3 {
  margin: 0 0 12px 0;
  font-size: 1rem;
  font-weight: 600;
}

.search-input {
  width: 100%;
}

.library-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

/* Horizontal two-panel layout */
.library-content-horizontal {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Left panel: Categories */
.categories-panel {
  width: 160px;
  border-right: 1px solid #e2e8f0;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.category-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
  transition: all 0.2s;
}

.category-item i {
  font-size: 0.9rem;
  color: #64748b;
}

.category-item:hover {
  background: #f1f5f9;
}

.category-item-hovered {
  background: #3b82f6 !important;
  color: #ffffff !important;
  font-weight: 600;
}

.category-item-hovered i {
  color: #ffffff !important;
}

/* Right panel: Nodes */
.nodes-panel {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  background: #f8fafc;
}

.nodes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}

.node-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 8px;
  border-radius: 6px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.75rem;
  text-align: center;
  min-height: 70px;
}

.node-item:hover {
  background: #eff6ff;
  border-color: #3b82f6;
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.node-item i {
  font-size: 1.2rem;
  color: #3b82f6;
}

.nodes-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #94a3b8;
  font-size: 0.9rem;
  font-style: italic;
  text-align: center;
  padding: 24px;
}

.loading-message,
.error-message,
.no-results {
  padding: 24px;
  text-align: center;
  color: #64748b;
  font-size: 0.9rem;
}

.error-message {
  color: #dc2626;
}

.no-results {
  font-style: italic;
}
</style>
