<template>
  <section class="page-content deploy-content">
    <WorkspaceHeader title="Deploy" :actions="headerActionItems">
      <ContextualActions v-if="!isHostedPro" :context="deployActionContext" />
      <Button
        v-if="!isHostedPro"
        label="New Watch"
        icon="pi pi-plus"
        class="p-button-sm"
        data-action="create_folder_watch"
        @click="showCreateDialog = true"
      />
    </WorkspaceHeader>

    <section v-if="isHostedPro" class="hosted-pro-deploy" role="status">
      <i class="pi pi-desktop" aria-hidden="true"></i>
      <h2>Deploy from a Workbench</h2>
      <p>
        Hosted Pro provides model fitting and scientific review. Folder watches and prediction
        history run on a Workbench, where you can import a signed application package and continue
        deployment.
      </p>
    </section>

    <template v-else>
      <WorkspaceContext label="Deployment context">
        <WorkspaceContextItem
          :label="sectionTitle"
          :value="selectedApplication?.name || 'Select an application'"
        >
          <span
            v-if="selectedApplication?.campaign_validation_recorded"
            title="Campaign validation evidence recorded; accuracy on new samples is not certified."
            >★</span
          >
        </WorkspaceContextItem>
      </WorkspaceContext>
      <WorkspaceTabs v-model="activeTab" :tab-ids="tabIds">
        <TabPanel header="Application">
          <section class="released-applications" aria-labelledby="released-applications-heading">
            <div class="section-heading">
              <div>
                <h2 id="released-applications-heading">Fitted applications</h2>
              </div>
              <span v-if="selectedApplication" class="selected-application" role="status">
                Selected: {{ selectedApplication.name }}
              </span>
            </div>
            <div
              v-if="deployStore.applicationsLoading && !applicationList.length"
              class="loading-state compact"
            >
              <ProgressSpinner style="width: 24px; height: 24px" />
              <span>Loading fitted applications...</span>
            </div>
            <div v-else-if="applicationError" class="error-state" role="alert">
              {{ applicationError }}<Button label="Retry" @click="fetchArtifacts" />
            </div>
            <div v-else-if="!applicationList.length" class="empty-state compact">
              <i class="pi pi-box"></i>
              <p>
                No fitted applications yet. Save a fitted model or import an application package.
              </p>
            </div>
            <div v-else class="application-list" role="list">
              <button
                v-for="application in applicationList"
                :key="application.application_id"
                type="button"
                class="application-card"
                :class="{ selected: application.application_id === selectedApplicationId }"
                :aria-pressed="application.application_id === selectedApplicationId"
                @click="selectApplication(application.application_id)"
              >
                <span class="application-card__name">{{ application.name }}</span>
                <span
                  v-if="application.campaign_validation_recorded"
                  class="campaign-validation-star"
                  role="img"
                  aria-label="Campaign validation recorded"
                  title="Validation evidence recorded in the imported campaign package. This does not certify accuracy on new samples."
                  >★</span
                >
                <Tag
                  :value="application.origin === 'saved_run' ? 'Saved run' : 'Portable application'"
                  severity="info"
                />
              </button>
            </div>
          </section>

          <details v-if="selectedApplication">
            <summary>Details</summary>
            <p v-if="selectedApplication.source_run_id">
              Source run {{ selectedApplication.source_run_id }}
            </p>
            <code>{{ selectedApplication.application_id }}</code>
            <code v-if="selectedApplication.artifact_digest">{{
              selectedApplication.artifact_digest
            }}</code>
          </details>
          <details v-if="selectedApplication && appMode === 'local'">
            <summary>Optional qualification and evidence</summary>
            <QualificationPanel
              :workflow-id="selectedApplication.workflow_id"
              :canonical-artifact-id="selectedApplication.canonical_artifact_id"
              :project-id="projectStore.currentProjectId"
            />
          </details>
          <QualificationPanel
            v-else-if="selectedApplication"
            :workflow-id="selectedApplication.workflow_id"
            :canonical-artifact-id="selectedApplication.canonical_artifact_id"
            :project-id="projectStore.currentProjectId"
          />
        </TabPanel>
        <!-- ======================== FOLDER WATCHES TAB ======================== -->
        <TabPanel header="Folder Watches">
          <div v-if="deployStore.loading && deployStore.watches.length === 0" class="loading-state">
            <ProgressSpinner style="width: 32px; height: 32px" />
            <span>Loading watches...</span>
          </div>

          <div v-else-if="deployStore.watchesError" class="error-state" role="alert">
            {{ deployStore.watchesError }}<Button label="Retry" @click="syncOperationalState" />
          </div>
          <div v-else-if="deployStore.watches.length === 0" class="empty-state">
            <i class="pi pi-eye"></i>
            <h3>No folder watches</h3>
            <p>
              Create a folder watch to automatically process new spectral files as they appear in a
              server directory.
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

            <Column header="Model" style="min-width: 240px">
              <template #body="{ data }">
                <Dropdown
                  :modelValue="watchTargetKey(data)"
                  :options="watchArtifactOptions(data)"
                  optionLabel="label"
                  optionValue="artifact_uid"
                  optionDisabled="disabled"
                  :disabled="appMode !== 'local' && data.is_enabled"
                  placeholder="Select fitted model"
                  :aria-label="`Model for ${data.name}`"
                  @update:model-value="(uid: string) => handleRebind(data.id, uid)"
                />
                <small v-if="data.workflow_version_id"
                  >Version {{ data.workflow_version_id }}</small
                >
                <small v-else-if="data.canonical_plan_digest" :title="data.canonical_plan_digest"
                  >Application plan {{ data.canonical_plan_digest.slice(0, 12) }}</small
                >
              </template>
            </Column>

            <Column field="file_pattern" header="Pattern" style="width: 80px" />

            <Column field="poll_interval_sec" header="Interval" style="width: 80px">
              <template #body="{ data }"> {{ data.poll_interval_sec }}s </template>
            </Column>

            <Column header="Intervals">
              <template #body="{ data }">
                <span>{{
                  data.uncertainty_record ? "Selected calibration record" : "Point predictions only"
                }}</span>
                <button
                  v-if="data.uncertainty_record"
                  type="button"
                  @click="exportWatchUncertainty(data)"
                >
                  Export
                </button>
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

            <Column v-if="appMode === 'local'" header="Dry run">
              <template #body="{ data }">
                <button
                  v-if="!data.canonical_artifact_id"
                  type="button"
                  @click="dryRunWatchId = data.id"
                >
                  Try a file (optional)
                </button>
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

            <Column header="Instrument QC">
              <template #body="{ data }"
                ><button type="button" @click="qcWatchId = data.id">
                  QC / maintenance
                </button></template
              >
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
          <div
            v-if="deployStore.runsLoading && deployStore.deployRuns.length === 0"
            class="loading-state"
          >
            <ProgressSpinner style="width: 32px; height: 32px" />
            <span>Loading runs...</span>
          </div>

          <div v-else-if="deployStore.runsError" class="error-state" role="alert">
            {{ deployStore.runsError }}<Button label="Retry" @click="syncOperationalState" />
          </div>
          <div v-else-if="deployStore.deployRuns.length === 0" class="empty-state">
            <i class="pi pi-history"></i>
            <h3>No prediction history</h3>
            <p>Runs from folder watches and batch predictions will appear here.</p>
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
                <span
                  class="workflow-ref"
                  :title="
                    data.source_metadata?.canonical_artifact_digest ||
                    (data.succeeded_artifact_uids || []).join(', ')
                  "
                >
                  {{
                    data.source_metadata?.canonical_artifact_digest
                      ? `Campaign ${data.source_metadata.canonical_artifact_digest.slice(0, 12)}`
                      : formatModelIds(data.succeeded_artifact_uids)
                  }}
                </span>
              </template>
            </Column>

            <Column header="QC at run start">
              <template #body="{ data }">
                <button
                  v-if="data.source_metadata?.instrument_qc"
                  type="button"
                  @click="qcSnapshot = data.source_metadata.instrument_qc"
                >
                  {{ data.source_metadata.instrument_qc.status }}
                </button>
                <span v-else>Not retained</span>
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
                <div v-else-if="predictionErrors[data.id]" role="alert">
                  <p>Run {{ data.id }}: {{ predictionErrors[data.id] }}</p>
                  <Button label="Retry results" @click="loadPredictions(data.id)" />
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
                  <Column header="Results">
                    <template #body="{ data: pred }">
                      <Button
                        icon="pi pi-search"
                        label="Inspect"
                        class="p-button-text p-button-sm"
                        :disabled="!pred.results && !pred.retained_node_ids?.length"
                        @click="inspectPrediction(pred, data.project_id)"
                      />
                    </template>
                  </Column>
                </DataTable>
                <p v-else class="no-predictions">No per-file results available.</p>
              </div>
            </template>
          </DataTable>
        </TabPanel>
      </WorkspaceTabs>
    </template>

    <Dialog
      :visible="selectedPrediction !== null"
      :header="selectedPrediction?.file_name || 'Prediction'"
      modal
      :style="{ width: '720px', maxWidth: '95vw' }"
      @update:visible="selectedPrediction = null"
    >
      <template v-if="selectedPrediction">
        <p>
          Saved per-file values. Original input labels and complete node evidence may not be
          retained.
        </p>
        <p>Model: {{ selectedPrediction.model_id || "Not recorded" }}</p>
        <SavedValue :value="selectedPrediction.results" />
      </template>
    </Dialog>

    <Dialog
      :visible="dryRunWatchId !== null"
      header="Try a file (optional)"
      modal
      :style="{ width: '800px', maxWidth: '95vw' }"
      @update:visible="dryRunWatchId = null"
    >
      <WatchDryRun
        v-if="appMode === 'local' && dryRunWatchId !== null"
        :key="dryRunWatchId"
        :watch-id="dryRunWatchId"
      />
    </Dialog>
    <Dialog
      :visible="qcWatchId !== null"
      header="Instrument QC history"
      modal
      :style="{ width: '800px', maxWidth: '95vw' }"
      @update:visible="qcWatchId = null"
    >
      <InstrumentQCPanel v-if="qcWatchId !== null" :watch-id="qcWatchId" />
    </Dialog>
    <Dialog
      :visible="qcSnapshot !== null"
      header="Retained QC at run start"
      modal
      :style="{ width: '800px', maxWidth: '95vw' }"
      @update:visible="qcSnapshot = null"
    >
      <p>
        Evidence known at batch start. Later controls, maintenance and reviews do not rewrite this
        record. Predictions were not held.
      </p>
      <SavedValue :value="qcSnapshot" />
    </Dialog>
    <!-- Create Watch Dialog -->
    <Dialog
      v-model:visible="showCreateDialog"
      header="New Folder Watch"
      :modal="true"
      :style="{ width: '500px' }"
    >
      <div class="create-form">
        <div class="form-field">
          <label for="watch-workflow">Saved model or imported campaign solution</label>
          <Dropdown
            inputId="watch-workflow"
            v-model="newWatch.artifact_uid"
            :options="artifactOptions"
            optionLabel="label"
            optionValue="artifact_uid"
            optionDisabled="disabled"
            placeholder="Select model"
            class="w-full"
          />
          <small
            >Incoming files must carry the fitted feature order and axis units. Sherpa portable CSV
            preserves this metadata; plain CSV may not. Incompatible files produce a visible
            error.</small
          >
        </div>
        <PredictionUncertaintyEditor
          v-if="selectedWatchModel?.canonical_artifact_id"
          v-model="selectedUncertainty"
          :workflow-id="selectedWatchModel.workflow_id"
          :canonical-artifact-id="selectedWatchModel.canonical_artifact_id"
          :project-id="projectStore.currentProjectId"
          @valid="uncertaintyValid = $event"
        />
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
          <Button
            v-if="nativeFolderPicker"
            label="Choose folder…"
            icon="pi pi-folder-open"
            severity="secondary"
            :loading="choosingFolder"
            @click="chooseWatchFolder"
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
            <label
              for="watch-interval"
              title="Minimum time between polls. Scheduling resolution is one second; processing can delay the next poll."
              >Poll Interval (sec)</label
            >
            <InputNumber
              inputId="watch-interval"
              v-model="newWatch.poll_interval_sec"
              :min="1"
              class="w-full"
            />
          </div>
        </div>
        <div class="form-field">
          <label for="watch-asset">Scientific Asset ID</label>
          <InputText
            id="watch-asset"
            v-model="newWatch.asset_id"
            placeholder="Required only for multi-asset files (for example, a)"
            class="w-full"
          />
          <small>One exact asset identity is applied to every file in this watch.</small>
        </div>
      </div>
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="showCreateDialog = false" />
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
        <strong>{{ deleteTarget?.name }}</strong
        >?
      </p>
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="showDeleteDialog = false" />
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
import { ref, computed, onMounted, onBeforeUnmount, watch, reactive } from "vue";
import { useRoute, useRouter } from "vue-router";
import PredictionUncertaintyEditor from "./PredictionUncertaintyEditor.vue";
import InstrumentQCPanel from "./InstrumentQCPanel.vue";
import WatchDryRun from "./WatchDryRun.vue";
import QualificationPanel from "./QualificationPanel.vue";
import SavedValue from "@/views/models/SavedValue.vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import { focusSection } from "@/lib/sherpaAttention";
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
import ContextualActions from "@/components/ContextualActions.vue";
import { useAdvisorStore } from "@/stores/advisor";
import { useDeployStore } from "@/stores/deploy";
import { useProjectStore } from "@/stores/project";
import { useRunsStore } from "@/stores/runs";
import { useAppConfig } from "@/composables/useAppConfig";
import api from "@/api/client";
import type { FolderWatch, BatchPredictionResult, DeployApplication } from "@/types";

const toast = useToast();
const deployStore = useDeployStore();
const runsStore = useRunsStore();
const projectStore = useProjectStore();
const advisorStore = useAdvisorStore();
const { appMode, siteProfile } = useAppConfig();
const qcWatchId = ref<number | null>(null);
const dryRunWatchId = ref<number | null>(null);
const qcSnapshot = ref<Record<string, unknown> | null>(null);
const isHostedPro = computed(() => appMode?.value === "enterprise" && siteProfile?.value === "pro");

const tabIds = ["application", "watches", "history"] as const;
const activeTab = ref<string>("application");
const sectionTitle = computed(
  () =>
    ({ application: "Application", watches: "Folder Watches", history: "Prediction History" })[
      activeTab.value
    ] || "Application",
);
const applicationError = ref("");
let mounted = false;
let disposed = false;
let operationalTimer: ReturnType<typeof setInterval> | null = null;

// R4 — Sherpa Advisor scope routing for the Deploy tab.
const DEPLOY_SUBSCOPES = {
  application: "exports",
  watches: "integrations",
  history: "jobs",
} as const;
const DEPLOY_SUBSCOPE_TITLES: Record<string, string> = {
  exports: "Application",
  integrations: "Folder Watches",
  jobs: "Prediction History",
};

async function syncAdvisorForDeploySubtab(): Promise<void> {
  if (isHostedPro.value) return;
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  const subscopeKey =
    DEPLOY_SUBSCOPES[activeTab.value as keyof typeof DEPLOY_SUBSCOPES] ?? "integrations";
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
  focusSection(activeTab.value);
  void syncAdvisorForDeploySubtab();
  if (mounted) void syncOperationalState();
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
interface ArtifactOption {
  artifact_uid: string;
  application_handle?: string;
  canonical_artifact_id?: number;
  disabled?: boolean;
  workflow_id: number;
  workflow_version_id: number | null;
  name: string;
  label: string;
}
const artifactOptions = ref<ArtifactOption[]>([]);
const selectedApplicationId = ref<string | null>(null);
const applicationList = computed<DeployApplication[]>(() =>
  Array.isArray(deployStore.applications) ? deployStore.applications : [],
);
const selectedApplication = computed<DeployApplication | null>(
  () =>
    applicationList.value.find(
      (application) => application.application_id === selectedApplicationId.value,
    ) || null,
);
const selectedPrediction = ref<BatchPredictionResult | null>(null);
function watchTargetKey(watch: FolderWatch) {
  return watch.canonical_artifact_id
    ? `canonical:${watch.canonical_artifact_id}`
    : watch.artifact_uid;
}
function targetPayload(model: ArtifactOption) {
  if (model.application_handle) {
    return {
      application_handle: model.application_handle,
      artifact_uid: null,
      canonical_artifact_id: null,
    };
  }
  return model.canonical_artifact_id
    ? { artifact_uid: null, canonical_artifact_id: model.canonical_artifact_id }
    : { artifact_uid: model.artifact_uid, canonical_artifact_id: null };
}
function watchArtifactOptions(watch: FolderWatch) {
  const options = artifactOptions.value.filter((model) => model.workflow_id === watch.workflow_id);
  const key = watchTargetKey(watch);
  if (key && !options.some((model) => model.artifact_uid === key)) {
    return [{ artifact_uid: key, label: `${key} (unavailable)`, disabled: true }, ...options];
  }
  return options;
}
const route = useRoute();
const router = useRouter();
const deployActionContext = computed(() => {
  if (isHostedPro.value) return null;
  const projectId = projectStore.currentProjectId;
  const applicationHandle = selectedApplicationId.value;
  return projectId != null && applicationHandle
    ? { surface: "deploy" as const, projectId, applicationHandle }
    : null;
});
function selectApplication(applicationId: string): void {
  selectedApplicationId.value = applicationId;
  const application = applicationList.value.find((item) => item.application_id === applicationId);
  if (application)
    newWatch.artifact_uid =
      application.canonical_artifact_id != null
        ? `canonical:${application.canonical_artifact_id}`
        : application.artifact_uid;
}
function openQualifiedRuns() {
  void router.push({
    path: "/runs",
    query: {
      ...(projectStore.currentProjectId ? { project: projectStore.currentProjectId } : {}),
      tab: "run_history",
    },
  });
}
function inspectPrediction(prediction: BatchPredictionResult, projectId: number | null) {
  const nodes = prediction.retained_node_ids || [];
  if (nodes.length) {
    void router.push({
      path: `/runs/${prediction.run_id}`,
      query: {
        node: nodes[nodes.length - 1],
        view: "Results",
        ...(projectId ? { project: projectId } : {}),
      },
    });
  } else {
    selectedPrediction.value = prediction;
  }
}
let artifactRequest = 0;
let routeBindingApplied = false;
async function fetchArtifacts() {
  if (isHostedPro.value) return;
  const request = ++artifactRequest;
  const projectId = projectStore.currentProjectId;
  applicationError.value = "";
  if (projectId == null) return;
  try {
    if (typeof deployStore.fetchApplications === "function") {
      await deployStore.fetchApplications(projectId);
      if (!mounted || request !== artifactRequest || projectStore.currentProjectId !== projectId)
        return;
      artifactOptions.value = applicationList.value.map((application) => ({
        artifact_uid:
          application.canonical_artifact_id != null
            ? `canonical:${application.canonical_artifact_id}`
            : application.artifact_uid || application.application_id,
        application_handle: application.application_handle || undefined,
        canonical_artifact_id: application.canonical_artifact_id || undefined,
        workflow_id: application.workflow_id,
        workflow_version_id: application.workflow_version_id,
        name: application.name,
        label:
          application.origin === "saved_run"
            ? `${application.name} (${application.artifact_uid})`
            : `${application.name} — ${application.artifact_digest?.slice(0, 12) || "portable"}`,
      }));
      const requested = requestedApplicationId();
      if (
        !routeBindingApplied && !selectedApplicationId.value && requested &&
        applicationList.value.some((application) => application.application_id === requested)
      ) {
        selectApplication(requested);
        routeBindingApplied = true;
      }
      return;
    }
    const [response, canonical] = await Promise.all([
      api.get<ArtifactOption[]>("/models", {
        params: { project_id: projectId, deploy_ready: true, limit: 1000 },
      }),
      api.get<
        Array<{
          canonical_artifact_id: number;
          workflow_id: number;
          name: string;
          artifact_digest: string;
          deploy_ready: boolean;
          refusal: string | null;
        }>
      >("/deploy/canonical-targets", {
        params: { project_id: projectId },
      }),
    ]);
    if (request !== artifactRequest || projectStore.currentProjectId !== projectId) return;
    artifactOptions.value = response.data
      .filter((model) => model.workflow_id != null && model.workflow_version_id != null)
      .map((model) => ({
        ...model,
        label: `${model.name} (${model.artifact_uid})`,
      }));
    artifactOptions.value.push(
      ...canonical.data.map((target) => ({
        artifact_uid: `canonical:${target.canonical_artifact_id}`,
        canonical_artifact_id: target.canonical_artifact_id,
        workflow_id: target.workflow_id,
        workflow_version_id: null,
        name: target.name,
        label: `${target.name} — campaign ${target.artifact_digest.slice(0, 12)}${target.refusal ? `: ${target.refusal}` : ""}`,
        disabled: !target.deploy_ready,
      })),
    );
    const requested = artifactOptions.value.find(
      (model) => model.artifact_uid === route.query.artifact,
    );
    if (requested && !routeBindingApplied) {
      routeBindingApplied = true;
      newWatch.artifact_uid = requested.artifact_uid;
      showCreateDialog.value = true;
    }
  } catch (error: any) {
    if (request === artifactRequest) {
      artifactOptions.value = [];
      applicationError.value = "Applications could not be loaded.";
      toast.add({
        severity: "error",
        summary: "Deployment targets unavailable",
        detail:
          error?.response?.data?.detail ||
          "Could not load saved models and campaign solutions. Use Retry.",
        life: 6000,
      });
    }
  }
}

function requestedApplicationId(): string | null {
  const requested = typeof route.query.application === "string" ? route.query.application : null;
  if (requested && !requested.startsWith("run:")) return requested;
  if (requested?.startsWith("run:")) {
    const runId = Number(requested.slice(4));
    const application = applicationList.value.find((item) => item.source_run_id === runId);
    if (application) return application.application_id;
  }
  const artifact = typeof route.query.artifact === "string" ? route.query.artifact : null;
  if (artifact) {
    const saved = applicationList.value.find(
      (application) => application.artifact_uid === artifact,
    );
    if (saved) return saved.application_id;
    const canonicalId = artifact.startsWith("canonical:")
      ? Number(artifact.slice("canonical:".length))
      : NaN;
    const portable = applicationList.value.find(
      (application) => canonicalId > 0 && application.canonical_artifact_id === canonicalId,
    );
    if (portable) return portable.application_id;
    return artifact.startsWith("artifact:") || artifact.startsWith("canonical:")
      ? artifact
      : `artifact:${artifact}`;
  }
  const canonical = Number(route.query.canonical_artifact_id);
  return Number.isSafeInteger(canonical) && canonical > 0 ? `canonical:${canonical}` : null;
}

// Watch CRUD state
const showCreateDialog = ref(false);
const headerActionItems = computed(() => {
  if (isHostedPro.value) return [];
  return [
    {
      label: "New Watch",
      visible: true,
      disabled: deployStore.loading || deployStore.applicationsLoading,
      icon: "pi pi-plus",
      command: () => {
        showCreateDialog.value = true;
      },
    },
  ];
});
const creating = ref(false);
const nativeFolderPicker = window.spectraDesktop?.chooseWatchFolder;
const choosingFolder = ref(false);
const chooseWatchFolder = async () => {
  if (!nativeFolderPicker || choosingFolder.value) return;
  choosingFolder.value = true;
  try {
    const folder = await nativeFolderPicker();
    if (folder) newWatch.folder_path = folder;
  } catch {
    toast.add({
      severity: "error",
      summary: "Folder selection unavailable",
      detail: "Try again or enter the folder path.",
      life: 5000,
    });
  } finally {
    choosingFolder.value = false;
  }
};

const newWatch = reactive({
  artifact_uid: null as string | null,
  name: "",
  folder_path: "",
  file_pattern: "*",
  poll_interval_sec: 60,
  asset_id: "",
});

const showDeleteDialog = ref(false);
const deleteTarget = ref<FolderWatch | null>(null);
const deletingWatch = ref(false);

// Prediction expansion
const expandedRuns = ref<Record<string, boolean>>({});
const predictions = ref<Record<number, BatchPredictionResult[]>>({});
const loadingPredictions = ref<Record<number, boolean>>({});
const predictionErrors = ref<Record<number, string>>({});
let predictionScope = 0;
watch(
  () => projectStore.currentProjectId,
  () => {
    predictionScope += 1;
    predictions.value = {};
    predictionErrors.value = {};
    loadingPredictions.value = {};
    expandedRuns.value = {};
  },
);
async function loadPredictions(runId: number) {
  if (loadingPredictions.value[runId]) return;
  const scope = predictionScope;
  loadingPredictions.value[runId] = true;
  delete predictionErrors.value[runId];
  try {
    const values = await runsStore.fetchPredictions(runId);
    if (scope === predictionScope) predictions.value[runId] = values;
  } catch (error: any) {
    if (scope === predictionScope)
      predictionErrors.value[runId] = String(
        error?.response?.data?.detail || error?.message || "Results could not be loaded.",
      );
  } finally {
    if (scope === predictionScope) loadingPredictions.value[runId] = false;
  }
}

const selectedUncertainty = ref<Record<string, unknown> | null>(null);
const uncertaintyValid = ref(true);
const selectedWatchModel = computed(() =>
  artifactOptions.value.find((model) => model.artifact_uid === newWatch.artifact_uid),
);
watch(
  () => newWatch.artifact_uid,
  () => {
    selectedUncertainty.value = null;
    uncertaintyValid.value = true;
  },
);
const canCreate = computed(
  () =>
    artifactOptions.value.some(
      (model) => model.artifact_uid === newWatch.artifact_uid && !model.disabled,
    ) &&
    newWatch.name.trim() &&
    newWatch.folder_path.trim() &&
    uncertaintyValid.value,
);
watch(
  () => projectStore.currentProjectId,
  () => {
    artifactRequest++;
    selectedApplicationId.value = null;
    artifactOptions.value = [];
    workflowOptions.value = [];
    showCreateDialog.value = false;
    newWatch.artifact_uid = null;
    qcWatchId.value = null;
    dryRunWatchId.value = null;
    selectedPrediction.value = null;
    deployStore.resetProjectScope?.();
    if (mounted && !isHostedPro.value) void refreshAll();
  },
);

onMounted(async () => {
  const linkedProjectId = Number(route.query.project);
  if (
    Number.isSafeInteger(linkedProjectId) &&
    linkedProjectId > 0 &&
    linkedProjectId !== projectStore.currentProjectId
  )
    await projectStore.selectProject(linkedProjectId);
  else await projectStore.ensureProjectForBrowserTab();
  if (disposed) return;
  mounted = true;
  if (isHostedPro.value) return;
  const tab = String(route.query.tab || "application");
  activeTab.value =
    tab === "integrations"
      ? "watches"
      : tab === "jobs"
        ? "history"
        : tabIds.includes(tab as (typeof tabIds)[number])
          ? tab
          : "application";
  await refreshAll();
  if (disposed) return;
  window.addEventListener("focus", syncOperationalState);
  operationalTimer = setInterval(() => {
    if (!document.hidden) void syncOperationalState();
  }, 15000);
});
onBeforeUnmount(() => {
  disposed = true;
  mounted = false;
  artifactRequest++;
  predictionScope++;
  deployStore.resetProjectScope?.();
  if (operationalTimer) clearInterval(operationalTimer);
  window.removeEventListener("focus", syncOperationalState);
});

// Failed requests are distinct from a confirmed empty response, and remain retryable.
watch(
  expandedRuns,
  (expanded) => {
    for (const run of deployStore.deployRuns) {
      if (
        expanded[String(run.id)] &&
        !predictions.value[run.id] &&
        !predictionErrors.value[run.id]
      ) {
        void loadPredictions(run.id);
      }
    }
  },
  { deep: true },
);

async function syncOperationalState() {
  const projectId = projectStore.currentProjectId;
  if (!mounted || isHostedPro.value || projectId == null) return;
  await Promise.all([
    deployStore.fetchWatches(projectId),
    deployStore.fetchDeployRuns(undefined, undefined, projectId),
    !showCreateDialog.value ? fetchArtifacts() : Promise.resolve(),
  ]);
  if (!mounted || projectId !== projectStore.currentProjectId) return;
  for (const run of deployStore.deployRuns) {
    if (expandedRuns.value[String(run.id)]) void loadPredictions(run.id);
  }
}
async function refreshAll() {
  if (isHostedPro.value) return;
  const projectId = projectStore.currentProjectId;
  await syncOperationalState();
  if (!mounted || projectId == null || projectId !== projectStore.currentProjectId) return;
  try {
    const response = await api.get<WorkflowOption[]>("/workflows", {
      params: { project_id: projectId },
    });
    if (mounted && projectId === projectStore.currentProjectId)
      workflowOptions.value = response.data;
  } catch {
    if (projectId === projectStore.currentProjectId) workflowOptions.value = [];
  }
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
      detail: error?.response?.data?.detail || error?.message || "Could not toggle watch",
      life: 3000,
    });
  }
}

function exportWatchUncertainty(watch: FolderWatch) {
  if (!watch.uncertainty_record) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(watch.uncertainty_record, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `watch-${watch.id}-prediction-intervals.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
async function handleRebind(watchId: number, artifactUid: string) {
  try {
    const model = artifactOptions.value.find(
      (item) => item.artifact_uid === artifactUid && !item.disabled,
    );
    if (!model) return;
    await deployStore.updateWatch(watchId, {
      ...targetPayload(model),
      uncertainty_record: null,
      uncertainty_population: null,
    });
    toast.add({
      severity: "success",
      summary: "Model bound; previous interval evidence cleared",
      life: 3000,
    });
  } catch (error: any) {
    toast.add({
      severity: "error",
      summary: "Model not bound",
      detail: error?.response?.data?.detail || error?.message,
      life: 5000,
    });
  }
}

async function handleCreate() {
  if (!canCreate.value) return;
  const model = artifactOptions.value.find((model) => model.artifact_uid === newWatch.artifact_uid);
  if (!model) return;
  creating.value = true;
  try {
    await deployStore.createWatch({
      workflow_id: model.workflow_id,
      uncertainty_record: selectedUncertainty.value,
      uncertainty_population: selectedUncertainty.value
        ? String(selectedUncertainty.value.intended_population)
        : null,
      ...targetPayload(model),
      name: newWatch.name.trim(),
      folder_path: newWatch.folder_path.trim(),
      file_pattern: newWatch.file_pattern || "*",
      poll_interval_sec: newWatch.poll_interval_sec,
      asset_id: newWatch.asset_id.trim() || null,
    });
    showCreateDialog.value = false;
    // Reset form
    newWatch.artifact_uid = null;
    newWatch.name = "";
    newWatch.folder_path = "";
    newWatch.file_pattern = "*";
    newWatch.poll_interval_sec = 60;
    newWatch.asset_id = "";
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

function getBatchFileCount(run: {
  results_summary: Record<string, Record<string, unknown>>;
}): string {
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
.campaign-validation-star {
  color: #eab308;
  font-size: 1.6rem;
}
.page-content {
  display: flex;
  flex-direction: column;
  padding: 0 1rem;
  color: var(--text-color);
}

:global(.content:has(.deploy-content)) {
  background: #e4e0fa;
}

.hosted-pro-deploy {
  display: flex;
  max-width: 640px;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.65rem;
  padding: 2rem;
  border: 1px solid rgba(99, 102, 241, 0.2);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
}

.hosted-pro-deploy i {
  color: #4338ca;
  font-size: 1.75rem;
}

.hosted-pro-deploy h2,
.hosted-pro-deploy p {
  margin: 0;
}

.hosted-pro-deploy p {
  color: #475569;
  line-height: 1.55;
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

.released-applications {
  padding: 1rem;
  border: 1px solid rgba(99, 102, 241, 0.18);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.62);
}

.section-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
}

.section-heading h2 {
  margin: 0;
  color: var(--text-color);
  font-size: 1.15rem;
}

.section-heading p {
  margin: 0.25rem 0 0;
  color: #64748b;
}

.selected-application {
  color: #4338ca;
  font-size: 0.875rem;
  font-weight: 600;
}

.application-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin-top: 1rem;
}

.application-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 0.25rem 0.75rem;
  min-width: 220px;
  padding: 0.75rem;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  color: var(--text-color);
  cursor: pointer;
  text-align: left;
}

.application-card.selected {
  border-color: #6366f1;
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.18);
}

.application-card__name {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.application-card small {
  grid-column: 1 / -1;
  color: #64748b;
}

.empty-state.compact,
.loading-state.compact {
  padding: 1rem;
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


</style>
