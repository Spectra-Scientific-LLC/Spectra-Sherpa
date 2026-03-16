<template>
  <section class="page-content">
    <div class="section-header">
      <div>
        <h1>Experiments</h1>
        <p class="section-subtitle">
          Save execution runs, compare parameters and metrics side-by-side
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="Save Current Run"
          icon="pi pi-bookmark"
          class="p-button-sm"
          :disabled="!canSaveRun"
          @click="showSaveDialog = true"
        />
        <Button
          label="Compare Selected"
          icon="pi pi-chart-bar"
          class="p-button-sm p-button-outlined"
          :disabled="runsStore.selectedCount < 2"
          :badge="runsStore.selectedCount > 0 ? String(runsStore.selectedCount) : undefined"
          @click="handleCompare"
        />
        <Button
          icon="pi pi-refresh"
          class="p-button-sm p-button-text"
          :loading="runsStore.runsLoading"
          title="Refresh runs"
          @click="refreshRuns"
        />
      </div>
    </div>

    <TabView v-model:activeIndex="activeTab">
      <!-- ======================== RUN HISTORY TAB ======================== -->
      <TabPanel header="Run History">
        <div v-if="runsStore.runsLoading && runsStore.runs.length === 0" class="loading-state">
          <ProgressSpinner style="width: 32px; height: 32px" />
          <span>Loading runs...</span>
        </div>

        <div v-else-if="runsStore.runs.length === 0" class="empty-state">
          <i class="pi pi-bookmark"></i>
          <h3>No saved runs yet</h3>
          <p>
            Execute a workflow, then click "Save Current Run" to begin
            tracking your experiments.
          </p>
        </div>

        <DataTable
          v-else
          :value="runsStore.runs"
          v-model:selection="selectedRows"
          dataKey="id"
          stripedRows
          size="small"
          :loading="runsStore.runsLoading"
          sortField="executed_at"
          :sortOrder="-1"
          class="runs-table"
        >
          <Column selectionMode="multiple" headerStyle="width: 3rem" />

          <Column field="name" header="Name" sortable style="min-width: 180px">
            <template #body="{ data }">
              <div class="run-name-cell">
                <span class="run-name">{{ data.name }}</span>
                <span v-if="data.notes" class="run-notes-hint" :title="data.notes">
                  <i class="pi pi-comment"></i>
                </span>
              </div>
            </template>
          </Column>

          <Column field="status" header="Status" sortable style="width: 100px">
            <template #body="{ data }">
              <Tag
                :severity="statusSeverity(data.status)"
                :value="data.status"
                class="status-tag"
              />
            </template>
          </Column>

          <Column field="executed_at" header="Executed" sortable style="width: 150px">
            <template #body="{ data }">
              <span class="timestamp" :title="data.executed_at">
                {{ formatRelativeTime(data.executed_at) }}
              </span>
            </template>
          </Column>

          <Column header="Labels" style="width: 180px">
            <template #body="{ data }">
              <LabelChips
                :modelValue="data.labels || []"
                @update:model-value="(labels: string[]) => handleUpdateLabels(data.id, labels)"
              />
            </template>
          </Column>

          <Column header="Source" style="width: 80px">
            <template #body="{ data }">
              <Tag
                v-if="data.source_type && data.source_type !== 'manual'"
                :value="data.source_type"
                severity="secondary"
                class="source-tag"
              />
            </template>
          </Column>

          <Column header="Metrics" style="min-width: 200px">
            <template #body="{ data }">
              <span class="metrics-preview">
                {{ formatMetricsPreview(data.results_summary) }}
              </span>
            </template>
          </Column>

          <Column style="width: 60px">
            <template #body="{ data }">
              <Button
                icon="pi pi-trash"
                class="p-button-text p-button-sm p-button-danger"
                title="Delete run"
                @click="confirmDelete(data)"
              />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <!-- ======================== BATCH RUN TAB ======================== -->
      <TabPanel header="Batch Run">
        <BatchRunTab />
      </TabPanel>

      <!-- ======================== COMPARE TAB ======================== -->
      <TabPanel header="Compare">
        <div v-if="runsStore.comparisonLoading" class="loading-state">
          <ProgressSpinner style="width: 32px; height: 32px" />
          <span>Loading comparison...</span>
        </div>

        <ComparisonPanel
          v-else-if="runsStore.comparison"
          :runs="runsStore.comparison.runs"
          :metric-keys="runsStore.comparison.metric_keys"
          :diff="runsStore.comparison.diff"
          @back="activeTab = 0"
        />

        <div v-else class="empty-state">
          <i class="pi pi-chart-bar"></i>
          <h3>No comparison active</h3>
          <p>
            Select 2 or more runs from the History tab and click "Compare Selected".
          </p>
        </div>
      </TabPanel>
    </TabView>

    <!-- Save Run Dialog -->
    <Dialog
      v-model:visible="showSaveDialog"
      header="Save Execution Run"
      :modal="true"
      :style="{ width: '450px' }"
    >
      <div class="save-form">
        <div class="form-field">
          <label for="run-name">Run Name</label>
          <InputText
            id="run-name"
            v-model="saveRunName"
            placeholder="e.g. Baseline - SNV + 3 comp"
            class="w-full"
          />
        </div>
        <div class="form-field">
          <label for="run-notes">Notes (optional)</label>
          <Textarea
            id="run-notes"
            v-model="saveRunNotes"
            rows="3"
            placeholder="Describe what you changed or why this run matters..."
            class="w-full"
          />
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showSaveDialog = false"
        />
        <Button
          label="Save Run"
          icon="pi pi-check"
          :loading="saving"
          :disabled="!saveRunName.trim()"
          @click="handleSaveRun"
        />
      </template>
    </Dialog>

    <!-- Delete Confirmation -->
    <Dialog
      v-model:visible="showDeleteDialog"
      header="Delete Run"
      :modal="true"
      :style="{ width: '400px' }"
    >
      <p>
        Are you sure you want to delete
        <strong>{{ deleteTarget?.name }}</strong>? This cannot be undone.
      </p>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showDeleteDialog = false"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          class="p-button-danger"
          :loading="deleting"
          @click="handleDelete"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- experiment comparison payloads include flexible metric/result snapshots. */
import { ref, computed, onMounted, watch } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Textarea from "primevue/textarea";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";

import ComparisonPanel from "./ComparisonPanel.vue";
import BatchRunTab from "./BatchRunTab.vue";
import LabelChips from "@/components/LabelChips.vue";
import { useRunsStore } from "@/stores/runs";
import { useWorkflowStore } from "@/stores/workflow";
import type { ExecutionRunSummary } from "@/types";

const toast = useToast();
const runsStore = useRunsStore();
const workflowStore = useWorkflowStore();

const activeTab = ref(0);
const showSaveDialog = ref(false);
const saveRunName = ref("");
const saveRunNotes = ref("");
const saving = ref(false);

const showDeleteDialog = ref(false);
const deleteTarget = ref<ExecutionRunSummary | null>(null);
const deleting = ref(false);

// Selection binding for DataTable
const selectedRows = computed({
  get: () => runsStore.runs.filter((r) => runsStore.selectedRunIds.has(r.id)),
  set: (rows: ExecutionRunSummary[]) => {
    runsStore.selectedRunIds = new Set(rows.map((r) => r.id));
  },
});

const canSaveRun = computed(
  () => workflowStore.workflowId && workflowStore.lastExecutionResults
);

// Auto-suggest run name
watch(showSaveDialog, (visible) => {
  if (visible) {
    const base = workflowStore.workflowName || "Workflow";
    const count = runsStore.runs.length + 1;
    saveRunName.value = `${base} - Run ${count}`;
    saveRunNotes.value = "";
  }
});

// Load runs when the workflow changes
onMounted(() => {
  if (workflowStore.workflowId) {
    runsStore.fetchRuns(workflowStore.workflowId);
  }
});

watch(
  () => workflowStore.workflowId,
  (newId) => {
    if (newId) {
      runsStore.fetchRuns(newId);
      runsStore.clearSelection();
    }
  }
);

function refreshRuns() {
  if (workflowStore.workflowId) {
    runsStore.fetchRuns(workflowStore.workflowId);
  }
}

async function handleSaveRun() {
  if (!workflowStore.workflowId || !workflowStore.lastExecutionResults) return;

  saving.value = true;
  try {
    const results = workflowStore.lastExecutionResults as Record<string, unknown>;
    const diagnostics = workflowStore.lastExecutionDiagnostics as Record<string, Record<string, unknown>>;

    // Build node_statuses from node execution states (use backend node IDs
    // for consistency with results_summary and params_snapshot keys)
    const nodeStatuses: Record<string, string> = {};
    for (const node of workflowStore.nodes) {
      const state = workflowStore.getNodeExecutionState(node.id);
      if (state) {
        nodeStatuses[node.id] = state.status;
      }
    }

    // Determine overall status
    const hasError = Object.values(nodeStatuses).some((s) => s === "error");
    const allCompleted = Object.values(nodeStatuses).every((s) => s === "completed");
    const status = hasError ? "error" : allCompleted ? "completed" : "partial";

    await runsStore.saveRun(workflowStore.workflowId, {
      name: saveRunName.value.trim(),
      notes: saveRunNotes.value.trim() || undefined,
      status,
      results_summary: extractMetrics(results),
      diagnostics: Object.keys(diagnostics).length > 0 ? diagnostics : undefined,
      node_statuses: nodeStatuses,
      integrity_hash: workflowStore.workflowHash || undefined,
      executed_at: new Date().toISOString(),
    });

    showSaveDialog.value = false;
    toast.add({
      severity: "success",
      summary: "Run Saved",
      detail: `"${saveRunName.value}" saved to experiment history`,
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Save Failed",
      detail: error?.message || "Could not save run",
      life: 5000,
    });
  } finally {
    saving.value = false;
  }
}

async function handleCompare() {
  if (!workflowStore.workflowId || runsStore.selectedCount < 2) return;
  try {
    await runsStore.compareRuns(
      workflowStore.workflowId,
      [...runsStore.selectedRunIds]
    );
    activeTab.value = 2;
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Compare Failed",
      detail: error?.message || "Could not compare runs",
      life: 5000,
    });
  }
}

async function handleUpdateLabels(runId: number, labels: string[]) {
  try {
    await runsStore.updateLabels(runId, labels);
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Update Failed",
      detail: error?.message || "Could not update labels",
      life: 3000,
    });
  }
}

function confirmDelete(run: ExecutionRunSummary) {
  deleteTarget.value = run;
  showDeleteDialog.value = true;
}

async function handleDelete() {
  if (!workflowStore.workflowId || !deleteTarget.value) return;
  deleting.value = true;
  try {
    await runsStore.deleteRun(workflowStore.workflowId, deleteTarget.value.id);
    showDeleteDialog.value = false;
    toast.add({
      severity: "info",
      summary: "Run Deleted",
      life: 2000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: error?.message || "Could not delete run",
      life: 5000,
    });
  } finally {
    deleting.value = false;
  }
}

// --- Helpers ---

const METRIC_KEYS = [
  "r2", "rmsecv", "rmse", "mse", "accuracy", "n_components",
  "n_samples", "n_features", "explained_variance", "n_clusters",
  "inertia", "silhouette_score",
];

function extractMetrics(
  results: Record<string, unknown>
): Record<string, Record<string, unknown>> {
  const summary: Record<string, Record<string, unknown>> = {};
  for (const [nodeId, result] of Object.entries(results)) {
    if (!result || typeof result !== "object") continue;
    const r = result as Record<string, unknown>;
    const primary =
      r.default && typeof r.default === "object"
        ? (r.default as Record<string, unknown>)
        : r;
    const metrics: Record<string, unknown> = {};

    for (const key of METRIC_KEYS) {
      if (key in primary) metrics[key] = primary[key];
    }
    if ("shape" in primary) metrics["output_shape"] = primary.shape;
    if ("type" in primary) metrics["output_type"] = primary.type;

    if (Object.keys(metrics).length > 0) {
      summary[nodeId] = metrics;
    }
  }
  return summary;
}

function statusSeverity(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "completed") return "success";
  if (status === "error") return "danger";
  if (status === "partial") return "warning";
  return "info";
}

function formatRelativeTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDays = Math.floor(diffHr / 24);
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

function formatMetricsPreview(
  summary: Record<string, Record<string, unknown>>
): string {
  const parts: string[] = [];
  for (const metrics of Object.values(summary)) {
    if (typeof metrics !== "object" || !metrics) continue;
    for (const [key, val] of Object.entries(metrics)) {
      if (parts.length >= 3) break;
      if (typeof val === "number") {
        const formatted = Number.isInteger(val) ? String(val) : val.toFixed(4);
        parts.push(`${key}=${formatted}`);
      }
    }
    if (parts.length >= 3) break;
  }
  return parts.length > 0 ? parts.join(", ") : "—";
}
</script>

<style scoped>
.page-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px;
  color: #64748b;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 48px;
  text-align: center;
  color: #94a3b8;
}

.empty-state i {
  font-size: 2.5rem;
}

.empty-state h3 {
  margin: 8px 0 0;
  color: #475569;
  font-size: 1.1rem;
}

.empty-state p {
  max-width: 400px;
  font-size: 0.9rem;
  line-height: 1.5;
}

.runs-table {
  font-size: 0.85rem;
}

.run-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.run-name {
  font-weight: 500;
}

.run-notes-hint {
  color: #94a3b8;
  font-size: 0.75rem;
}

.status-tag {
  font-size: 0.7rem;
  text-transform: uppercase;
}

.source-tag {
  font-size: 0.65rem;
  text-transform: uppercase;
}

.timestamp {
  color: #64748b;
  font-size: 0.8rem;
}

.metrics-preview {
  font-family: monospace;
  font-size: 0.8rem;
  color: #475569;
}

.save-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-field label {
  font-size: 0.85rem;
  font-weight: 500;
  color: #475569;
}

.w-full {
  width: 100%;
}
</style>
