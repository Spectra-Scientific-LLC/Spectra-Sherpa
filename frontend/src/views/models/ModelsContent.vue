<template>
  <section class="models-content">
    <header class="tab-header">
      <h1>Runs</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          label="Refresh"
          icon="pi pi-refresh"
          class="p-button-text p-button-sm"
          :loading="loading || runsStore.runsLoading"
          @click="refreshAll"
        />
        <Button
          label="Export"
          icon="pi pi-download"
          class="p-button-text p-button-sm"
          :disabled="!canExportActiveTab"
          @click="exportActiveTab"
        />
        <Button
          label="Compare Selected"
          icon="pi pi-chart-bar"
          class="p-button-sm p-button-outlined"
          :disabled="runsStore.selectedCount < 2"
          :badge="runsStore.selectedCount > 0 ? String(runsStore.selectedCount) : undefined"
          @click="handleCompareRuns"
        />
      </ResponsiveHeaderActions>
    </header>

    <!-- Loading / Error / No project / Empty --------------------------- -->
    <div v-if="loading && !models.length" class="empty-state">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <p>Loading models…</p>
    </div>

    <div v-else-if="error" class="empty-state">
      <p class="empty-state__title">{{ error }}</p>
      <Button label="Retry" icon="pi pi-refresh" class="p-button-text p-button-sm" @click="loadModels" />
    </div>

    <div v-else-if="!projectStore.currentProjectId" class="empty-state">
      <p class="empty-state__title">No project selected.</p>
      <Button
        label="Go to Dashboard"
        icon="pi pi-arrow-right"
        iconPos="right"
        class="p-button-text p-button-sm"
        @click="router.push('/dashboard')"
      />
    </div>

    <template v-else>
      <!-- Two-cell context strip: Project on the left, active subtab
           summary on the right (dynamic). Same pattern as Data page. -->
      <div class="context-strip">
        <button class="context-item" type="button" @click="router.push('/project')">
          <span class="context-label">Project</span>
          <strong>{{ activeProjectName }}</strong>
          <small>
            {{ runsStore.runs.length }} run{{ runsStore.runs.length === 1 ? "" : "s" }}
            · {{ models.length }} artifact{{ models.length === 1 ? "" : "s" }}
          </small>
        </button>
        <div class="context-item active-context" aria-live="polite">
          <span class="context-label">{{ activeSubtabLabel }}</span>
          <strong>{{ activeSubtabValue }}</strong>
          <small>{{ activeSubtabDetail }}</small>
        </div>
      </div>

      <TabView v-model:activeIndex="activeTab">
        <TabPanel header="Run History">
          <div v-if="runsStore.runsLoading && runsStore.runs.length === 0" class="loading-state">
            <ProgressSpinner style="width: 32px; height: 32px" />
            <span>Loading runs...</span>
          </div>

          <div v-else-if="runsStore.runs.length === 0" class="empty-state">
            <i class="pi pi-bookmark"></i>
            <p class="empty-state__title">No saved runs yet.</p>
            <p>Run a workflow, then save the result here for comparison and export.</p>
          </div>

          <div v-else class="run-history-panel">
            <div class="run-history-toolbar">
              <div class="run-kind-filter">
                <label for="run-kind-filter">Kind</label>
                <Dropdown
                  id="run-kind-filter"
                  v-model="runKindFilter"
                  :options="runKindOptions"
                  optionLabel="label"
                  optionValue="value"
                  class="run-kind-dropdown"
                />
              </div>
              <span class="run-history-count">
                {{ filteredRuns.length }} of {{ runsStore.runs.length }} run{{ runsStore.runs.length === 1 ? "" : "s" }}
              </span>
            </div>

            <DataTable
              v-model:selection="selectedRows"
              :value="filteredRuns"
              dataKey="id"
              stripedRows
              size="small"
              :loading="runsStore.runsLoading"
              sortField="executed_at"
              :sortOrder="-1"
              class="runs-table"
            >
              <template #empty>
                <div class="object-empty">No runs match this filter.</div>
              </template>
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

              <Column field="run_kind" header="Kind" sortable style="width: 140px">
                <template #body="{ data }">
                  <Tag
                    :value="formatRunKind(data.run_kind)"
                    severity="secondary"
                    class="kind-tag"
                  />
                </template>
              </Column>

              <Column header="Produces" style="width: 105px">
                <template #body="{ data }">
                  <Tag
                    v-if="(data.model_ids?.length || 0) > 0"
                    value="Artifact"
                    severity="success"
                    class="artifact-produced-tag"
                  />
                  <span v-else class="muted-dash">—</span>
                </template>
              </Column>

              <Column field="executed_at" header="Executed" sortable style="width: 150px">
                <template #body="{ data }">
                  <span class="timestamp" :title="data.executed_at">
                    {{ formatRelative(data.executed_at) }}
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
          </div>
        </TabPanel>

        <TabPanel header="Batch Run">
          <BatchRunTab
            :artifact-uids="selectedArtifactUidList"
            :artifacts="selectedArtifactSummaries"
            @completed="handleBatchCompleted"
          />
        </TabPanel>

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
            @back="activeTab = TAB_RUN_HISTORY"
          />

          <div v-else class="empty-state">
            <i class="pi pi-chart-bar"></i>
            <p class="empty-state__title">No runs selected.</p>
            <p>Check two or more rows in Run History to compare model versions, partitions, settings, and results.</p>
          </div>
        </TabPanel>

        <TabPanel header="Deploy">
          <div v-if="!selectedModel" class="object-empty">
            Select a model in <strong>Artifacts</strong> to see its deployment readiness.
          </div>
          <div v-else class="deploy-grid">
            <div>
              <span class="eyebrow">Selected</span>
              <h2 class="detail-name">{{ selectedModel.display_name || selectedModel.name }}</h2>
              <p class="deploy-subtitle">{{ modelSubtitle(selectedModel) }}</p>
            </div>
            <div class="readiness-list">
              <div v-for="item in deployReadinessItems" :key="item.label" class="readiness-row">
                <span class="dot" :class="item.ready ? 'ready' : 'empty'"></span>
                <div class="readiness-row__main">
                  <strong>{{ item.label }}</strong>
                  <small>{{ item.detail }}</small>
                </div>
              </div>
            </div>
            <div class="detail-actions">
              <Button
                label="Open Deploy"
                icon="pi pi-cloud-upload"
                iconPos="right"
                class="p-button-text p-button-sm"
                @click="router.push('/deploy')"
              />
            </div>
          </div>
        </TabPanel>

        <TabPanel header="Artifacts">
          <div class="artifact-toolbar">
            <InputText
              v-model="artifactSearch"
              placeholder="Search artifacts"
              class="artifact-search"
            />
            <span class="artifact-count">
              {{ selectedArtifactUidList.length }} selected
            </span>
            <Button
              v-if="!isDemoMode"
              label="Batch Run"
              icon="pi pi-play"
              class="p-button-sm"
              :disabled="selectedArtifactUidList.length === 0"
              @click="activeTab = TAB_BATCH_RUN"
            />
            <Button
              v-if="!isDemoMode"
              label="Mark Deploy-ready"
              icon="pi pi-check"
              class="p-button-text p-button-sm"
              :disabled="selectedArtifactUidList.length === 0"
              @click="markSelectedDeployReady"
            />
          </div>

          <div v-if="filteredModels.length" class="object-list">
            <div
              v-for="model in filteredModels"
              :key="model.artifact_uid"
              class="object-row"
              :class="{ active: selectedModel?.artifact_uid === model.artifact_uid }"
              role="button"
              tabindex="0"
              @click="toggleSelect(model)"
              @keydown.enter.prevent="toggleSelect(model)"
              @keydown.space.prevent="toggleSelect(model)"
            >
              <input
                type="checkbox"
                class="artifact-checkbox"
                :checked="selectedArtifactUids.has(model.artifact_uid)"
                :aria-label="`Select ${model.display_name || model.name}`"
                @click.stop="toggleArtifactSelection(model.artifact_uid)"
                @keydown.stop
              />
              <span class="dot ready"></span>
              <div class="object-row__main">
                <strong>{{ model.display_name || model.name }}</strong>
                <small>{{ modelSubtitle(model) }}</small>
              </div>
              <span class="object-row__time" :title="absoluteTimestamp(model.updated_at)">
                {{ formatRelative(model.updated_at) }}
              </span>
            </div>
          </div>

          <p v-else class="object-empty">No saved artifacts match this project/search.</p>

          <!-- Selected model detail panel — appears inline under the
               list once a row is clicked. Same vocabulary as Data's
               inspect view: small dl of stats. -->
          <section v-if="selectedModel" class="detail-section">
            <span class="eyebrow">Selected</span>
            <div class="artifact-name-edit">
              <InputText v-model="selectedModelNameDraft" class="artifact-name-input" :disabled="isDemoMode" />
              <Button
                v-if="!isDemoMode"
                label="Rename"
                class="p-button-sm p-button-text"
                :disabled="!selectedModelNameDraft.trim()"
                @click="renameSelectedModel"
              />
              <Button
                v-if="!isDemoMode"
                :label="selectedModel.is_deploy_ready ? 'Deploy-ready' : 'Mark deploy-ready'"
                :icon="selectedModel.is_deploy_ready ? 'pi pi-check' : 'pi pi-circle'"
                class="p-button-sm p-button-text"
                @click="toggleSelectedDeployReady"
              />
            </div>

            <dl class="detail-grid">
              <div>
                <dt>Type</dt>
                <dd>{{ selectedModel.model_type }}</dd>
              </div>
              <div>
                <dt>Features</dt>
                <dd>{{ selectedModel.n_features }}</dd>
              </div>
              <div>
                <dt>Components</dt>
                <dd>{{ selectedModel.n_components ?? "—" }}</dd>
              </div>
              <div>
                <dt>Workflow</dt>
                <dd>
                  <button
                    v-if="selectedModel.workflow_id != null"
                    type="button"
                    class="detail-link"
                    @click="router.push('/workflow')"
                  >#{{ selectedModel.workflow_id }} →</button>
                  <span v-else>not linked</span>
                </dd>
              </div>
              <div>
                <dt>Source node</dt>
                <dd>{{ selectedModel.node_id ?? "—" }}</dd>
              </div>
              <div v-if="selectedModelMetricRows.length" class="detail-metrics">
                <dt>Metrics</dt>
                <dd>
                  <span
                    v-for="row in selectedModelMetricRows"
                    :key="row.key"
                    class="metric-chip"
                  >
                    <span class="metric-chip__label">{{ row.label }}</span>
                    <span class="metric-chip__value">{{ row.value }}</span>
                  </span>
                </dd>
              </div>
              <div>
                <dt>Created</dt>
                <dd>{{ formatRelative(selectedModel.created_at) }}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{{ formatRelative(selectedModel.updated_at) }}</dd>
              </div>
            </dl>
          </section>
        </TabPanel>
      </TabView>
    </template>

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
            placeholder="Describe what changed or why this run matters."
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

    <Dialog
      v-model:visible="showDeleteDialog"
      header="Delete Run"
      :modal="true"
      :style="{ width: '400px' }"
    >
      <p>
        Delete <strong>{{ deleteTarget?.name }}</strong>? This cannot be undone.
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
/* eslint-disable @typescript-eslint/no-explicit-any -- run history payloads contain flexible backend metric snapshots. */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import InputText from "primevue/inputtext";
import ProgressSpinner from "primevue/progressspinner";
import TabPanel from "primevue/tabpanel";
import TabView from "primevue/tabview";
import Tag from "primevue/tag";
import Textarea from "primevue/textarea";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import LabelChips from "@/components/LabelChips.vue";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import { useRunsStore } from "@/stores/runs";
import { useWorkflowStore } from "@/stores/workflow";
import { getErrorMessage } from "@/utils/errors";
import { downloadJson } from "@/utils/download";
import BatchRunTab from "@/views/experiments/BatchRunTab.vue";
import ComparisonPanel from "@/views/experiments/ComparisonPanel.vue";
import type { ExecutionRunSummary } from "@/types";
import { useAuthStore } from "@/stores/auth";
import { useDemoMode } from "@/composables/useDemoMode";

interface ModelSummary {
  artifact_uid: string;
  name: string;
  display_name?: string | null;
  model_type: string;
  n_features: number;
  n_components: number | null;
  project_id: number | null;
  workflow_id: number | null;
  source_run_id?: number | null;
  training_dataset_id?: number | null;
  node_id?: string | null;
  metrics?: Record<string, unknown> | null;
  is_deploy_ready?: boolean;
  tags?: string[];
  created_at: string;
  updated_at: string;
}

const router = useRouter();
const toast = useToast();
const authStore = useAuthStore();
const projectStore = useProjectStore();
const runsStore = useRunsStore();
const workflowStore = useWorkflowStore();
const advisorStore = useAdvisorStore();
const { isDemoMode } = useDemoMode();
const headerActionItems = computed(() => [
  {
    label: "Refresh",
    icon: "pi pi-refresh",
    disabled: loading.value || runsStore.runsLoading,
    command: () => void refreshAll(),
  },
  {
    label: "Export",
    icon: "pi pi-download",
    disabled: !canExportActiveTab.value,
    command: exportActiveTab,
  },
  {
    label: "Compare Selected",
    icon: "pi pi-chart-bar",
    disabled: runsStore.selectedCount < 2,
    command: () => void handleCompareRuns(),
  },
]);

const models = ref<ModelSummary[]>([]);
const selectedModel = ref<ModelSummary | null>(null);
const selectedModelNameDraft = ref("");
const selectedArtifactUids = ref<Set<string>>(new Set());
const artifactSearch = ref("");
const runKindFilter = ref("all");
const loading = ref(false);
const error = ref<string | null>(null);
const showSaveDialog = ref(false);
const saveRunName = ref("");
const saveRunNotes = ref("");
const saving = ref(false);
const showDeleteDialog = ref(false);
const deleteTarget = ref<ExecutionRunSummary | null>(null);
const deleting = ref(false);
let artifactSearchTimer: ReturnType<typeof window.setTimeout> | null = null;

const TAB_RUN_HISTORY = 0;
const TAB_BATCH_RUN = 1;
const TAB_COMPARE = 2;
const TAB_DEPLOY = 3;
const TAB_ARTIFACTS = 4;
const RUNS_ACTIVE_TAB_PREFIX = "spectra_sherpa_runs_active_tab_v1";
const MODEL_SUBSCOPES = ["run_history", "batch_run", "compare", "deploy", "artifacts"] as const;
const MODEL_SUBSCOPE_TITLES: Record<(typeof MODEL_SUBSCOPES)[number], string> = {
  run_history: "Run History",
  batch_run: "Batch Run",
  compare: "Compare",
  deploy: "Deploy",
  artifacts: "Artifacts",
};
const activeTab = ref(TAB_RUN_HISTORY);

function runsActiveTabStorageKey(): string {
  return `${RUNS_ACTIVE_TAB_PREFIX}_${authStore.user?.id ?? "local"}_${
    projectStore.currentProjectId ?? "no-project"
  }`;
}

function restoreActiveRunsTab(): void {
  try {
    const raw = localStorage.getItem(runsActiveTabStorageKey());
    const parsed = raw === null ? NaN : Number(raw);
    if (Number.isInteger(parsed) && parsed >= 0 && parsed < MODEL_SUBSCOPES.length) {
      activeTab.value = parsed;
    }
  } catch {
    /* localStorage may be unavailable. */
  }
}

function persistActiveRunsTab(): void {
  try {
    localStorage.setItem(runsActiveTabStorageKey(), String(activeTab.value));
  } catch {
    /* localStorage may be unavailable. */
  }
}

const activeProjectName = computed(
  () => projectStore.currentProject?.name ?? "—",
);

const selectedRows = computed({
  get: () => runsStore.runs.filter((run) => runsStore.selectedRunIds.has(run.id)),
  set: (rows: ExecutionRunSummary[]) => {
    runsStore.selectedRunIds = new Set(rows.map((run) => run.id));
  },
});

const canSaveRun = computed(
  () => workflowStore.workflowId != null && workflowStore.lastExecutionResults != null,
);

const selectedArtifactUidList = computed(() => [...selectedArtifactUids.value]);
const selectedArtifactSummaries = computed(() => {
  const selected = selectedArtifactUids.value;
  return models.value.filter((model) => selected.has(model.artifact_uid));
});

const runKindOptions = [
  { label: "All", value: "all" },
  { label: "Training", value: "training" },
  { label: "Batch inference", value: "batch_inference" },
  { label: "Data", value: "data" },
  { label: "Other", value: "other" },
];

const filteredRuns = computed(() => {
  if (runKindFilter.value === "all") return runsStore.runs;
  return runsStore.runs.filter((run) => run.run_kind === runKindFilter.value);
});

const filteredModels = computed(() => {
  return models.value;
});

const canExportActiveTab = computed(() => {
  if (activeTab.value === TAB_RUN_HISTORY) return runsStore.runs.length > 0;
  if (activeTab.value === TAB_COMPARE) return runsStore.comparison != null;
  if (activeTab.value === TAB_DEPLOY) return selectedModel.value != null;
  if (activeTab.value === TAB_ARTIFACTS) return models.value.length > 0;
  return false;
});

const activeSubtabLabel = computed(() => {
  switch (activeTab.value) {
    case TAB_RUN_HISTORY: return "Run History";
    case TAB_BATCH_RUN: return "Batch Run";
    case TAB_COMPARE: return "Compare";
    case TAB_DEPLOY: return "Deploy";
    case TAB_ARTIFACTS: return "Artifacts";
    default: return "—";
  }
});

const activeSubtabValue = computed(() => {
  if (activeTab.value === TAB_RUN_HISTORY) {
    return `${filteredRuns.value.length} saved run${filteredRuns.value.length === 1 ? "" : "s"}`;
  }
  if (activeTab.value === TAB_BATCH_RUN) {
    return selectedArtifactUidList.value.length
      ? `${selectedArtifactUidList.value.length} selected artifact${selectedArtifactUidList.value.length === 1 ? "" : "s"}`
      : "Pick artifacts";
  }
  if (activeTab.value === TAB_COMPARE) {
    return runsStore.comparison
      ? `${runsStore.comparison.runs.length} compared run${runsStore.comparison.runs.length === 1 ? "" : "s"}`
      : "Select saved runs";
  }
  if (activeTab.value === TAB_DEPLOY) {
    return selectedModel.value?.display_name || selectedModel.value?.name || "No model selected";
  }
  return selectedModel.value?.display_name || selectedModel.value?.name || "Pick a model";
});

const activeSubtabDetail = computed(() => {
  switch (activeTab.value) {
    case TAB_RUN_HISTORY:
      return workflowStore.workflowId
        ? "Inspect saved workflow results"
        : "Load or run a workflow to build history";
    case TAB_BATCH_RUN:
      return "Apply saved artifacts to a project dataset";
    case TAB_COMPARE:
      return runsStore.selectedCount < 2
        ? "Pick two saved runs from history"
        : "Side-by-side metrics and parameter differences";
    case TAB_DEPLOY:
      return selectedModel.value
        ? "Confirm readiness before serving"
        : "Pick a model in Artifacts first";
    case TAB_ARTIFACTS:
      return selectedModel.value
        ? modelSubtitle(selectedModel.value)
        : "Click a model to inspect";
    default:
      return "";
  }
});

// Surface every numeric metric we got from the backend in the detail panel —
// the subtitle only shows the headline one, but the detail view is where the
// user goes when they want to actually compare two artifacts.
const selectedModelMetricRows = computed(() => {
  const metrics = selectedModel.value?.metrics ?? null;
  if (!metrics) return [] as { key: string; label: string; value: string }[];
  const rows: { key: string; label: string; value: string }[] = [];
  // Stable order: priority list first, then any other numeric keys.
  const seen = new Set<string>();
  for (const { key, label } of METRIC_PRIORITY) {
    const value = metrics[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      rows.push({ key, label, value: formatMetric(value) });
      seen.add(key);
    }
  }
  for (const [key, value] of Object.entries(metrics)) {
    if (seen.has(key)) continue;
    if (typeof value === "number" && Number.isFinite(value)) {
      rows.push({ key, label: key, value: formatMetric(value) });
    }
  }
  return rows;
});

const deployReadinessItems = computed(() => {
  const m = selectedModel.value;
  if (!m) return [];
  return [
    {
      label: "Project link",
      ready: m.project_id != null,
      detail: m.project_id != null
        ? "Linked to a project record"
        : "Link this artifact to a project record.",
    },
    {
      label: "Human deploy-ready flag",
      ready: Boolean(m.is_deploy_ready),
      detail: m.is_deploy_ready
        ? "A user has marked this artifact ready for deployment review."
        : "Mark deploy-ready after reviewing batch inference and comparison results.",
    },
    {
      label: "Workflow lineage",
      ready: m.workflow_id != null,
      detail: m.workflow_id != null
        ? `Produced by workflow #${m.workflow_id}.`
        : "Producing workflow is not recorded.",
    },
    {
      label: "Feature contract",
      ready: m.n_features > 0,
      detail: `${m.n_features} feature${m.n_features === 1 ? "" : "s"} recorded for serving input validation.`,
    },
    {
      label: "Finite metadata",
      ready: !hasInvalidModelNumber(m),
      detail: hasInvalidModelNumber(m)
        ? "Model metrics or numeric metadata include NaN/Inf and must be regenerated before deploy."
        : "Model metrics and numeric metadata are finite.",
    },
  ];
});

// Deep-link targets for training node provenance affordances. Artifact links
// jump to Artifacts; run links keep the user in Run History and select the
// producing run.
const route = useRoute();

function applyArtifactDeepLink(): void {
  const target = route.query.artifact;
  const uid = typeof target === "string" && target.length > 0 ? target : null;
  if (!uid) return;
  activeTab.value = TAB_ARTIFACTS;
  persistActiveRunsTab();
  const match = models.value.find((model) => model.artifact_uid === uid);
  if (match) {
    selectedModel.value = match;
    selectedModelNameDraft.value = match.display_name || match.name;
  } else {
    clearRouteQueryParam("artifact");
  }
}

function clearRouteQueryParam(name: string): void {
  if (!(name in route.query)) return;
  const query = { ...route.query };
  delete query[name];
  void router.replace({ query });
}

function applyRunDeepLink(): void {
  const target = route.query.run;
  const raw = typeof target === "string" && target.length > 0 ? Number.parseInt(target, 10) : NaN;
  if (!Number.isFinite(raw)) return;
  activeTab.value = TAB_RUN_HISTORY;
  runKindFilter.value = "all";
  runsStore.selectedRunIds = new Set([raw]);
  persistActiveRunsTab();
}

onMounted(async () => {
  await projectStore.ensureProjectForBrowserTab();
  restoreActiveRunsTab();
  await Promise.all([loadModels(), refreshRuns()]);
  applyArtifactDeepLink();
  applyRunDeepLink();
  void syncAdvisorForModelsTab();
});

watch(
  () => [route.query.artifact, route.query.run] as const,
  () => {
    applyArtifactDeepLink();
    applyRunDeepLink();
  },
);

watch(
  () => projectStore.currentProjectId,
  async () => {
    restoreActiveRunsTab();
    runsStore.clearSelection();
    selectedArtifactUids.value = new Set();
    await Promise.all([loadModels(), refreshRuns()]);
    applyArtifactDeepLink();
    applyRunDeepLink();
    void syncAdvisorForModelsTab();
  },
);

watch(artifactSearch, () => {
  if (artifactSearchTimer != null) {
    window.clearTimeout(artifactSearchTimer);
  }
  artifactSearchTimer = window.setTimeout(() => {
    void loadModels();
  }, 250);
});

watch(activeTab, () => {
  persistActiveRunsTab();
  if (activeTab.value === TAB_COMPARE && runsStore.selectedCount >= 2) void handleCompareRuns();
  void syncAdvisorForModelsTab();
});

watch(
  () => [...runsStore.selectedRunIds].join(","),
  () => {
    if (activeTab.value !== TAB_COMPARE) return;
    if (runsStore.selectedCount >= 2) {
      void handleCompareRuns();
    } else {
      runsStore.comparison = null;
    }
  },
);

watch(
  () => workflowStore.workflowId,
  async (workflowId) => {
    if (workflowId) {
      runsStore.clearSelection();
      await refreshRuns();
    }
  },
);

watch(showSaveDialog, (visible) => {
  if (visible) {
    const base = workflowStore.workflowName || "Workflow";
    const count = runsStore.runs.length + 1;
    saveRunName.value = `${base} - Run ${count}`;
    saveRunNotes.value = "";
  }
});

const promptedResultRef = ref<unknown>(workflowStore.lastExecutionResults);
watch(
  () => workflowStore.lastExecutionResults,
  (result) => {
    if (result && result !== promptedResultRef.value && canSaveRun.value) {
      promptedResultRef.value = result;
      showSaveDialog.value = true;
    }
  },
);

async function loadModels(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const projectId = projectStore.currentProjectId;
    if (projectId == null) {
      models.value = [];
      selectedModel.value = null;
      return;
    }
    const response = await api.get<ModelSummary[]>("/models", {
      params: {
        limit: 100,
        project_id: projectId,
        q: artifactSearch.value.trim() || undefined,
      },
    });
    // Sort by most-recently-updated so the list reads like an activity log.
    models.value = [...response.data].sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
    const isSearching = artifactSearch.value.trim().length > 0;
    if (
      !isSearching &&
      selectedModel.value &&
      !models.value.some((model) => model.artifact_uid === selectedModel.value?.artifact_uid)
    ) {
      selectedModel.value = null;
    }
    if (!isSearching) {
      const available = new Set(models.value.map((model) => model.artifact_uid));
      selectedArtifactUids.value = new Set([...selectedArtifactUids.value].filter((uid) => available.has(uid)));
    }
  } catch (err) {
    error.value = getErrorMessage(err, "Failed to load models.");
    models.value = [];
    selectedModel.value = null;
    selectedArtifactUids.value = new Set();
  } finally {
    loading.value = false;
  }
}

async function syncAdvisorForModelsTab(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  const subscopeKey = MODEL_SUBSCOPES[activeTab.value] ?? "run_history";
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "models",
      subscopeKey,
      title: MODEL_SUBSCOPE_TITLES[subscopeKey],
    });
  } catch (err) {
    console.warn("[models] switchScope failed", err);
  }
}

async function refreshRuns(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) {
    runsStore.runs = [];
    runsStore.clearSelection();
    return;
  }
  await runsStore.fetchProjectRuns(projectId);
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadModels(), refreshRuns()]);
}

async function handleSaveRun(): Promise<void> {
  if (!workflowStore.workflowId || !workflowStore.lastExecutionResults) return;

  saving.value = true;
  try {
    const results = workflowStore.lastExecutionResults as Record<string, unknown>;
    const diagnostics = workflowStore.lastExecutionDiagnostics as Record<string, Record<string, unknown>>;
    const nodeStatuses: Record<string, string> = {};

    for (const node of workflowStore.nodes) {
      const state = workflowStore.getNodeExecutionState(node.id);
      if (state) {
        nodeStatuses[node.id] = state.status;
      }
    }

    const hasError = Object.values(nodeStatuses).some((status) => status === "error");
    const allCompleted = Object.values(nodeStatuses).every((status) => status === "completed");
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
      model_ids: extractModelIds(results),
      run_kind: "training",
    });
    await loadModels();

    showSaveDialog.value = false;
    toast.add({
      severity: "success",
      summary: "Run saved",
      detail: `"${saveRunName.value}" was added to Run History.`,
      life: 3000,
    });
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Save failed",
      detail: err?.message || "Could not save run.",
      life: 5000,
    });
  } finally {
    saving.value = false;
  }
}

function extractModelIds(results: Record<string, unknown>): string[] {
  const ids = new Set<string>();
  for (const value of Object.values(results)) {
    collectModelIds(value, ids);
  }
  return [...ids];
}

function collectModelIds(value: unknown, ids: Set<string>): void {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    for (const item of value) collectModelIds(item, ids);
    return;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["model_id", "artifact_uid"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate) ids.add(candidate);
  }
  for (const child of Object.values(record)) {
    if (child && typeof child === "object") collectModelIds(child, ids);
  }
}

async function handleCompareRuns(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null || runsStore.selectedCount < 2) return;
  try {
    await runsStore.compareProjectRuns(projectId, [...runsStore.selectedRunIds]);
    activeTab.value = TAB_COMPARE;
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Compare failed",
      detail: err?.message || "Could not compare runs.",
      life: 5000,
    });
  }
}

async function handleUpdateLabels(runId: number, labels: string[]): Promise<void> {
  try {
    await runsStore.updateLabels(runId, labels);
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Update failed",
      detail: err?.message || "Could not update labels.",
      life: 3000,
    });
  }
}

function confirmDelete(run: ExecutionRunSummary): void {
  deleteTarget.value = run;
  showDeleteDialog.value = true;
}

async function handleDelete(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null || !deleteTarget.value) return;
  deleting.value = true;
  try {
    await runsStore.deleteProjectRun(projectId, deleteTarget.value.id);
    showDeleteDialog.value = false;
    toast.add({
      severity: "info",
      summary: "Run deleted",
      life: 2000,
    });
  } catch (err: any) {
    toast.add({
      severity: "error",
      summary: "Delete failed",
      detail: err?.message || "Could not delete run.",
      life: 5000,
    });
  } finally {
    deleting.value = false;
  }
}

function exportActiveTab(): void {
  const projectSlug = safeFilename(activeProjectName.value || "project");
  if (activeTab.value === TAB_COMPARE) {
    if (runsStore.comparison) {
      downloadJson(runsStore.comparison, `${projectSlug}-run-comparison.json`);
    }
    return;
  }
  if (activeTab.value === TAB_DEPLOY && selectedModel.value) {
    downloadJson(
      {
        model: selectedModel.value,
        readiness: deployReadinessItems.value,
      },
      `${projectSlug}-${safeFilename(selectedModel.value.name)}-deploy-readiness.json`,
    );
    return;
  }
  if (activeTab.value === TAB_ARTIFACTS) {
    downloadJson(models.value, `${projectSlug}-model-artifacts.json`);
    return;
  }
  downloadJson(runsStore.runs, `${projectSlug}-run-history.json`);
}

function toggleSelect(model: ModelSummary): void {
  if (selectedModel.value?.artifact_uid === model.artifact_uid) {
    selectedModel.value = null;
    selectedModelNameDraft.value = "";
  } else {
    selectedModel.value = model;
    selectedModelNameDraft.value = model.display_name || model.name;
  }
}

function toggleArtifactSelection(uid: string): void {
  const next = new Set(selectedArtifactUids.value);
  if (next.has(uid)) {
    next.delete(uid);
  } else {
    next.add(uid);
  }
  selectedArtifactUids.value = next;
}

async function handleBatchCompleted(run: ExecutionRunSummary): Promise<void> {
  runsStore.runs = [run, ...runsStore.runs.filter((existing) => existing.id !== run.id)];
  runsStore.selectedRunIds = new Set([run.id]);
  activeTab.value = TAB_RUN_HISTORY;
}

async function patchModel(uid: string, payload: Record<string, unknown>): Promise<ModelSummary | null> {
  try {
    const response = await api.patch<ModelSummary>(`/models/${uid}`, payload);
    const idx = models.value.findIndex((model) => model.artifact_uid === uid);
    if (idx !== -1) models.value[idx] = { ...models.value[idx], ...response.data };
    if (selectedModel.value?.artifact_uid === uid) {
      selectedModel.value = { ...selectedModel.value, ...response.data };
      selectedModelNameDraft.value = selectedModel.value.display_name || selectedModel.value.name;
    }
    return response.data;
  } catch (err) {
    toast.add({
      severity: "error",
      summary: "Artifact update failed",
      detail: getErrorMessage(err, "Could not update artifact metadata."),
      life: 5000,
    });
    return null;
  }
}

async function renameSelectedModel(): Promise<void> {
  if (!selectedModel.value) return;
  await patchModel(selectedModel.value.artifact_uid, {
    display_name: selectedModelNameDraft.value.trim(),
  });
}

async function toggleSelectedDeployReady(): Promise<void> {
  if (!selectedModel.value) return;
  await patchModel(selectedModel.value.artifact_uid, {
    is_deploy_ready: !selectedModel.value.is_deploy_ready,
  });
}

async function markSelectedDeployReady(): Promise<void> {
  await Promise.all(
    selectedArtifactUidList.value.map((uid) => patchModel(uid, { is_deploy_ready: true })),
  );
}

function modelSubtitle(model: ModelSummary): string {
  const parts: string[] = [model.model_type, `${model.n_features} feat`];
  if (model.n_components != null) {
    parts.push(`${model.n_components} LV`);
  }
  const metric = modelMetricSummary(model.metrics ?? null);
  if (metric) parts.push(metric);
  if (model.node_id) parts.push(`node ${model.node_id}`);
  if (model.workflow_id != null) parts.push(`wf #${model.workflow_id}`);
  return parts.join(" · ");
}

// Pick the most informative headline metric. Order matters — classification
// CV scores beat raw accuracy, and CV/test regression scores beat training
// scores. Anything not in this list is hidden from the subtitle (it remains
// available in the detail panel).
const METRIC_PRIORITY: Array<{ key: string; label: string }> = [
  { key: "cv_balanced_accuracy", label: "cv_bal_acc" },
  { key: "cv_accuracy", label: "cv_acc" },
  { key: "cv_f1_macro", label: "cv_f1" },
  { key: "cv_sensitivity_macro", label: "cv_sens" },
  { key: "cv_specificity_macro", label: "cv_spec" },
  { key: "f1_macro", label: "f1" },
  { key: "balanced_accuracy", label: "bal_acc" },
  { key: "accuracy_test", label: "acc_test" },
  { key: "accuracy", label: "acc" },
  { key: "train_balanced_accuracy", label: "train_bal_acc" },
  { key: "f1", label: "f1" },
  { key: "r2_cv", label: "r2_cv" },
  { key: "r2_test", label: "r2_test" },
  { key: "r2", label: "r2" },
  { key: "rmsecv", label: "rmsecv" },
  { key: "rmse_test", label: "rmse_test" },
  { key: "rmse", label: "rmse" },
  { key: "mae", label: "mae" },
];

function modelMetricSummary(
  metrics: Record<string, unknown> | null,
): string | null {
  if (!metrics) return null;
  const canonical =
    flattenClassificationMetricsContract(metrics.classification_metrics) ??
    flattenClassificationMetricsContract(metrics.metrics) ??
    flattenClassificationMetricsContract(metrics);
  const mergedMetrics = canonical ? { ...metrics, ...canonical } : metrics;
  for (const { key, label } of METRIC_PRIORITY) {
    const value = mergedMetrics[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return `${label} ${formatMetric(value)}`;
    }
  }
  return null;
}

function formatMetric(value: number): string {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function formatRelative(dateStr: string): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  if (diff < 0) return "just now";
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function absoluteTimestamp(dateStr: string): string {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
}

const METRIC_KEYS = [
  "r2",
  "r2_cv",
  "r2_test",
  "rmsecv",
  "rmse",
  "rmse_test",
  "mse",
  "mae",
  "accuracy",
  "test_accuracy",
  "train_accuracy",
  "cv_accuracy",
  "cv_balanced_accuracy",
  "cv_f1_macro",
  "cv_precision_macro",
  "cv_recall_macro",
  "cv_sensitivity_macro",
  "cv_specificity_macro",
  "balanced_accuracy",
  "accuracy_test",
  "test_balanced_accuracy",
  "test_f1_macro",
  "test_precision_macro",
  "test_recall_macro",
  "test_sensitivity_macro",
  "test_specificity_macro",
  "train_balanced_accuracy",
  "train_f1_macro",
  "train_precision_macro",
  "train_recall_macro",
  "train_sensitivity_macro",
  "train_specificity_macro",
  "f1",
  "f1_macro",
  "f1_score",
  "precision",
  "precision_macro",
  "recall",
  "recall_macro",
  "sensitivity_macro",
  "specificity_macro",
  "q2",
  "best_rmsecv",
  "global_rmsecv",
  "mean_n_selected",
  "selection_stability",
  "n_selected",
  "best_interval",
  "n_iterations_run",
  "n_components",
  "explained_variance",
  "explained_variance_ratio",
  "cumulative_variance",
  "reconstruction_error",
  "hotelling_t2",
  "q_residuals",
  "n_outliers",
  "n_clusters",
  "best_k",
  "inertia",
  "silhouette_score",
];

const METRIC_KEY_SET = new Set(METRIC_KEYS);
const METRIC_NESTED_KEYS = new Set(["default", "diagnostics", "meta", "metadata", "metrics", "quality_summary"]);
const CLASSIFICATION_METRIC_NAMES = [
  "accuracy",
  "balanced_accuracy",
  "f1_macro",
  "precision_macro",
  "recall_macro",
  "sensitivity_macro",
  "specificity_macro",
];
const AMBIGUOUS_CLASSIFICATION_KEYS = new Set([
  "accuracy",
  "balanced_accuracy",
  "f1",
  "f1_macro",
  "f1_score",
  "precision",
  "precision_macro",
  "recall",
  "recall_macro",
  "sensitivity_macro",
  "specificity_macro",
]);
const STRUCTURAL_RESULT_KEYS = new Set([
  "X",
  "X_cal",
  "X_test",
  "X_train",
  "cal_indices",
  "test_indices",
  "train_indices",
  "y",
  "y_cal",
  "y_pred",
  "y_test",
  "y_train",
]);

function flattenClassificationMetricsContract(value: unknown): Record<string, number> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.task_type !== "classification" || !record.splits || typeof record.splits !== "object") return null;

  const out: Record<string, number> = {};
  const splits = record.splits as Record<string, unknown>;
  for (const [split, rawMetrics] of Object.entries(splits)) {
    if (!rawMetrics || typeof rawMetrics !== "object" || Array.isArray(rawMetrics)) continue;
    const metrics = rawMetrics as Record<string, unknown>;
    for (const name of CLASSIFICATION_METRIC_NAMES) {
      const candidate = metrics[name];
      if (typeof candidate === "number" && Number.isFinite(candidate)) {
        out[`${split}_${name}`] = candidate;
      }
    }
  }
  const nClasses = record.n_classes;
  if (typeof nClasses === "number" && Number.isFinite(nClasses)) out.n_classes = nClasses;
  return Object.keys(out).length > 0 ? out : null;
}

function collectMetricScalars(
  value: unknown,
  out: Record<string, number>,
  depth = 0,
): void {
  if (depth > 5 || !value || typeof value !== "object" || Array.isArray(value)) return;
  const record = value as Record<string, unknown>;
  const canonical = flattenClassificationMetricsContract(record);
  if (canonical) {
    for (const [key, candidate] of Object.entries(canonical)) out[key] ??= candidate;
    return;
  }
  let hasCanonicalChild = false;
  for (const childKey of ["metrics", "classification_metrics"]) {
    const childMetrics = flattenClassificationMetricsContract(record[childKey]);
    if (childMetrics) {
      for (const [key, candidate] of Object.entries(childMetrics)) out[key] ??= candidate;
      hasCanonicalChild = true;
    }
  }
  for (const [key, candidate] of Object.entries(record)) {
    if (hasCanonicalChild && AMBIGUOUS_CLASSIFICATION_KEYS.has(key)) continue;
    if (METRIC_KEY_SET.has(key) && typeof candidate === "number" && Number.isFinite(candidate)) {
      out[key] ??= candidate;
    }
  }
  for (const key of METRIC_NESTED_KEYS) {
    collectMetricScalars(record[key], out, depth + 1);
  }
}

function collectMetricValues(
  value: unknown,
  out: Record<string, number | number[]>,
  depth = 0,
): void {
  if (depth > 5 || !value || typeof value !== "object" || Array.isArray(value)) return;
  const record = value as Record<string, unknown>;
  const canonical = flattenClassificationMetricsContract(record);
  if (canonical) {
    for (const [key, candidate] of Object.entries(canonical)) out[key] ??= candidate;
    return;
  }
  let hasCanonicalChild = false;
  for (const childKey of ["metrics", "classification_metrics"]) {
    const childMetrics = flattenClassificationMetricsContract(record[childKey]);
    if (childMetrics) {
      for (const [key, candidate] of Object.entries(childMetrics)) out[key] ??= candidate;
      hasCanonicalChild = true;
    }
  }
  for (const [key, candidate] of Object.entries(record)) {
    if (hasCanonicalChild && AMBIGUOUS_CLASSIFICATION_KEYS.has(key)) continue;
    if (!METRIC_KEY_SET.has(key) || key in out) continue;
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      out[key] = candidate;
    } else if (
      Array.isArray(candidate) &&
      candidate.length > 0 &&
      candidate.every((item) => typeof item === "number" && Number.isFinite(item))
    ) {
      out[key] = candidate as number[];
    }
  }
  for (const key of METRIC_NESTED_KEYS) {
    collectMetricValues(record[key], out, depth + 1);
  }
}

type MetricCategory =
  | "classification"
  | "regression"
  | "selection"
  | "clustering"
  | "decomposition"
  | "data";

const RUN_HISTORY_METRIC_ORDER: Record<MetricCategory, Array<{ key: string; label: string }>> = {
  classification: [
    { key: "cv_balanced_accuracy", label: "CV bal acc" },
    { key: "test_accuracy", label: "Test acc" },
    { key: "accuracy_test", label: "Test acc" },
    { key: "test_balanced_accuracy", label: "Test bal acc" },
    { key: "cv_accuracy", label: "CV acc" },
    { key: "balanced_accuracy", label: "Bal acc" },
    { key: "accuracy", label: "Acc" },
    { key: "train_accuracy", label: "Train acc" },
    { key: "train_balanced_accuracy", label: "Train bal acc" },
    { key: "cv_f1_macro", label: "CV F1" },
    { key: "cv_precision_macro", label: "CV precision" },
    { key: "cv_recall_macro", label: "CV recall" },
    { key: "cv_sensitivity_macro", label: "CV sensitivity" },
    { key: "cv_specificity_macro", label: "CV specificity" },
    { key: "train_f1_macro", label: "Train F1" },
    { key: "train_precision_macro", label: "Train precision" },
    { key: "train_recall_macro", label: "Train recall" },
    { key: "train_sensitivity_macro", label: "Train sensitivity" },
    { key: "train_specificity_macro", label: "Train specificity" },
    { key: "f1_macro", label: "F1" },
    { key: "f1", label: "F1" },
    { key: "best_k", label: "Best k" },
  ],
  regression: [
    { key: "r2_cv", label: "R2CV" },
    { key: "q2", label: "Q2" },
    { key: "r2_test", label: "Test R2" },
    { key: "r2", label: "R2" },
    { key: "rmsecv", label: "RMSECV" },
    { key: "rmse_test", label: "Test RMSE" },
    { key: "rmse", label: "RMSE" },
    { key: "mae", label: "MAE" },
  ],
  selection: [
    { key: "n_selected", label: "Selected" },
    { key: "mean_n_selected", label: "Mean selected" },
    { key: "best_rmsecv", label: "Best RMSECV" },
    { key: "global_rmsecv", label: "Global RMSECV" },
    { key: "selection_stability", label: "Stability" },
    { key: "best_interval", label: "Best interval" },
  ],
  clustering: [
    { key: "silhouette_score", label: "Silhouette" },
    { key: "n_clusters", label: "Clusters" },
    { key: "inertia", label: "Inertia" },
  ],
  decomposition: [
    { key: "explained_variance_ratio", label: "Explained" },
    { key: "cumulative_variance", label: "Cumulative" },
    { key: "explained_variance", label: "Explained" },
    { key: "reconstruction_error", label: "Recon err" },
    { key: "n_outliers", label: "Outliers" },
    { key: "n_components", label: "Components" },
  ],
  data: [],
};

const RUN_HISTORY_CATEGORY_PRIORITY: MetricCategory[] = [
  "classification",
  "regression",
  "selection",
  "clustering",
  "decomposition",
  "data",
];

function inferMetricCategory(
  nodeId: string,
  metrics: Record<string, unknown>,
  values: Record<string, number | number[]>,
): MetricCategory {
  const hint = [
    nodeId,
    metrics.type,
    metrics.output_type,
    metrics.model_type,
    metrics.task_type,
  ]
    .filter((value) => typeof value === "string")
    .join(" ")
    .toLowerCase();
  const hasAny = (keys: string[]) => keys.some((key) => key in values);

  if (
    /classification|classifier|plsda|simca|knn|lda|qda|logistic/.test(hint) ||
    hasAny(["cv_accuracy", "train_accuracy", "accuracy", "balanced_accuracy", "f1", "f1_macro", "cv_f1_macro"])
  ) {
    return "classification";
  }
  if (
    /selection|cars|ipls|interval|variable/.test(hint) ||
    hasAny(["n_selected", "best_rmsecv", "mean_n_selected", "selection_stability", "best_interval"])
  ) {
    return "selection";
  }
  if (/cluster|hca|kmeans/.test(hint) || hasAny(["silhouette_score", "n_clusters", "inertia"])) {
    return "clustering";
  }
  if (
    /regression|calibration|pls|pcr|svr|linear/.test(hint) ||
    hasAny(["r2_cv", "r2_test", "r2", "rmsecv", "rmse", "q2", "mae"])
  ) {
    return "regression";
  }
  if (
    /pca|mcr|als|nmf|ica|efa|decomposition|scores|loadings/.test(hint) ||
    hasAny(["explained_variance_ratio", "explained_variance", "reconstruction_error", "n_outliers"])
  ) {
    return "decomposition";
  }
  return "data";
}

function metricCategoryRank(category: MetricCategory): number {
  const idx = RUN_HISTORY_CATEGORY_PRIORITY.indexOf(category);
  return idx === -1 ? RUN_HISTORY_CATEGORY_PRIORITY.length : idx;
}

function orderedMetricEntriesForRunHistory(
  nodeId: string,
  metrics: Record<string, unknown>,
): Array<[string, string, number | number[]]> {
  const values: Record<string, number | number[]> = {};
  collectMetricValues(metrics, values);
  const category = inferMetricCategory(nodeId, metrics, values);
  const seen = new Set<string>();
  const entries: Array<[string, string, number | number[]]> = [];
  for (const { key, label } of RUN_HISTORY_METRIC_ORDER[category]) {
    if (key in values) {
      entries.push([key, label, values[key]]);
      seen.add(key);
    }
  }
  for (const { key, label } of METRIC_PRIORITY) {
    if (!seen.has(key) && key in values) {
      entries.push([key, label, values[key]]);
      seen.add(key);
    }
  }
  for (const [key, value] of Object.entries(values)) {
    if (!seen.has(key)) entries.push([key, key, value]);
  }
  return entries;
}

function extractMetrics(
  results: Record<string, unknown>,
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
    collectMetricScalars(primary, metrics as Record<string, number>);
    if ("shape" in primary) metrics.output_shape = primary.shape;
    if ("type" in primary) metrics.output_type = primary.type;
    for (const [key, value] of Object.entries(r)) {
      if (STRUCTURAL_RESULT_KEYS.has(key)) {
        metrics[key] = compactResultStructure(value);
      }
    }

    if (Object.keys(metrics).length > 0) {
      summary[nodeId] = metrics;
    }
  }
  return summary;
}

function compactResultStructure(value: unknown): Record<string, unknown> {
  if (Array.isArray(value)) {
    if (value.length > 0 && Array.isArray(value[0])) {
      return { shape: [value.length, value[0].length] };
    }
    return { length: value.length, n_samples: value.length };
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const compact: Record<string, unknown> = {};
    for (const key of ["type", "title", "units", "n_samples", "n_features", "shape"]) {
      if (key in record) compact[key] = record[key];
    }
    if (Array.isArray(record.data)) {
      const data = record.data;
      compact.shape = data.length > 0 && Array.isArray(data[0])
        ? [data.length, data[0].length]
        : [data.length];
      compact.n_samples ??= data.length;
      if (data.length > 0 && Array.isArray(data[0])) compact.n_features ??= data[0].length;
    }
    return compact;
  }
  return { value };
}

function statusSeverity(status: string): "success" | "danger" | "warning" | "info" {
  if (status === "completed") return "success";
  if (status === "error") return "danger";
  if (status === "partial") return "warning";
  return "info";
}

function formatRunKind(kind: string | null | undefined): string {
  switch (kind) {
    case "training":
      return "Training";
    case "batch_inference":
      return "Batch";
    case "data":
      return "Data";
    case "other":
      return "Other";
    default:
      return "Other";
  }
}

function hasInvalidModelNumber(model: ModelSummary): boolean {
  if (!Number.isFinite(model.n_features)) return true;
  if (model.n_components != null && !Number.isFinite(model.n_components)) return true;
  return containsInvalidNumber(model.metrics);
}

function containsInvalidNumber(value: unknown): boolean {
  if (typeof value === "number") return !Number.isFinite(value);
  if (Array.isArray(value)) return value.some((item) => containsInvalidNumber(item));
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some((item) => containsInvalidNumber(item));
  }
  return false;
}

function formatMetricsPreview(
  summary: Record<string, Record<string, unknown>>,
): string {
  const candidates: Array<{
    rank: number;
    nodeIndex: number;
    metricIndex: number;
    key: string;
    label: string;
    value: number | number[];
  }> = [];
  Object.entries(summary).forEach(([nodeId, metrics], nodeIndex) => {
    if (typeof metrics !== "object" || !metrics) return;
    const values: Record<string, number | number[]> = {};
    collectMetricValues(metrics, values);
    const category = inferMetricCategory(nodeId, metrics, values);
    if (category === "data") return;
    orderedMetricEntriesForRunHistory(nodeId, metrics).forEach(([key, label, value], metricIndex) => {
      candidates.push({
        rank: metricCategoryRank(category),
        nodeIndex,
        metricIndex,
        key,
        label,
        value,
      });
    });
  });
  const parts = candidates
    .sort((a, b) => (
      a.rank - b.rank ||
      a.nodeIndex - b.nodeIndex ||
      a.metricIndex - b.metricIndex
    ))
    .slice(0, 3)
    .map(({ key, label, value }) => `${label}=${formatRunHistoryMetricValue(key, value)}`);
  return parts.length > 0 ? parts.join(", ") : "—";
}

function formatRunHistoryMetricValue(key: string, value: number | number[]): string {
  if (Array.isArray(value)) {
    if (key === "explained_variance_ratio" || key === "cumulative_variance") {
      const total = value.reduce((sum, item) => sum + item, 0);
      return `${(total * 100).toFixed(1)}%`;
    }
    return value.length ? formatMetric(value[0]) : "—";
  }
  if (
    /accuracy|f1|precision|recall|r2|q2|silhouette|stability/.test(key) &&
    Math.abs(value) <= 1
  ) {
    return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

function safeFilename(value: string): string {
  return value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "runs";
}
</script>

<style scoped>
/*
  Canonical Zen vocabulary — same tokens as ProjectContent: 0.9375rem base,
  1.75rem h1 / 1.5rem h2 at weight 500, 1080px max-width, hairline section
  dividers, single primary accent for the selected/ready state, middle-dot
  separators inside the row's small line.
*/

.models-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

/* Header ----------------------------------------------------------- */

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* Empty / loading state ------------------------------------------ */

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 3rem 1rem;
  text-align: center;
}

.empty-state__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 500;
}

.empty-state p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 3rem 1rem;
  color: var(--text-color-secondary);
  text-align: center;
}

/* Context strip ---------------------------------------------------- */
/* Two-cell strip — Project on the left, active-subtab summary on the
   right. Same vocabulary as DataContent's context strip. */
.context-strip {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--surface-border);
}

.context-item {
  appearance: none;
  background: transparent;
  border: none;
  border-right: 1px solid var(--surface-border);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  min-width: 0;
  padding: 0.25rem 1rem 0.25rem 0;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: color 0.15s ease;
}

.context-item:last-child {
  border-right: none;
  padding-left: 1rem;
  padding-right: 0;
}

.context-item.active-context {
  cursor: default;
}

.context-item:not(.active-context):hover strong {
  color: var(--primary-color);
}

.context-item:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

.context-item strong {
  color: var(--text-color);
  font-size: 1rem;
  font-weight: 500;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  transition: color 0.15s ease;
}

.context-item small {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.context-label {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* Zen subtab styling — strip PrimeVue TabView's boxed chrome to a flat
   hairline-underline strip. Active tab gets a primary underline; hover
   lifts to primary with a half-strength underline. Same vocabulary as
   the Data page's :deep() block. */
.models-content :deep(.p-tabview) {
  background: transparent;
}

.models-content :deep(.p-tabview-nav-container),
.models-content :deep(.p-tabview-nav-content) {
  background: transparent;
}

.models-content :deep(.p-tabview-nav) {
  display: flex;
  align-items: center;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--surface-border);
  padding: 0;
  margin: 0;
  list-style: none;
}

.models-content :deep(.p-tabview-nav li) {
  margin: 0;
  background: transparent;
}

.models-content :deep(.p-tabview-nav .p-tabview-nav-link) {
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

.models-content :deep(.p-tabview-nav li:not(.p-disabled):not(.p-highlight) .p-tabview-nav-link:hover) {
  color: var(--primary-color);
  border-bottom-color: color-mix(in srgb, var(--primary-color) 40%, transparent) !important;
}

.models-content :deep(.p-tabview-nav li.p-highlight .p-tabview-nav-link) {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color) !important;
}

/* Artifacts is the persistent list (mirrors My Dataset on Data page).
   DOM order is Run History / Batch Run / Compare / Deploy / Artifacts.
   CSS pins Artifacts to the right edge with a hairline gutter. */
.models-content :deep(.p-tabview-nav > li:nth-child(5)) {
  order: 99;
  margin-left: auto;
  border-left: 1px solid var(--surface-border);
}

.models-content :deep(.p-tabview-nav > li:nth-child(5)) .p-tabview-nav-link {
  padding-left: 1.25rem;
}

.models-content :deep(.p-tabview-panels) {
  background: transparent;
  padding: 1.5rem 0 0;
}

.compare-workspace {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.compare-controls {
  align-items: end;
  border-bottom: 1px solid var(--surface-border);
  display: grid;
  gap: 0.75rem;
  grid-template-columns: minmax(220px, 1fr) 150px 140px auto;
  padding-bottom: 1rem;
}

.compare-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-width: 0;
}

.compare-field label {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.compare-select {
  width: 100%;
}

.compare-error {
  color: #b91c1c;
  font-size: 0.875rem;
  margin: 0;
}

.compare-results {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-bottom: 0.75rem;
}

.result-summary {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.result-summary strong {
  color: var(--text-color);
  font-size: 0.9375rem;
  font-weight: 600;
}

.result-summary span {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

/* Compare grid: tabular layout sharing the row vocabulary with the
   list — selected row gets a primary leading stripe. */
.compare-grid {
  display: flex;
  flex-direction: column;
  font-size: 0.875rem;
}

.compare-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 0.75rem;
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--surface-border);
  cursor: pointer;
  transition: color 0.15s ease;
}

.compare-row--result {
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 0.8fr) minmax(0, 1fr) minmax(0, 1.6fr);
}

.compare-row:last-child {
  border-bottom: none;
}

.compare-row:not(.compare-row--head):hover {
  color: var(--primary-color);
}

.compare-row:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

.compare-row--head {
  cursor: default;
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom-color: var(--surface-border);
}

.compare-row.active {
  color: var(--primary-color);
}

.compare-row span,
.compare-row strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.compare-row strong {
  font-weight: 500;
}

/* Run history ----------------------------------------------------- */

.runs-table {
  font-size: 0.85rem;
}

.run-history-panel {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.run-history-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.25rem;
}

.run-kind-filter {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.run-kind-filter label,
.run-history-count {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
}

.run-kind-dropdown {
  min-width: 11rem;
}

.run-name-cell {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.run-name {
  font-weight: 500;
}

.run-notes-hint {
  color: var(--text-color-secondary);
  font-size: 0.75rem;
}

.status-tag,
.kind-tag,
.artifact-produced-tag {
  font-size: 0.68rem;
  text-transform: uppercase;
}

.muted-dash {
  color: var(--text-color-secondary);
}

.timestamp {
  color: var(--text-color-secondary);
  font-size: 0.8rem;
}

.metrics-preview {
  color: var(--text-color-secondary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 0.8rem;
}

.save-form {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-field label {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  font-weight: 500;
}

.w-full {
  width: 100%;
}

/* Deploy readiness ----------------------------------------------- */

.deploy-grid {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.deploy-subtitle {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  margin: 0.25rem 0 0;
}

.readiness-list {
  display: flex;
  flex-direction: column;
}

.readiness-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--surface-border);
}

.readiness-row:last-child {
  border-bottom: none;
}

.readiness-row__main {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.readiness-row__main strong {
  font-size: 0.9375rem;
  font-weight: 500;
}

.readiness-row__main small {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
}

/* Object list (the models) --------------------------------------- */

.object-section {
  display: flex;
  flex-direction: column;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--surface-border);
}

.object-section__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.object-section__title {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.object-section__count {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-variant-numeric: tabular-nums;
}

.object-list {
  display: flex;
  flex-direction: column;
}

.artifact-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}

.artifact-search {
  width: min(320px, 100%);
}

.artifact-count {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  margin-right: auto;
}

.object-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--surface-border);
  cursor: pointer;
  user-select: none;
  transition: color 0.15s ease;
}

.artifact-checkbox {
  width: 1rem;
  height: 1rem;
  accent-color: var(--primary-color);
}

.object-row:last-child {
  border-bottom: none;
}

.object-row:hover {
  color: var(--primary-color);
}

.object-row:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

/* Selected: leading-edge accent stripe — same vocabulary as the
   active project card on the Dashboard. */
.object-row.active::before {
  content: "";
  position: absolute;
  left: -0.5rem;
  top: 0.5rem;
  bottom: 0.5rem;
  width: 3px;
  background: var(--primary-color);
  border-radius: 0 2px 2px 0;
}

.object-row__main {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  min-width: 0;
  flex: 1;
}

.object-row__main strong {
  font-size: 0.9375rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.object-row__main small {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.object-row__time {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.artifact-name-edit {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.artifact-name-input {
  min-width: min(360px, 100%);
}

.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border: 1.5px solid var(--text-color-secondary);
  border-radius: 50%;
  flex-shrink: 0;
  opacity: 0.55;
}

.dot.ready {
  background: var(--primary-color);
  border-color: var(--primary-color);
  opacity: 1;
}

.object-empty {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  margin: 0.5rem 0 0;
}

/* Selected model detail ------------------------------------------ */

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.detail-name {
  font-size: 1.5rem;
  font-weight: 500;
  margin: 0;
  letter-spacing: 0;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 0.75rem 1.5rem;
  margin: 0;
}

.detail-grid > div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.detail-grid dt {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-color-secondary);
}

.detail-grid dd {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--text-color);
  font-weight: 500;
}

.detail-grid .detail-metrics {
  grid-column: 1 / -1;
}

.detail-grid .detail-metrics dd {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.metric-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 0.375rem;
  padding: 0.125rem 0.5rem;
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  font-size: 0.8125rem;
}

.metric-chip__label {
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-weight: 500;
}

.metric-chip__value {
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.detail-link {
  background: transparent;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--primary-color);
  cursor: pointer;
}

.detail-link:hover {
  text-decoration: underline;
}

.detail-actions {
  display: flex;
  gap: 0.5rem;
  margin-left: -0.5rem;
}

/* Shared ---------------------------------------------------------- */

.eyebrow {
  display: block;
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* Responsive ----------------------------------------------------- */

@media (max-width: 900px) {
  .header-actions {
    justify-content: flex-start;
  }
  .context-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
