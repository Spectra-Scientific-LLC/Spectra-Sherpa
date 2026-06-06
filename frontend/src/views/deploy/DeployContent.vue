<template>
  <section class="page-content">
    <header class="tab-header">
      <h1>Deploy</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          icon="pi pi-refresh"
          class="p-button-sm p-button-text"
          :loading="deployStore.loading"
          title="Refresh"
          @click="refreshAll"
        />
        <Button
          label="New Watch"
          icon="pi pi-plus"
          class="p-button-sm"
          data-action="create_folder_watch"
          @click="showCreateDialog = true"
        />
      </ResponsiveHeaderActions>
    </header>

    <TabView v-model:activeIndex="activeTab">
      <!-- ======================== FOLDER WATCHES TAB ======================== -->
      <TabPanel header="Folder Watches">
        <div v-if="deployStore.loading && deployStore.watches.length === 0" class="loading-state">
          <ProgressSpinner style="width: 32px; height: 32px" />
          <span>Loading watches...</span>
        </div>

        <div v-else-if="deployStore.watches.length === 0" class="empty-state">
          <i class="pi pi-eye"></i>
          <h3>No folder watches</h3>
          <p>
            Create a folder watch to automatically process new spectral files
            as they appear in a server directory.
          </p>
        </div>

        <DataTable
          v-else
          :value="deployStore.watches"
          dataKey="id"
          stripedRows
          size="small"
          class="watches-table"
        >
          <Column field="name" header="Name" sortable style="min-width: 150px">
            <template #body="{ data }">
              <span class="watch-name">{{ data.name }}</span>
            </template>
          </Column>

          <Column header="Workflow" style="min-width: 120px">
            <template #body="{ data }">
              <span class="workflow-ref">
                {{ getWorkflowName(data.workflow_id) }}
              </span>
            </template>
          </Column>

          <Column field="folder_path" header="Folder" style="min-width: 200px">
            <template #body="{ data }">
              <span class="folder-path" :title="data.folder_path">
                {{ data.folder_path }}
              </span>
            </template>
          </Column>

          <Column field="file_pattern" header="Pattern" style="width: 80px" />

          <Column field="poll_interval_sec" header="Interval" style="width: 80px">
            <template #body="{ data }">
              {{ data.poll_interval_sec }}s
            </template>
          </Column>

          <Column header="Enabled" style="width: 90px">
            <template #body="{ data }">
              <ToggleButton
                :modelValue="data.is_enabled"
                onLabel="ON"
                offLabel="OFF"
                class="toggle-sm"
                @update:model-value="(val: boolean) => handleToggle(data.id, val)"
              />
            </template>
          </Column>

          <Column header="Last Poll" style="width: 120px">
            <template #body="{ data }">
              <span v-if="data.last_poll_at" class="timestamp">
                {{ formatRelativeTime(data.last_poll_at) }}
              </span>
              <span v-else class="timestamp">Never</span>
            </template>
          </Column>

          <Column header="Files" style="width: 60px">
            <template #body="{ data }">
              {{ data.processed_files ? Object.keys(data.processed_files).length : 0 }}
            </template>
          </Column>

          <Column header="Error" style="width: 100px">
            <template #body="{ data }">
              <span v-if="data.last_error" class="error-text" :title="data.last_error">
                <i class="pi pi-exclamation-triangle"></i>
                Error
              </span>
            </template>
          </Column>

          <Column style="width: 60px">
            <template #body="{ data }">
              <Button
                icon="pi pi-trash"
                class="p-button-text p-button-sm p-button-danger"
                title="Delete watch"
                @click="confirmDeleteWatch(data)"
              />
            </template>
          </Column>
        </DataTable>
      </TabPanel>

      <!-- ======================== PREDICTION HISTORY TAB ======================== -->
      <TabPanel header="Prediction History">
        <div v-if="deployStore.runsLoading && deployStore.deployRuns.length === 0" class="loading-state">
          <ProgressSpinner style="width: 32px; height: 32px" />
          <span>Loading runs...</span>
        </div>

        <div v-else-if="deployStore.deployRuns.length === 0" class="empty-state">
          <i class="pi pi-history"></i>
          <h3>No prediction history</h3>
          <p>
            Runs from folder watches and batch predictions will appear here.
          </p>
        </div>

        <DataTable
          v-else
          :value="deployStore.deployRuns"
          dataKey="id"
          stripedRows
          size="small"
          v-model:expandedRows="expandedRuns"
          class="runs-table"
        >
          <Column :expander="true" headerStyle="width: 3rem" />

          <Column field="name" header="Name" sortable style="min-width: 200px" />

          <Column header="Source" style="width: 100px">
            <template #body="{ data }">
              <Tag
                :value="data.source_type || 'manual'"
                :severity="data.source_type === 'folder_watch' ? 'warning' : 'info'"
                class="source-tag"
              />
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

          <Column field="status" header="Status" style="width: 90px">
            <template #body="{ data }">
              <Tag
                :severity="statusSeverity(data.status)"
                :value="data.status"
                class="status-tag"
              />
            </template>
          </Column>

          <Column header="Files" style="width: 80px">
            <template #body="{ data }">
              {{ getBatchFileCount(data) }}
            </template>
          </Column>

          <Column header="Artifacts" style="min-width: 170px">
            <template #body="{ data }">
              <span class="workflow-ref" :title="(data.model_ids || []).join(', ')">
                {{ formatModelIds(data.model_ids) }}
              </span>
            </template>
          </Column>

          <Column field="executed_at" header="Date" sortable style="width: 130px">
            <template #body="{ data }">
              <span class="timestamp">{{ formatRelativeTime(data.executed_at) }}</span>
            </template>
          </Column>

          <!-- Expanded row: per-file predictions -->
          <template #expansion="{ data }">
            <div class="predictions-detail">
              <h4>Per-file Results</h4>
              <div v-if="loadingPredictions[data.id]" class="loading-state" style="padding: 16px">
                <ProgressSpinner style="width: 24px; height: 24px" />
              </div>
              <DataTable
                v-else-if="predictions[data.id]?.length"
                :value="predictions[data.id]"
                size="small"
                stripedRows
                class="predictions-table"
              >
                <Column field="file_name" header="File" style="min-width: 200px" />
                <Column field="status" header="Status" style="width: 80px">
                  <template #body="{ data: pred }">
                    <Tag
                      :severity="pred.status === 'completed' ? 'success' : 'danger'"
                      :value="pred.status"
                      class="status-tag"
                    />
                  </template>
                </Column>
                <Column field="processing_time_ms" header="Time" style="width: 80px">
                  <template #body="{ data: pred }">
                    {{ pred.processing_time_ms ? `${pred.processing_time_ms}ms` : "\u2014" }}
                  </template>
                </Column>
                <Column header="Artifact" style="min-width: 130px">
                  <template #body="{ data: pred }">
                    <span class="workflow-ref" :title="pred.model_id || ''">
                      {{ shortModelId(pred.model_id) }}
                    </span>
                  </template>
                </Column>
                <Column field="error_message" header="Error" style="min-width: 150px">
                  <template #body="{ data: pred }">
                    <span v-if="pred.error_message" class="error-text">
                      {{ pred.error_message }}
                    </span>
                  </template>
                </Column>
              </DataTable>
              <p v-else class="no-predictions">No per-file results available.</p>
            </div>
          </template>
        </DataTable>
      </TabPanel>
    </TabView>

    <!-- Create Watch Dialog -->
    <Dialog
      v-model:visible="showCreateDialog"
      header="New Folder Watch"
      :modal="true"
      :style="{ width: '500px' }"
    >
      <div class="create-form">
        <div class="form-field">
          <label for="watch-workflow">Workflow</label>
          <Dropdown
            inputId="watch-workflow"
            v-model="newWatch.workflow_id"
            :options="workflowOptions"
            optionLabel="name"
            optionValue="id"
            placeholder="Select workflow"
            class="w-full"
          />
        </div>
        <div class="form-field">
          <label for="watch-name">Watch Name</label>
          <InputText
            id="watch-name"
            v-model="newWatch.name"
            placeholder="e.g. Incoming Samples"
            class="w-full"
          />
        </div>
        <div class="form-field">
          <label for="watch-folder">Folder Path</label>
          <InputText
            id="watch-folder"
            v-model="newWatch.folder_path"
            placeholder="/data/incoming/"
            class="w-full"
          />
        </div>
        <div class="form-row">
          <div class="form-field">
            <label for="watch-pattern">File Pattern</label>
            <InputText
              id="watch-pattern"
              v-model="newWatch.file_pattern"
              placeholder="*.spa"
              class="w-full"
            />
          </div>
          <div class="form-field">
            <label for="watch-interval">Poll Interval (sec)</label>
            <InputNumber
              inputId="watch-interval"
              v-model="newWatch.poll_interval_sec"
              :min="10"
              :max="86400"
              class="w-full"
            />
          </div>
        </div>
      </div>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="showCreateDialog = false"
        />
        <Button
          label="Create"
          icon="pi pi-check"
          :loading="creating"
          :disabled="!canCreate"
          @click="handleCreate"
        />
      </template>
    </Dialog>

    <!-- Delete Watch Confirmation -->
    <Dialog
      v-model:visible="showDeleteDialog"
      header="Delete Watch"
      :modal="true"
      :style="{ width: '400px' }"
    >
      <p>
        Are you sure you want to delete
        <strong>{{ deleteTarget?.name }}</strong>?
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
          :loading="deletingWatch"
          @click="handleDeleteWatch"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
/* eslint-disable @typescript-eslint/no-explicit-any -- deployment run payloads are backend-shaped and vary by execution status. */
import { ref, computed, onMounted, watch, reactive } from "vue";
import TabView from "primevue/tabview";
import TabPanel from "primevue/tabpanel";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import InputNumber from "primevue/inputnumber";
import Dropdown from "primevue/dropdown";
import ToggleButton from "primevue/togglebutton";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";

import LabelChips from "@/components/LabelChips.vue";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import { useAdvisorStore } from "@/stores/advisor";
import { useDeployStore } from "@/stores/deploy";
import { useProjectStore } from "@/stores/project";
import { useRunsStore } from "@/stores/runs";
import api from "@/api/client";
import type { FolderWatch, BatchPredictionResult } from "@/types";

const toast = useToast();
const deployStore = useDeployStore();
const runsStore = useRunsStore();
const projectStore = useProjectStore();
const advisorStore = useAdvisorStore();

const activeTab = ref(0);

// R4 — Sherpa Advisor scope routing for the Deploy tab.
const DEPLOY_SUBSCOPES = ["integrations", "jobs"] as const;
const DEPLOY_SUBSCOPE_TITLES: Record<(typeof DEPLOY_SUBSCOPES)[number], string> = {
  integrations: "Folder Watches",
  jobs: "Prediction History",
};

async function syncAdvisorForDeploySubtab(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  const subscopeKey = DEPLOY_SUBSCOPES[activeTab.value] ?? "integrations";
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "deploy",
      subscopeKey,
      title: DEPLOY_SUBSCOPE_TITLES[subscopeKey],
    });
  } catch (err) {
    console.warn("[deploy] switchScope failed", err);
  }
}

watch(activeTab, () => {
  void syncAdvisorForDeploySubtab();
});
watch(
  () => projectStore.currentProjectId,
  (next) => {
    if (next != null) void syncAdvisorForDeploySubtab();
  },
);
onMounted(() => {
  void syncAdvisorForDeploySubtab();
});

// Workflow options for dropdown
interface WorkflowOption {
  id: number;
  name: string;
}
const workflowOptions = ref<WorkflowOption[]>([]);

// Watch CRUD state
const showCreateDialog = ref(false);
const headerActionItems = computed(() => [
  {
    label: "Refresh",
    icon: "pi pi-refresh",
    disabled: deployStore.loading,
    command: refreshAll,
  },
  {
    label: "New Watch",
    icon: "pi pi-plus",
    command: () => {
      showCreateDialog.value = true;
    },
  },
]);
const creating = ref(false);
const newWatch = reactive({
  workflow_id: null as number | null,
  name: "",
  folder_path: "",
  file_pattern: "*",
  poll_interval_sec: 60,
});

const showDeleteDialog = ref(false);
const deleteTarget = ref<FolderWatch | null>(null);
const deletingWatch = ref(false);

// Prediction expansion
const expandedRuns = ref<Record<string, boolean>>({});
const predictions = ref<Record<number, BatchPredictionResult[]>>({});
const loadingPredictions = ref<Record<number, boolean>>({});

const canCreate = computed(
  () => newWatch.workflow_id && newWatch.name.trim() && newWatch.folder_path.trim()
);

onMounted(async () => {
  deployStore.fetchWatches();
  deployStore.fetchDeployRuns();

  try {
    const response = await api.get<WorkflowOption[]>("/workflows");
    workflowOptions.value = response.data;
  } catch {
    workflowOptions.value = [];
  }
});

// Load predictions when expanding a run row
watch(expandedRuns, async (expanded) => {
  for (const run of deployStore.deployRuns) {
    const key = String(run.id);
    if (expanded[key] && !predictions.value[run.id] && !loadingPredictions.value[run.id]) {
      loadingPredictions.value[run.id] = true;
      try {
        predictions.value[run.id] = await runsStore.fetchPredictions(run.id);
      } catch {
        predictions.value[run.id] = [];
      } finally {
        loadingPredictions.value[run.id] = false;
      }
    }
  }
});

function refreshAll() {
  deployStore.fetchWatches();
  deployStore.fetchDeployRuns();
}

function getWorkflowName(workflowId: number): string {
  const wf = workflowOptions.value.find((w) => w.id === workflowId);
  return wf ? wf.name : `#${workflowId}`;
}

async function handleToggle(watchId: number, enable: boolean) {
  try {
    await deployStore.toggleWatch(watchId, enable);
    toast.add({
      severity: "info",
      summary: enable ? "Watch Enabled" : "Watch Disabled",
      life: 2000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Toggle Failed",
      detail: error?.message || "Could not toggle watch",
      life: 3000,
    });
  }
}

async function handleCreate() {
  if (!canCreate.value) return;
  creating.value = true;
  try {
    await deployStore.createWatch({
      workflow_id: newWatch.workflow_id!,
      name: newWatch.name.trim(),
      folder_path: newWatch.folder_path.trim(),
      file_pattern: newWatch.file_pattern || "*",
      poll_interval_sec: newWatch.poll_interval_sec,
    });
    showCreateDialog.value = false;
    // Reset form
    newWatch.workflow_id = null;
    newWatch.name = "";
    newWatch.folder_path = "";
    newWatch.file_pattern = "*";
    newWatch.poll_interval_sec = 60;
    toast.add({
      severity: "success",
      summary: "Watch Created",
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Create Failed",
      detail: error?.response?.data?.detail || error?.message || "Could not create watch",
      life: 5000,
    });
  } finally {
    creating.value = false;
  }
}

function confirmDeleteWatch(w: FolderWatch) {
  deleteTarget.value = w;
  showDeleteDialog.value = true;
}

async function handleDeleteWatch() {
  if (!deleteTarget.value) return;
  deletingWatch.value = true;
  try {
    await deployStore.deleteWatch(deleteTarget.value.id);
    showDeleteDialog.value = false;
    toast.add({ severity: "info", summary: "Watch Deleted", life: 2000 });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Delete Failed",
      detail: error?.message || "Could not delete watch",
      life: 5000,
    });
  } finally {
    deletingWatch.value = false;
  }
}

async function handleUpdateLabels(runId: number, labels: string[]) {
  try {
    await runsStore.updateLabels(runId, labels);
    // Also update in deploy runs list
    const idx = deployStore.deployRuns.findIndex((r) => r.id === runId);
    if (idx !== -1) {
      deployStore.deployRuns[idx] = { ...deployStore.deployRuns[idx], labels };
    }
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Update Failed",
      detail: error?.message || "Could not update labels",
      life: 3000,
    });
  }
}

function getBatchFileCount(run: { results_summary: Record<string, Record<string, unknown>> }): string {
  const batch = run.results_summary?.__batch__;
  if (batch && typeof batch.total_files === "number") {
    return String(batch.total_files);
  }
  return "\u2014";
}

function shortModelId(modelId: string | null | undefined): string {
  if (!modelId) return "\u2014";
  return modelId.length > 12 ? `${modelId.slice(0, 12)}\u2026` : modelId;
}

function formatModelIds(modelIds: string[] | null | undefined): string {
  if (!modelIds || modelIds.length === 0) return "\u2014";
  if (modelIds.length === 1) return shortModelId(modelIds[0]);
  return `${modelIds.length} models`;
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
</script>

<style scoped>
.page-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
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

.watches-table,
.runs-table {
  font-size: 0.85rem;
}

.watch-name {
  font-weight: 500;
}

.workflow-ref {
  color: #6366f1;
  font-size: 0.8rem;
}

.folder-path {
  font-family: monospace;
  font-size: 0.8rem;
  color: #475569;
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}

.toggle-sm {
  transform: scale(0.85);
}

.timestamp {
  color: #64748b;
  font-size: 0.8rem;
}

.error-text {
  color: #ef4444;
  font-size: 0.8rem;
}

.status-tag {
  font-size: 0.7rem;
  text-transform: uppercase;
}

.source-tag {
  font-size: 0.65rem;
  text-transform: uppercase;
}

.predictions-detail {
  padding: 12px 24px;
}

.predictions-detail h4 {
  margin: 0 0 12px;
  font-size: 0.9rem;
  color: #475569;
}

.predictions-table {
  font-size: 0.8rem;
}

.no-predictions {
  color: #94a3b8;
  font-size: 0.85rem;
}

.create-form {
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

.form-row {
  display: flex;
  gap: 12px;
}

.form-row .form-field {
  flex: 1;
}

.w-full {
  width: 100%;
}

/* ===== Sub-tab styling ============================================
   Match DataContent.vue: transparent panels, hairline rule beneath the
   nav, primary-color underline marks the active sub-tab. Keeps Deploy's
   "Folder Watches / Prediction History" visually consistent with Data's
   "Import / Synthesis / Upload / ..." sub-tabs. */
.page-content :deep(.p-tabview) {
  background: transparent;
}

.page-content :deep(.p-tabview-nav-container),
.page-content :deep(.p-tabview-nav-content) {
  background: transparent;
}

.page-content :deep(.p-tabview-nav) {
  display: flex;
  align-items: center;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  padding: 0;
  margin: 0;
  list-style: none;
}

.page-content :deep(.p-tabview-nav li) {
  margin: 0;
  background: transparent;
}

.page-content :deep(.p-tabview-nav .p-tabview-nav-link) {
  background: transparent !important;
  border: none !important;
  border-radius: 0;
  border-bottom: 2px solid transparent !important;
  color: var(--text-color-secondary);
  font-size: 0.9375rem;
  font-weight: 500;
  padding: 0.6rem 1rem;
  transition: color 0.15s ease, border-color 0.15s ease;
  box-shadow: none !important;
}

.page-content :deep(.p-tabview-nav li:not(.p-disabled):not(.p-highlight) .p-tabview-nav-link:hover) {
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 40%, transparent) !important;
}

.page-content :deep(.p-tabview-nav li.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color) !important;
}

.page-content :deep(.p-tabview-panels) {
  background: transparent;
  padding: 1.5rem 0 0;
}
</style>
