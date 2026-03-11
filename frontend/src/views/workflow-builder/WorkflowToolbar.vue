<template>
  <div class="workflow-toolbar">
    <div class="toolbar-header">
      <h3>Add Nodes</h3>
    </div>

    <div class="toolbar-content">
      <!-- Data Sources Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'data')">
        <div class="section-header" :class="{ active: activeSection === 'data' }" @click="toggleSection('data')">
          <span>Data Sources</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'data' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'data' }">
          <div
            v-for="(config, type) in dataNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Synthesis Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'synthesis')">
        <div class="section-header" :class="{ active: activeSection === 'synthesis' }" @click="toggleSection('synthesis')">
          <span>Synthesis</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'synthesis' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'synthesis' }">
          <div
            v-for="(config, type) in synthesisNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Preprocessing Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'preprocess')">
        <div class="section-header" :class="{ active: activeSection === 'preprocess' }" @click="toggleSection('preprocess')">
          <span>Preprocessing</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'preprocess' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'preprocess' }">
          <div
            v-for="(config, type) in preprocessNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Exploratory Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'exploratory')">
        <div class="section-header" :class="{ active: activeSection === 'exploratory' }" @click="toggleSection('exploratory')">
          <span>Exploratory</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'exploratory' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'exploratory' }">
          <div
            v-for="(config, type) in exploratoryNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Regression Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'regression')">
        <div class="section-header" :class="{ active: activeSection === 'regression' }" @click="toggleSection('regression')">
          <span>Regression</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'regression' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'regression' }">
          <div
            v-for="(config, type) in regressionNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Classification Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'classification')">
        <div class="section-header" :class="{ active: activeSection === 'classification' }" @click="toggleSection('classification')">
          <span>Classification</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'classification' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'classification' }">
          <div
            v-for="(config, type) in classificationNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Clustering Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'clustering')">
        <div class="section-header" :class="{ active: activeSection === 'clustering' }" @click="toggleSection('clustering')">
          <span>Clustering</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'clustering' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'clustering' }">
          <div
            v-for="(config, type) in clusteringNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Validation Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'validation')">
        <div class="section-header" :class="{ active: activeSection === 'validation' }" @click="toggleSection('validation')">
          <span>Validation</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'validation' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'validation' }">
          <div
            v-for="(config, type) in validationNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Output Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'output')">
        <div class="section-header" :class="{ active: activeSection === 'output' }" @click="toggleSection('output')">
          <span>Output</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'output' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'output' }">
          <div
            v-for="(config, type) in outputNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Deployment Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'deploy')">
        <div class="section-header" :class="{ active: activeSection === 'deploy' }" @click="toggleSection('deploy')">
          <span>Deployment</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'deploy' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'deploy' }">
          <div
            v-for="(config, type) in deployNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>

      <!-- Dynamic sections for plugin/custom categories not in the built-in list -->
      <div
        v-for="extra in extraCategories"
        :key="extra.key"
        class="section"
        @mouseenter="!clickCooldown && (activeSection = extra.key)"
      >
        <div class="section-header" :class="{ active: activeSection === extra.key }" @click="toggleSection(extra.key)">
          <span>{{ extra.label }}</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === extra.key }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === extra.key }">
          <div
            v-for="(config, type) in extra.nodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
            <span v-if="config.description" class="node-desc">{{ config.description }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="toolbar-help">
      <h4>How to use</h4>
      <ol>
        <li>Add nodes from above</li>
        <li>Click "Connect" on a node</li>
        <li>Click destination node</li>
        <li>Adjust parameters on right</li>
        <li>Click "Execute Workflow"</li>
      </ol>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useWorkflowStore } from '@/stores/workflow';
import type { NodeTypeMetadata } from '@/types';

interface NodeConfig {
  label: string;
  icon: string;
  colorClass: string;
  description: string;
}

const emit = defineEmits<{
  (e: 'add-node', nodeType: string): void;
}>();

const workflowStore = useWorkflowStore();

// Active section state - starts with 'data' (Data Sources) open
const activeSection = ref<string>('data');

// Cooldown flag to prevent immediate re-expansion after clicking a node
const clickCooldown = ref<boolean>(false);

// Fetch node library on mount
onMounted(async () => {
  if (workflowStore.nodeLibrary.size === 0) {
    await workflowStore.fetchNodeLibrary();
  }
});

// Icon mappings by canonical node_type
const NODE_ICONS: Record<string, string> = {
  // Data sources
  'data.source': '📊',
  'data.file_load': '📂',
  'data.nist_library': '📚',
  'data.synthetic_curve': '📈',
  'data.train_test_split': '✂️',
  'data.attach_target': '🎯',
  // Synthesis
  'synthesis.species': '🧬',
  'synthesis.blend': '🔀',
  'synthesis.merge': '📚',
  // Preprocessing
  'preprocess.smooth': '〰️',
  'preprocess.derivative': '∂',
  'preprocess.normalize': '⚖️',
  'preprocess.scale': '📏',
  'baseline.penalized_ls': '📉',
  'baseline.rubberband': '📉',
  'preprocess.cosmic_ray': '✨',
  'preprocess.clip_range': '✂️',
  'preprocess.clip_floor': '⬆️',
  'preprocess.wavenumber_align': '⚙️',
  'preprocess.osc': '⊥',
  'preprocess.emsc': '📐',
  'time_series.moving_window': '🕒',
  'time_series.trend_removal': '📉',
  // Exploratory
  'model.pca': '🔀',
  'model.pca_transform': '⚙️',
  'model.mcr_als': '🧩',
  'model.simplisma': '🔎',
  'model.efa': '🔬',
  'model.nmf': '📊',
  'model.ica': '⚡',
  'analysis.peak_finding': '⛰️',
  // Regression
  'model.pls': '📈',
  'model.pls_predict': '🎯',
  'model.pcr': '🧮',
  'model.svr': '🧲',
  'model.linear_regression': '📉',
  'model.load_apply': '📦',
  // Clustering
  'model.kmeans': '🧭',
  'model.dbscan': '🫧',
  'model.hca': '🌳',
  // Validation
  'diagnostics.cross_validation': '🔄',
  'diagnostics.outliers': '🚨',
  'stats.summary': '📊',
  // Classification
  'classification.plsda': '🎯',
  'classification.knn': '👥',
  'classification.simca': '🎲',
  'classification.predict': '🔮',
  // Output
  'output.plot': '📈',
  'output.contour': '🗺️',
  'output.data_table': '📋',
  'output.export': '💾',
  // Deploy
  'deploy.input': '📥',
  'deploy.output': '📤',
};

// Category to color class mapping
const CATEGORY_COLOR: Record<string, string> = {
  data: 'node-data',
  synthesis: 'node-synthesis',
  preprocessing: 'node-preprocess',
  exploratory: 'node-exploratory',
  regression: 'node-regression',
  classification: 'node-classify',
  clustering: 'node-clustering',
  validation: 'node-validation',
  output: 'node-visualize',
  deploy: 'node-export',
};

// Category display names
const CATEGORY_LABELS: Record<string, string> = {
  data: 'Data',
  synthesis: 'Synthesis',
  preprocessing: 'Preprocessing',
  exploratory: 'Exploratory',
  regression: 'Regression',
  classification: 'Classification',
  clustering: 'Clustering',
  validation: 'Validation',
  output: 'Output',
  deploy: 'Deployment',
};

// Convert backend metadata to NodeConfig
const metadataToConfig = (metadata: NodeTypeMetadata): NodeConfig => {
  const baseColor = CATEGORY_COLOR[metadata.category] || 'node-plugin';
  const colorClass = metadata.node_type === 'output.export' ? 'node-export' : baseColor;
  return {
    label: metadata.label,
    icon: NODE_ICONS[metadata.node_type] || '📦',
    colorClass,
    description: metadata.description,
  };
};

// Built-in category keys handled by dedicated template sections
const BUILTIN_CATEGORIES = new Set(Object.keys(CATEGORY_LABELS));

// Dynamically group nodes by category from backend
const nodesByCategory = computed(() => {
  const groups: Record<string, Record<string, NodeConfig>> = {};

  // Initialize built-in categories
  for (const category of BUILTIN_CATEGORIES) {
    groups[category] = {};
  }

  // Populate from node library
  workflowStore.nodeLibrary.forEach((metadata, nodeType) => {
    const category = metadata.category;
    if (!groups[category]) {
      groups[category] = {};
    }
    groups[category][metadata.node_type] = metadataToConfig(metadata);
  });

  return groups;
});

// Extra categories from backend that aren't covered by the built-in template sections
const extraCategories = computed(() => {
  const extras: Array<{ key: string; label: string; nodes: Record<string, NodeConfig> }> = [];
  for (const [category, nodes] of Object.entries(nodesByCategory.value)) {
    if (!BUILTIN_CATEGORIES.has(category) && Object.keys(nodes).length > 0) {
      // Generate display label: "custom" -> "Custom", "spectral_analysis" -> "Spectral Analysis"
      const label = category
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      extras.push({ key: category, label, nodes });
    }
  }
  return extras;
});

// Direct access to backend-populated category groups (no fallbacks)
const dataNodes = computed(() => nodesByCategory.value.data || {});
const synthesisNodes = computed(() => nodesByCategory.value.synthesis || {});
const preprocessNodes = computed(() => nodesByCategory.value.preprocessing || {});
const exploratoryNodes = computed(() => nodesByCategory.value.exploratory || {});
const regressionNodes = computed(() => nodesByCategory.value.regression || {});
const clusteringNodes = computed(() => nodesByCategory.value.clustering || {});
const validationNodes = computed(() => nodesByCategory.value.validation || {});
const classificationNodes = computed(() => nodesByCategory.value.classification || {});
const outputNodes = computed(() => nodesByCategory.value.output || {});
const deployNodes = computed(() => nodesByCategory.value.deploy || {});

const toggleSection = (section: string) => {
  activeSection.value = activeSection.value === section ? '' : section;
};

const addNode = (nodeType: string) => {
  emit('add-node', nodeType);
  // Auto-collapse section after selection
  activeSection.value = '';

  // Enable cooldown to prevent immediate re-expansion
  clickCooldown.value = true;
  setTimeout(() => {
    clickCooldown.value = false;
  }, 500);
};
</script>

<style scoped>
.workflow-toolbar {
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.toolbar-header {
  padding: 16px;
  border-bottom: 1px solid #334155;
}

.toolbar-header h3 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
}

.toolbar-content {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* Section wrapper */
.section {
  border-radius: 8px;
  overflow: hidden;
}

/* Section headers - now interactive */
.section-header {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #64748b;
  padding: 12px 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
}

.section-header:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #94a3b8;
}

.section-header.active {
  color: #cbd5e1;
  background: rgba(59, 130, 246, 0.1);
}

.section-header i {
  font-size: 0.65rem;
  transition: transform 0.2s ease;
}

.section-header i.rotated {
  transform: rotate(90deg);
}

/* Section nodes container - collapsible */
.section-nodes {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s ease-out, padding 0.3s ease-out;
  padding: 0 4px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-nodes.expanded {
  max-height: 60vh;
  overflow-y: auto;
  padding: 8px 4px;
}

.node-button {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
  font-weight: 500;
  font-size: 0.9rem;
  color: white;
}

.node-button:hover {
  opacity: 0.85;
  transform: translateX(4px);
}

.node-desc {
  display: none;
  width: 100%;
  font-size: 0.7rem;
  font-weight: 400;
  color: rgba(255, 255, 255, 0.8);
  line-height: 1.3;
}

.node-button:hover .node-desc {
  display: block;
}

.node-icon {
  font-size: 1.2rem;
}

.node-label {
  flex: 1;
}

.add-icon {
  font-size: 0.75rem;
  opacity: 0.7;
}

/* Node type colors */
.node-data {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
}

.node-synthesis {
  background: linear-gradient(135deg, #06b6d4, #0891b2);
}

.node-preprocess {
  background: linear-gradient(135deg, #22c55e, #16a34a);
}

.node-exploratory {
  background: linear-gradient(135deg, #a855f7, #9333ea);
}

.node-regression {
  background: linear-gradient(135deg, #8b5cf6, #7c3aed);
}

.node-classify {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.node-clustering {
  background: linear-gradient(135deg, #ec4899, #db2777);
}

.node-validation {
  background: linear-gradient(135deg, #eab308, #ca8a04);
}

.node-visualize {
  background: linear-gradient(135deg, #f97316, #ea580c);
}

.node-export {
  background: linear-gradient(135deg, #64748b, #475569);
}

.node-plugin {
  background: linear-gradient(135deg, #ec4899, #be185d);
}

.toolbar-help {
  padding: 16px;
  background: rgba(255, 255, 255, 0.03);
  border-top: 1px solid #334155;
}

.toolbar-help h4 {
  margin: 0 0 12px 0;
  font-size: 0.8rem;
  font-weight: 600;
  color: #94a3b8;
  display: flex;
  align-items: center;
  gap: 6px;
}

.toolbar-help h4::before {
  content: '💡';
}

.toolbar-help ol {
  margin: 0;
  padding-left: 18px;
  font-size: 0.8rem;
  color: #64748b;
  line-height: 1.6;
}

.toolbar-help li {
  margin-bottom: 4px;
}
</style>
