<template>
  <div class="workflow-toolbar">
    <div class="toolbar-header">
      <h3>Add Nodes</h3>
    </div>

    <div class="toolbar-content">
      <!-- Data Sources Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'data')">
        <div class="section-header" :class="{ active: activeSection === 'data' }">
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
          </div>
        </div>
      </div>

      <!-- Synthesis Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'synthesis')">
        <div class="section-header" :class="{ active: activeSection === 'synthesis' }">
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
          </div>
        </div>
      </div>

      <!-- Preprocessing Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'preprocess')">
        <div class="section-header" :class="{ active: activeSection === 'preprocess' }">
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
          </div>
        </div>
      </div>

      <!-- Analysis Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'analysis')">
        <div class="section-header" :class="{ active: activeSection === 'analysis' }">
          <span>Analysis</span>
          <i class="pi pi-chevron-right" :class="{ rotated: activeSection === 'analysis' }"></i>
        </div>
        <div class="section-nodes" :class="{ expanded: activeSection === 'analysis' }">
          <div
            v-for="(config, type) in analysisNodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            @click="addNode(type)"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
          </div>
        </div>
      </div>

      <!-- Classification Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'classification')">
        <div class="section-header" :class="{ active: activeSection === 'classification' }">
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
          </div>
        </div>
      </div>

      <!-- Output Section -->
      <div class="section" @mouseenter="!clickCooldown && (activeSection = 'output')">
        <div class="section-header" :class="{ active: activeSection === 'output' }">
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
        <div class="section-header" :class="{ active: activeSection === extra.key }">
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

// Icon mappings by node_type (from backend)
const NODE_ICONS: Record<string, string> = {
  // Data sources
  'data.source': '📊',
  'data.file_load': '📂',
  'data.nist_library': '📚',
  'data.synthetic_curve': '📈',
  'data.train_test_split': '✂️',
  // Synthesis
  'synthesis.species': '🧬',
  'synthesis.blend': '🔀',
  'synthesis.merge': '📚',
  // Preprocessing
  'baseline.als': '📉',
  'baseline.rubberband': '📉',
  'smooth.savitzky_golay': '〰️',
  'normalize.snv': '⚖️',
  'normalize.scale': '📏',
  'normalize.msc': '⚖️',
  'derivative.first': '∂',
  'derivative.second': '∂²',
  'preprocess.cosmic_ray': '✨',
  'preprocess.clip_range': '✂️',
  'preprocess.clip_floor': '⬆️',
  'preprocess.wavenumber_align': '⚙️',
  'preprocess.scale_max': '📏',
  'preprocess.center_mean': '⊖',
  'preprocess.pareto_scaling': '📊',
  'preprocess.osc': '⊥',
  'preprocess.autoscaling': '⚡',
  'preprocess.sg_derivative': '∂⁓',
  'preprocess.emsc': '📐',
  'time_series.moving_window': '🕒',
  'time_series.trend_removal': '📉',
  // Modeling / Analysis
  'model.pca': '🔀',
  'model.pca_transform': '⚙️',
  'model.pls': '📈',
  'model.pls_predict': '🎯',
  'model.linear_regression': '📉',
  'model.mcr_als': '🧩',
  'model.efa': '🔬',
  'model.pcr': '🧮',
  'model.svr': '🧲',
  'model.kmeans': '🧭',
  'model.dbscan': '🫧',
  'model.hca': '🌳',
  'analysis.peak_finding': '⛰️',
  'diagnostics.outliers': '🚨',
  'diagnostics.cross_validation': '🔄',
  'stats.summary': '📊',
  // Classification
  'classification.plsda': '🎯',
  'classification.plsda_predict': '🔮',
  'classification.knn': '👥',
  'classification.knn_predict': '🔍',
  'classification.simca': '🎲',
  // Output
  'output.plot': '📈',
  'output.contour': '🗺️',
  'output.data_table': '📋',
  'output.export': '💾',
};

// Category to color class mapping
const CATEGORY_COLOR: Record<string, string> = {
  data: 'node-data',
  synthesis: 'node-synthesis',
  preprocessing: 'node-preprocess',
  modeling: 'node-model',
  analysis: 'node-analyze',
  classification: 'node-classify',
  output: 'node-visualize',
};

// Category display names
const CATEGORY_LABELS: Record<string, string> = {
  data: 'Data Sources',
  synthesis: 'Synthesis',
  preprocessing: 'Preprocessing',
  modeling: 'Analysis',
  analysis: 'Analysis',
  classification: 'Classification',
  output: 'Output',
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

  // Populate from node library — accept ALL categories, not just built-in
  workflowStore.nodeLibrary.forEach((metadata, nodeType) => {
    const category = metadata.category;
    if (!groups[category]) {
      groups[category] = {};
    }
    const normalizedType = workflowStore.normalizeNodeType(nodeType);
    groups[category][normalizedType] = metadataToConfig(metadata);
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

// Fallback to hardcoded nodes if backend library hasn't loaded yet
// Data Source Nodes (Blue)
const DATA_NODES: Record<string, NodeConfig> = {
  'data.source': { label: 'Data Source', icon: '📊', colorClass: 'node-data', description: 'Load from experiments or files' },
  'data.file_load': { label: 'File Load', icon: '📂', colorClass: 'node-data', description: 'Load from local files' },
  'data.nist_library': { label: 'NIST Library', icon: '📚', colorClass: 'node-data', description: 'Load from NIST spectral library' },
  'data.synthetic_curve': { label: 'Synthetic Curve', icon: '📈', colorClass: 'node-data', description: 'Generate concentration curve' },
  'data.train_test_split': { label: 'Train/Test Split', icon: '✂️', colorClass: 'node-data', description: 'Split data into training and test sets' },
};

// Synthesis/Blend Nodes (Cyan)
const SYNTHESIS_NODES: Record<string, NodeConfig> = {
  'synthesis.species': { label: 'Species', icon: '🧬', colorClass: 'node-synthesis', description: 'Mark spectrum as blend species' },
  'synthesis.blend': { label: 'Blend', icon: '🔀', colorClass: 'node-synthesis', description: 'Blend species into mixture' },
  'synthesis.merge': { label: 'Merge Spectra', icon: '📚', colorClass: 'node-synthesis', description: 'Stack multiple spectra' },
};

// Preprocessing Nodes (Green)
const PREPROCESS_NODES: Record<string, NodeConfig> = {
  'normalize.snv': { label: 'Normalize (SNV)', icon: '⚖️', colorClass: 'node-preprocess', description: 'Standard normal variate normalization' },
  'normalize.scale': { label: 'Scale', icon: '📏', colorClass: 'node-preprocess', description: 'Scale data to range' },
  'normalize.msc': { label: 'MSC', icon: '⚖️', colorClass: 'node-preprocess', description: 'Multiplicative scatter correction' },
  'baseline.als': { label: 'Baseline (ALS)', icon: '📉', colorClass: 'node-preprocess', description: 'Baseline correction via ALS' },
  'baseline.rubberband': { label: 'Baseline (Rubberband)', icon: '📉', colorClass: 'node-preprocess', description: 'Rubberband baseline correction' },
  'smooth.savitzky_golay': { label: 'Smooth (S-G)', icon: '〰️', colorClass: 'node-preprocess', description: 'Savitzky-Golay smoothing' },
  'derivative.first': { label: '1st Derivative', icon: '∂', colorClass: 'node-preprocess', description: 'First derivative (Savitzky-Golay)' },
  'derivative.second': { label: '2nd Derivative', icon: '∂²', colorClass: 'node-preprocess', description: 'Second derivative (Savitzky-Golay)' },
  'preprocess.sg_derivative': { label: 'SG Derivative', icon: '∂⁓', colorClass: 'node-preprocess', description: 'Smooth + derivative combined' },
  'preprocess.cosmic_ray': { label: 'Cosmic Ray', icon: '✨', colorClass: 'node-preprocess', description: 'Remove cosmic ray spikes' },
  'preprocess.clip_range': { label: 'Clip Range', icon: '✂️', colorClass: 'node-preprocess', description: 'Limit wavenumber range' },
  'preprocess.clip_floor': { label: 'Clip Floor', icon: '⬆️', colorClass: 'node-preprocess', description: 'Remove negative values' },
  'preprocess.wavenumber_align': { label: 'WN Align', icon: '⚙️', colorClass: 'node-preprocess', description: 'Align to common grid' },
  'preprocess.scale_max': { label: 'Scale Max', icon: '📏', colorClass: 'node-preprocess', description: 'Scale by max value' },
  'preprocess.center_mean': { label: 'Mean Center', icon: '⊖', colorClass: 'node-preprocess', description: 'Subtract mean spectrum' },
  'preprocess.pareto_scaling': { label: 'Pareto Scale', icon: '📊', colorClass: 'node-preprocess', description: 'Scale by sqrt of std dev' },
  'preprocess.autoscaling': { label: 'Autoscale', icon: '⚡', colorClass: 'node-preprocess', description: 'Mean center + unit variance scaling' },
  'preprocess.osc': { label: 'OSC Filter', icon: '⊥', colorClass: 'node-preprocess', description: 'Orthogonal signal correction' },
  'preprocess.emsc': { label: 'EMSC', icon: '📐', colorClass: 'node-preprocess', description: 'Extended MSC with polynomial baseline' },
  'time_series.moving_window': { label: 'Moving Window', icon: '🕒', colorClass: 'node-preprocess', description: 'Apply moving window smoothing' },
  'time_series.trend_removal': { label: 'Trend Removal', icon: '📉', colorClass: 'node-preprocess', description: 'Remove trends and drift' },
};

// Analysis Nodes (Purple)
const ANALYSIS_NODES: Record<string, NodeConfig> = {
  'model.pca': { label: 'PCA', icon: '🔀', colorClass: 'node-model', description: 'Principal Component Analysis' },
  'model.pca_transform': { label: 'Apply PCA', icon: '⚙️', colorClass: 'node-model', description: 'Transform new data using PCA model' },
  'model.pls': { label: 'PLS', icon: '📈', colorClass: 'node-model', description: 'Partial Least Squares regression' },
  'model.pls_predict': { label: 'Apply PLS', icon: '🎯', colorClass: 'node-model', description: 'Predict using trained PLS model' },
  'model.linear_regression': { label: 'Linear Regression', icon: '📉', colorClass: 'node-model', description: 'Simple linear regression' },
  'model.mcr_als': { label: 'MCR-ALS', icon: '🧩', colorClass: 'node-model', description: 'Multivariate Curve Resolution' },
  'model.efa': { label: 'EFA', icon: '🔬', colorClass: 'node-model', description: 'Evolving Factor Analysis' },
  'model.pcr': { label: 'PCR', icon: '🧮', colorClass: 'node-model', description: 'Principal Component Regression' },
  'model.svr': { label: 'SVR', icon: '🧲', colorClass: 'node-model', description: 'Support Vector Regression' },
  'model.kmeans': { label: 'KMeans', icon: '🧭', colorClass: 'node-model', description: 'K-Means clustering' },
  'model.dbscan': { label: 'DBSCAN', icon: '🫧', colorClass: 'node-model', description: 'Density-based clustering' },
  'model.hca': { label: 'HCA', icon: '🌳', colorClass: 'node-model', description: 'Hierarchical clustering' },
  'analysis.peak_finding': { label: 'Peak Finding', icon: '⛰️', colorClass: 'node-analyze', description: 'Find peaks in spectra' },
  'diagnostics.outliers': { label: 'Outlier Detection', icon: '🚨', colorClass: 'node-analyze', description: 'Detect outliers (Hotelling T², Q)' },
  'diagnostics.cross_validation': { label: 'Cross-Validation', icon: '🔄', colorClass: 'node-analyze', description: 'Calculate CV metrics' },
  'stats.summary': { label: 'Statistics', icon: '📊', colorClass: 'node-analyze', description: 'Compute descriptive statistics' },
};

// Classification Nodes (Orange)
const CLASSIFICATION_NODES: Record<string, NodeConfig> = {
  'classification.plsda': { label: 'PLS-DA', icon: '🎯', colorClass: 'node-classify', description: 'Partial Least Squares Discriminant Analysis' },
  'classification.plsda_predict': { label: 'Apply PLS-DA', icon: '🔮', colorClass: 'node-classify', description: 'Classify using trained PLS-DA model' },
  'classification.knn': { label: 'KNN', icon: '👥', colorClass: 'node-classify', description: 'K-Nearest Neighbors classification' },
  'classification.knn_predict': { label: 'Apply KNN', icon: '🔍', colorClass: 'node-classify', description: 'Classify using trained KNN model' },
  'classification.simca': { label: 'SIMCA', icon: '🎲', colorClass: 'node-classify', description: 'Soft Independent Modeling of Class Analogy' },
};

// Output Nodes (Gray)
const OUTPUT_NODES: Record<string, NodeConfig> = {
  'output.plot': { label: 'Scatter Plot', icon: '📈', colorClass: 'node-visualize', description: 'Create scatter plot visualization' },
  'output.contour': { label: 'Contour Plot', icon: '🗺️', colorClass: 'node-visualize', description: 'Create 2D heatmap/contour visualization' },
  'output.data_table': { label: 'Data Table', icon: '📋', colorClass: 'node-visualize', description: 'Interactive data table with sorting' },
  'output.export': { label: 'Export', icon: '💾', colorClass: 'node-export', description: 'Export data to file' },
};

// Computed properties with dynamic data (fallback to hardcoded if library not loaded)
const dataNodes = computed(() => {
  const dynamic = nodesByCategory.value.data;
  return Object.keys(dynamic).length > 0 ? dynamic : DATA_NODES;
});

const synthesisNodes = computed(() => {
  const dynamic = nodesByCategory.value.synthesis;
  return Object.keys(dynamic).length > 0 ? dynamic : SYNTHESIS_NODES;
});

const preprocessNodes = computed(() => {
  const dynamic = nodesByCategory.value.preprocessing;
  return Object.keys(dynamic).length > 0 ? dynamic : PREPROCESS_NODES;
});

const analysisNodes = computed(() => {
  const dynamic = nodesByCategory.value.modeling;
  const analysis = nodesByCategory.value.analysis;
  // Merge modeling + analysis into analysis section
  const merged = { ...dynamic, ...analysis };
  return Object.keys(merged).length > 0 ? merged : ANALYSIS_NODES;
});

const classificationNodes = computed(() => {
  const dynamic = nodesByCategory.value.classification;
  return Object.keys(dynamic).length > 0 ? dynamic : CLASSIFICATION_NODES;
});

const outputNodes = computed(() => {
  const dynamic = nodesByCategory.value.output;
  return Object.keys(dynamic).length > 0 ? dynamic : OUTPUT_NODES;
});

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
  max-height: 500px;
  padding: 8px 4px;
}

.node-button {
  display: flex;
  align-items: center;
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

.node-model {
  background: linear-gradient(135deg, #a855f7, #9333ea);
}

.node-classify {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}

.node-analyze {
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
