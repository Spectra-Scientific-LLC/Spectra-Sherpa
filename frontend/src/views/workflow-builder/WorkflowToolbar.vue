<template>
  <div class="workflow-toolbar" :class="{ collapsed: isCollapsed }">
    <div class="toolbar-header">
      <h3 v-if="!isCollapsed">Add Nodes</h3>
      <button
        type="button"
        class="collapse-toggle"
        :aria-label="isCollapsed ? 'Expand toolbar' : 'Collapse toolbar'"
        :title="isCollapsed ? 'Expand' : 'Collapse'"
        data-testid="toolbar-collapse-toggle"
        @click="toggleCollapsed"
      >
        <i class="pi" :class="isCollapsed ? 'pi-chevron-right' : 'pi-chevron-left'"></i>
      </button>
    </div>

    <div v-if="!isCollapsed" class="toolbar-content">
      <!-- Search category - always first, auto-focused on mount -->
      <div class="section section-search" data-testid="section-search">
        <div class="section-header static">
          <span>Search</span>
          <i class="pi pi-search"></i>
        </div>
        <div class="search-box">
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            class="search-input"
            placeholder="Filter nodes by name…"
            aria-label="Search nodes"
            data-testid="toolbar-search-input"
          />
          <button
            v-if="searchQuery"
            type="button"
            class="search-clear"
            aria-label="Clear search"
            data-testid="toolbar-search-clear"
            @click="searchQuery = ''"
          >
            <i class="pi pi-times"></i>
          </button>
        </div>
        <div
          v-if="searchQuery.trim()"
          class="section-nodes expanded search-results"
          data-testid="toolbar-search-results"
        >
          <template v-if="searchResults.length > 0">
            <div
              v-for="hit in searchResults"
              :key="hit.type"
              class="node-button"
              :class="hit.config.colorClass"
              :data-testid="`node-button-${hit.type}`"
              @click="addNode(hit.type)"
              @mouseenter="onNodeHover($event, hit.config)"
              @mouseleave="onNodeLeave"
            >
              <span class="node-icon">{{ hit.config.icon }}</span>
              <span class="node-label">{{ hit.config.label }}</span>
              <i class="pi pi-plus add-icon"></i>
            </div>
          </template>
          <div v-else class="search-empty" data-testid="toolbar-search-empty">
            No nodes match "{{ searchQuery }}"
          </div>
        </div>
      </div>

      <!-- Categories rendered via v-for -->
      <div
        v-for="category in allCategories"
        :key="category.key"
        class="section"
        :data-testid="`section-${category.key}`"
      >
        <div
          class="section-header"
          :class="{ active: isOpen(category.key) }"
          :data-testid="`section-header-${category.key}`"
          @click="toggleSection(category.key)"
        >
          <span>{{ category.label }}</span>
          <i class="pi pi-chevron-right" :class="{ rotated: isOpen(category.key) }"></i>
        </div>
        <div
          class="section-nodes"
          :class="{ expanded: isOpen(category.key) }"
          :data-testid="`section-nodes-${category.key}`"
        >
          <div
            v-for="(config, type) in category.nodes"
            :key="type"
            class="node-button"
            :class="config.colorClass"
            :data-testid="`node-button-${type}`"
            @click="addNode(String(type))"
            @mouseenter="onNodeHover($event, config)"
            @mouseleave="onNodeLeave"
          >
            <span class="node-icon">{{ config.icon }}</span>
            <span class="node-label">{{ config.label }}</span>
            <i class="pi pi-plus add-icon"></i>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!isCollapsed" class="toolbar-help">
      <h4>How to use</h4>
      <ol>
        <li>Add nodes from above</li>
        <li>Click "Connect" on a node</li>
        <li>Click destination node</li>
        <li>Adjust parameters on right</li>
        <li>Click "Execute Workflow"</li>
      </ol>
    </div>

    <!--
      Floating hover tooltip. Uses position: fixed (via inline style) so it
      escapes the scrollable toolbar and can overlay the main workflow canvas.
      Expert users ignore it and search by name; new users hover to read the
      full description without truncation.
    -->
    <div
      v-if="hoveredNode"
      class="node-tooltip"
      data-testid="node-hover-tooltip"
      :style="{ left: `${hoveredNode.x}px`, top: `${hoveredNode.y}px` }"
      role="tooltip"
    >
      <div class="node-tooltip-title">{{ hoveredNode.label }}</div>
      <div v-if="hoveredNode.description" class="node-tooltip-body">
        {{ hoveredNode.description }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue';
import { useWorkflowStore } from '@/stores/workflow';
import type { NodeTypeMetadata } from '@/types';

interface NodeConfig {
  label: string;
  icon: string;
  colorClass: string;
  description: string;
}

interface CategoryGroup {
  key: string;
  label: string;
  nodes: Record<string, NodeConfig>;
}

interface SearchHit {
  type: string;
  config: NodeConfig;
  score: number;
}

const emit = defineEmits<{
  (e: 'add-node', nodeType: string): void;
  (e: 'toggle-collapsed', collapsed: boolean): void;
}>();

const workflowStore = useWorkflowStore();

const COLLAPSED_STORAGE_KEY = 'workflow-toolbar-collapsed';

// Multi-open categories: a Set of category keys that are currently expanded.
const openSections = ref<Set<string>>(new Set());

// Live search query - filters nodes across all categories as the user types.
const searchQuery = ref<string>('');

// Whole-toolbar collapse state (persisted in localStorage).
const isCollapsed = ref<boolean>(false);

const searchInputRef = ref<HTMLInputElement | null>(null);

// Floating hover tooltip state: the currently hovered node and the screen
// coordinates at which to render the tooltip. Cleared on mouseleave.
interface HoverTooltipState {
  label: string;
  description: string;
  x: number;
  y: number;
}
const hoveredNode = ref<HoverTooltipState | null>(null);

// Horizontal gap (px) between the hovered button and the tooltip.
const TOOLTIP_GAP_PX = 12;
// Max tooltip width (must match the CSS rule below) — used for edge-clamping.
const TOOLTIP_MAX_WIDTH_PX = 320;

// Restore persisted collapsed state before mount so the initial render matches.
try {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(COLLAPSED_STORAGE_KEY) : null;
  if (stored === '1') {
    isCollapsed.value = true;
  }
} catch {
  // localStorage may be unavailable (private mode, tests) — fall back to expanded.
}

onMounted(async () => {
  if (workflowStore.nodeLibrary.size === 0) {
    await workflowStore.fetchNodeLibrary();
  }
  // Auto-focus the search input when the toolbar mounts expanded.
  if (!isCollapsed.value) {
    await nextTick();
    searchInputRef.value?.focus();
  }
  // Broadcast the initial state so the parent layout can size the grid column.
  emit('toggle-collapsed', isCollapsed.value);
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
  'transfer.pds': '🔄',
  'transfer.sbc': '📐',
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
  // Selection & Design
  'selection.sample_partition': '🎯',
  'selection.variable_select': '🔬',
  'selection.ipls': '📊',
  'selection.cars': '🏎️',
  'selection.spa': '📐',
  'selection.uve': '🧹',
  'selection.stability': '🔒',
  'selection.nested_cv': '🔄',
  'selection.audit': '📋',
  'selection.compare': '⚖️',
  // Deploy
  'deploy.input': '📥',
  'deploy.output': '📤',
};

// Category to color class mapping
const CATEGORY_COLOR: Record<string, string> = {
  data: 'node-data',
  synthesis: 'node-synthesis',
  preprocessing: 'node-preprocess',
  selection: 'node-selection',
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
  data: 'Data Sources',
  synthesis: 'Synthesis',
  preprocessing: 'Preprocessing',
  selection: 'Selection & Design',
  exploratory: 'Exploratory',
  regression: 'Regression',
  classification: 'Classification',
  clustering: 'Clustering',
  validation: 'Validation',
  output: 'Output',
  deploy: 'Deployment',
};

// Ordered list of built-in category keys — drives v-for render order.
const BUILTIN_CATEGORY_ORDER: string[] = [
  'data',
  'synthesis',
  'preprocessing',
  'selection',
  'exploratory',
  'regression',
  'classification',
  'clustering',
  'validation',
  'output',
  'deploy',
];

/**
 * Normalize whitespace on a node description and return the full text.
 * The floating tooltip is the only consumer now, so long, detailed
 * descriptions render completely — users move their cursor down the
 * category list to read each one in turn.
 */
const summarizePurpose = (description: string): string => {
  return description.replace(/\s+/g, ' ').trim();
};

// Convert backend metadata to NodeConfig
const metadataToConfig = (metadata: NodeTypeMetadata): NodeConfig => {
  const baseColor = CATEGORY_COLOR[metadata.category] || 'node-plugin';
  const colorClass = metadata.node_type === 'output.export' ? 'node-export' : baseColor;
  return {
    label: metadata.label,
    icon: NODE_ICONS[metadata.node_type] || '📦',
    colorClass,
    description: summarizePurpose(metadata.description),
  };
};

// Built-in category keys handled by the canonical template sections
const BUILTIN_CATEGORIES = new Set(BUILTIN_CATEGORY_ORDER);

// Dynamically group nodes by category from backend
const nodesByCategory = computed(() => {
  const groups: Record<string, Record<string, NodeConfig>> = {};

  for (const category of BUILTIN_CATEGORIES) {
    groups[category] = {};
  }

  workflowStore.nodeLibrary.forEach((metadata) => {
    const category = metadata.category;
    if (!groups[category]) {
      groups[category] = {};
    }
    groups[category][metadata.node_type] = metadataToConfig(metadata);
  });

  return groups;
});

// Extra categories from backend that aren't covered by the built-in list.
const extraCategories = computed<CategoryGroup[]>(() => {
  const extras: CategoryGroup[] = [];
  for (const [category, nodes] of Object.entries(nodesByCategory.value)) {
    if (!BUILTIN_CATEGORIES.has(category) && Object.keys(nodes).length > 0) {
      const label = category
        .replace(/_/g, ' ')
        .replace(/\b\w/g, (c) => c.toUpperCase());
      extras.push({ key: category, label, nodes });
    }
  }
  return extras;
});

// Full ordered list of categories shown in the toolbar (built-in first, extras last).
const allCategories = computed<CategoryGroup[]>(() => {
  const builtin: CategoryGroup[] = BUILTIN_CATEGORY_ORDER.map((key) => ({
    key,
    label: CATEGORY_LABELS[key],
    nodes: nodesByCategory.value[key] || {},
  }));
  return [...builtin, ...extraCategories.value];
});

/**
 * Case-insensitive fuzzy search across node labels and node_type identifiers.
 * Returns a ranked list of at most 20 hits. Ranking preference:
 *   1) label starts with query     (score 0)
 *   2) label contains query        (score 10)
 *   3) node_type contains query    (score 20)
 * Ties broken by label length, then alphabetically.
 */
const searchResults = computed<SearchHit[]>(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return [];

  const hits: SearchHit[] = [];
  const seen = new Set<string>();

  for (const category of allCategories.value) {
    for (const [type, config] of Object.entries(category.nodes)) {
      if (seen.has(type)) continue;
      const label = config.label.toLowerCase();
      const typeLower = type.toLowerCase();

      let score: number | null = null;
      if (label.startsWith(q)) {
        score = 0;
      } else if (label.includes(q)) {
        score = 10;
      } else if (typeLower.includes(q)) {
        score = 20;
      }

      if (score !== null) {
        seen.add(type);
        hits.push({ type, config, score: score + config.label.length });
      }
    }
  }

  hits.sort((a, b) => a.score - b.score || a.config.label.localeCompare(b.config.label));
  return hits.slice(0, 20);
});

const isOpen = (key: string): boolean => openSections.value.has(key);

const toggleSection = (section: string) => {
  // Use a fresh Set so reactivity triggers (Vue doesn't deep-track Set mutations).
  const next = new Set(openSections.value);
  if (next.has(section)) {
    next.delete(section);
  } else {
    next.add(section);
  }
  openSections.value = next;
};

const addNode = (nodeType: string) => {
  emit('add-node', nodeType);
  // Clear search after a successful add so the panel returns to category view.
  searchQuery.value = '';
  // Dismiss any floating tooltip that was showing for this button.
  hoveredNode.value = null;
};

/**
 * Show the floating tooltip anchored to the right edge of the hovered button.
 * If the button's right edge plus tooltip width overflows the viewport, the
 * tooltip flips to the left side of the button instead.
 */
const onNodeHover = (event: MouseEvent, config: NodeConfig) => {
  const target = event.currentTarget as HTMLElement | null;
  if (!target) return;
  const rect = target.getBoundingClientRect();
  const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1024;

  let x = rect.right + TOOLTIP_GAP_PX;
  if (x + TOOLTIP_MAX_WIDTH_PX > viewportWidth) {
    // Not enough room on the right — anchor to the left of the button.
    x = Math.max(8, rect.left - TOOLTIP_MAX_WIDTH_PX - TOOLTIP_GAP_PX);
  }

  hoveredNode.value = {
    label: config.label,
    description: config.description,
    x,
    y: rect.top,
  };
};

const onNodeLeave = () => {
  hoveredNode.value = null;
};

const toggleCollapsed = async () => {
  isCollapsed.value = !isCollapsed.value;
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(COLLAPSED_STORAGE_KEY, isCollapsed.value ? '1' : '0');
    }
  } catch {
    // Ignore storage failures — state still lives in memory for the session.
  }
  emit('toggle-collapsed', isCollapsed.value);
  if (!isCollapsed.value) {
    await nextTick();
    searchInputRef.value?.focus();
  }
};

defineExpose({ summarizePurpose });
</script>

<style scoped>
.workflow-toolbar {
  background: #1e293b;
  border-radius: 8px;
  border: 1px solid #334155;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: background 0.2s ease;
}

.workflow-toolbar.collapsed {
  /* When collapsed, the toolbar shrinks to just the chevron column. */
  align-items: center;
}

.toolbar-header {
  padding: 16px;
  border-bottom: 1px solid #334155;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
}

.workflow-toolbar.collapsed .toolbar-header {
  padding: 12px 6px;
  border-bottom: none;
  justify-content: center;
}

.toolbar-header h3 {
  margin: 0;
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #94a3b8;
}

.collapse-toggle {
  background: transparent;
  border: 1px solid #334155;
  border-radius: 4px;
  color: #94a3b8;
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.15s ease;
  padding: 0;
}

.collapse-toggle:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
  border-color: #475569;
}

.collapse-toggle i {
  font-size: 0.7rem;
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

.section-header.static {
  cursor: default;
  color: #94a3b8;
}

.section-header.static:hover {
  background: rgba(255, 255, 255, 0.03);
  color: #94a3b8;
}

.section-header i {
  font-size: 0.65rem;
  transition: transform 0.2s ease;
}

.section-header i.rotated {
  transform: rotate(90deg);
}

/* Search box */
.search-box {
  position: relative;
  display: flex;
  align-items: center;
  margin: 6px 4px 4px 4px;
}

.search-input {
  width: 100%;
  padding: 8px 28px 8px 10px;
  border-radius: 6px;
  border: 1px solid #334155;
  background: rgba(15, 23, 42, 0.6);
  color: #e2e8f0;
  font-size: 0.85rem;
  font-family: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
  box-sizing: border-box;
}

.search-input::placeholder {
  color: #64748b;
}

.search-input:focus {
  outline: none;
  border-color: #3b82f6;
  background: rgba(15, 23, 42, 0.9);
}

.search-clear {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: #64748b;
  cursor: pointer;
  padding: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
}

.search-clear:hover {
  color: #e2e8f0;
  background: rgba(255, 255, 255, 0.08);
}

.search-clear i {
  font-size: 0.65rem;
}

.search-results {
  margin-top: 4px;
}

.search-empty {
  padding: 10px 12px;
  font-size: 0.78rem;
  color: #64748b;
  font-style: italic;
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

/*
 * Floating hover tooltip. Uses position: fixed so it escapes the scrollable
 * toolbar and overlays the workflow canvas to the right. Coordinates are
 * supplied inline from onNodeHover(); this rule owns the look-and-feel only.
 */
.node-tooltip {
  position: fixed;
  z-index: 1000;
  max-width: 320px;
  padding: 10px 12px;
  background: #0f172a;
  color: #e2e8f0;
  border: 1px solid #334155;
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  font-size: 0.78rem;
  line-height: 1.4;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.node-tooltip-title {
  font-weight: 600;
  font-size: 0.82rem;
  color: #f8fafc;
}

.node-tooltip-body {
  font-weight: 400;
  color: #cbd5e1;
  white-space: normal;
  word-wrap: break-word;
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

.node-selection {
  background: linear-gradient(135deg, #14b8a6, #0d9488);
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
