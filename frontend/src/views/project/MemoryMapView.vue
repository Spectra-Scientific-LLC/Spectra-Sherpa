<template>
  <section class="memory-map-content">
    <div class="section-header">
      <div>
        <h1>Memory Map</h1>
        <p class="section-subtitle">
          Sherpa Advisor's memory for this project — every scope you've visited,
          every conversation thread, and every cross-cutting relationship.
        </p>
      </div>
      <div class="header-actions">
        <Button
          icon="pi pi-arrow-left"
          label="Back to Project"
          class="p-button-outlined"
          @click="goBack"
        />
        <Button
          icon="pi pi-refresh"
          class="p-button-text"
          :loading="loading"
          @click="() => reload()"
          v-tooltip.bottom="'Refresh'"
        />
      </div>
    </div>

    <div v-if="!projectId" class="empty-state">
      <i class="pi pi-folder-open"></i>
      <h3>No active project</h3>
      <p>Open a project to see its memory map.</p>
    </div>

    <div v-else-if="loading && !graph" class="loading-state">
      <ProgressSpinner style="width: 40px; height: 40px" />
      <span>Loading memory graph...</span>
    </div>

    <div v-else-if="isLocalUnavailable" class="empty-state">
      <i class="pi pi-sitemap"></i>
      <h3>Memory Map unavailable</h3>
      <p>Memory Map is available when Sherpa Advisor memory is backed by the server.</p>
    </div>

    <div v-else-if="error" class="error-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <span>{{ error }}</span>
    </div>

    <div v-else-if="graph && graph.nodes.length === 0" class="empty-state">
      <i class="pi pi-comments"></i>
      <h3>No memory yet</h3>
      <p>
        Start a Sherpa Advisor conversation in any tab and it will appear here.
        Cross-tab edges build automatically as you navigate between scopes.
      </p>
    </div>

    <template v-else-if="graph">
      <!-- Summary chips -->
      <div class="map-summary">
        <span class="map-chip">
          <i class="pi pi-folder"></i>
          {{ graph.nodes.length }} scope{{ graph.nodes.length === 1 ? '' : 's' }}
        </span>
        <span class="map-chip">
          <i class="pi pi-comments"></i>
          {{ totalTopics }} topic{{ totalTopics === 1 ? '' : 's' }}
        </span>
        <span class="map-chip">
          <i class="pi pi-bookmark"></i>
          {{ totalFacts }} fact{{ totalFacts === 1 ? '' : 's' }}
        </span>
        <span class="map-chip">
          <i class="pi pi-link"></i>
          {{ graph.edges.length }} edge{{ graph.edges.length === 1 ? '' : 's' }}
        </span>
      </div>

      <!-- Grouped-by-tab list view.  A force-directed graph viz can
           swap in here later; the data shape (nodes + edges + badges)
           is already render-ready. -->
      <div
        v-for="group in groupedByTab"
        :key="group.tab"
        class="tab-group"
      >
        <h3 class="tab-group-title">{{ tabLabel(group.tab) }}</h3>
        <div class="node-grid">
          <div
            v-for="node in group.nodes"
            :key="node.id"
            class="node-card"
            :class="{ 'has-stale': node.badges.stale_descendant_count > 0 }"
          >
            <div class="node-card-header">
              <span class="node-title">{{ node.title || formatSubscope(node.subscope_key) }}</span>
              <span class="node-subscope">{{ node.subscope_key }}</span>
            </div>
            <div class="node-badges">
              <span class="node-badge" :title="`${node.badges.topic_count} topic${node.badges.topic_count === 1 ? '' : 's'}`">
                <i class="pi pi-comments"></i> {{ node.badges.topic_count }}
              </span>
              <span class="node-badge" :title="`${node.badges.fact_count} fact${node.badges.fact_count === 1 ? '' : 's'}`">
                <i class="pi pi-bookmark"></i> {{ node.badges.fact_count }}
              </span>
              <span
                v-if="node.badges.last_compaction_at"
                class="node-badge node-badge-muted"
                :title="`Last compaction: ${formatTimestamp(node.badges.last_compaction_at)}`"
              >
                <i class="pi pi-clock"></i> {{ formatRelative(node.badges.last_compaction_at) }}
              </span>
              <span
                v-if="node.badges.stale_descendant_count > 0"
                class="node-badge node-badge-warn"
                :title="`${node.badges.stale_descendant_count} descendant scope${node.badges.stale_descendant_count === 1 ? '' : 's'} pending refresh`"
              >
                <i class="pi pi-exclamation-circle"></i> {{ node.badges.stale_descendant_count }} stale
              </span>
            </div>
            <div v-if="incomingEdgesByTarget[node.id]?.length" class="node-edges">
              <span class="edges-label">Influenced by:</span>
              <span
                v-for="edge in incomingEdgesByTarget[node.id]"
                :key="edge.id"
                class="edge-chip"
              >
                {{ nodeLabelById(edge.source_node_id) }}
                <span class="edge-weight">w{{ edge.weight.toFixed(1) }}</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";

import { useAppConfig } from "@/composables/useAppConfig";
import {
  getAdvisorMemoryAdapter,
  type MemoryMapData,
  type MemoryMapNode,
} from "@/lib/advisorMemoryAdapter";
import { useProjectStore } from "@/stores/project";
import { getErrorMessage } from "@/utils/errors";

const router = useRouter();
const projectStore = useProjectStore();
const { appMode } = useAppConfig();

const isServerBacked = computed(() => appMode.value !== "local");
const projectId = computed(() => projectStore.currentProjectId);

const graph = ref<MemoryMapData | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);
const isLocalUnavailable = ref(false);

// Tab display labels.  Order mirrors TAB_INHERITANCE_ORDER on the server.
const TAB_DISPLAY: Record<string, string> = {
  project: "Project",
  data: "Data",
  experiments: "Experiments",
  workflow: "Workflow",
  deploy: "Deploy",
  report: "Report",
};
const TAB_ORDER = ["project", "data", "experiments", "workflow", "deploy", "report"];

const groupedByTab = computed(() => {
  if (!graph.value) return [];
  const buckets = new Map<string, MemoryMapNode[]>();
  for (const node of graph.value.nodes) {
    const bucket = buckets.get(node.tab_key) ?? [];
    bucket.push(node);
    buckets.set(node.tab_key, bucket);
  }
  return TAB_ORDER.filter((tab) => buckets.has(tab)).map((tab) => ({
    tab,
    nodes: buckets.get(tab)!.sort((a, b) => a.subscope_key.localeCompare(b.subscope_key)),
  }));
});

const totalTopics = computed(() =>
  (graph.value?.nodes ?? []).reduce((sum, n) => sum + n.badges.topic_count, 0),
);
const totalFacts = computed(() =>
  (graph.value?.nodes ?? []).reduce((sum, n) => sum + n.badges.fact_count, 0),
);

const incomingEdgesByTarget = computed(() => {
  const map: Record<number, MemoryMapData["edges"]> = {};
  for (const edge of graph.value?.edges ?? []) {
    const list = map[edge.target_node_id] ?? [];
    list.push(edge);
    map[edge.target_node_id] = list;
  }
  // Sort within each bucket by weight descending so the most relevant
  // ancestor surfaces first.
  for (const list of Object.values(map)) list.sort((a, b) => b.weight - a.weight);
  return map;
});

function nodeLabelById(nodeId: number): string {
  const node = graph.value?.nodes.find((n) => n.id === nodeId);
  if (!node) return `#${nodeId}`;
  const tab = TAB_DISPLAY[node.tab_key] ?? node.tab_key;
  return `${tab} · ${node.title || formatSubscope(node.subscope_key)}`;
}

function tabLabel(tab: string): string {
  return TAB_DISPLAY[tab] ?? tab;
}

function formatSubscope(key: string): string {
  if (key.startsWith("sheet:")) return `Sheet ${key.slice(6)}`;
  if (key.startsWith("trial:")) return "Trial";
  return key.charAt(0).toUpperCase() + key.slice(1);
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatRelative(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const ms = now - then;
    if (ms < 60_000) return "just now";
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`;
    if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`;
    return `${Math.floor(ms / 86_400_000)}d ago`;
  } catch {
    return iso;
  }
}

async function reload(projectIdOverride: number | null = null): Promise<void> {
  const id = projectIdOverride ?? projectId.value;
  if (id === null) return;
  loading.value = true;
  error.value = null;
  isLocalUnavailable.value = false;
  try {
    const adapter = getAdvisorMemoryAdapter(isServerBacked.value);
    const data = await adapter.getMemoryMap(id);
    graph.value = data;
    if (data === null) {
      // Local mode — Memory Map is unavailable.  This is an expected
      // deployment boundary, not a failed request.
      isLocalUnavailable.value = true;
    }
  } catch (err) {
    error.value = getErrorMessage(err, "Failed to load memory map");
  } finally {
    loading.value = false;
  }
}

function goBack(): void {
  router.push("/project");
}

onMounted(() => {
  void (async () => {
    const project = await projectStore.ensureProjectForBrowserTab();
    await reload(projectStore.currentProjectId ?? project?.id ?? null);
  })();
});
</script>

<style scoped>
.memory-map-content {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 24px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--surface-border, #e5e7eb);
}

.section-header h1 {
  margin: 0 0 4px;
}

.section-subtitle {
  margin: 0;
  color: var(--text-color-secondary, #667085);
  font-size: 0.9rem;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.empty-state,
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 64px 16px;
  text-align: center;
  color: var(--text-color-secondary, #667085);
}

.empty-state i,
.loading-state i {
  font-size: 2.5rem;
  margin-bottom: 12px;
  color: var(--text-color-secondary, #b0b6bf);
}

.empty-state h3 {
  margin: 0 0 8px;
}

.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: var(--red-50, #fef2f2);
  border: 1px solid var(--red-200, #fecaca);
  color: var(--red-900, #7f1d1d);
  border-radius: 6px;
  margin-bottom: 16px;
}

.map-summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 24px;
}

.map-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--surface-100, #f3f4f6);
  border: 1px solid var(--surface-200, #e5e7eb);
  border-radius: 16px;
  font-size: 0.85rem;
  color: var(--text-color, #1f2937);
}

.tab-group {
  margin-bottom: 32px;
}

.tab-group-title {
  margin: 0 0 12px;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--primary-color, #3b82f6);
  border-left: 3px solid var(--primary-color, #3b82f6);
  padding-left: 10px;
}

.node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.node-card {
  padding: 14px;
  background: var(--surface-0, #ffffff);
  border: 1px solid var(--surface-border, #e5e7eb);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.node-card.has-stale {
  border-color: var(--orange-300, #fdba74);
}

.node-card-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}

.node-title {
  font-weight: 600;
  color: var(--text-color, #1f2937);
}

.node-subscope {
  font-family: var(--font-family-mono, ui-monospace, monospace);
  font-size: 0.75rem;
  color: var(--text-color-secondary, #667085);
}

.node-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.node-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--surface-100, #f3f4f6);
  border-radius: 10px;
  font-size: 0.75rem;
  color: var(--text-color, #374151);
}

.node-badge-muted {
  color: var(--text-color-secondary, #667085);
}

.node-badge-warn {
  background: var(--orange-100, #ffedd5);
  color: var(--orange-900, #7c2d12);
}

.node-edges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--surface-200, #e5e7eb);
  font-size: 0.78rem;
  color: var(--text-color-secondary, #667085);
}

.edges-label {
  font-weight: 500;
}

.edge-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 8px;
  background: var(--blue-50, #eff6ff);
  border: 1px solid var(--blue-200, #bfdbfe);
  border-radius: 10px;
  color: var(--blue-900, #1e3a8a);
}

.edge-weight {
  font-size: 0.7rem;
  color: var(--blue-700, #1d4ed8);
  opacity: 0.75;
}
</style>
