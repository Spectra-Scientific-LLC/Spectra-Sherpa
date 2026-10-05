<template>
  <section class="project-content">
    <!-- Header --------------------------------------------------------- -->
    <WorkspaceHeader title="Project" :actions="headerActionItems">
        <Button
          label="New Project" icon="pi pi-plus" class="p-button-sm"
          :disabled="appConfig?.siteProfile === 'demo'"
          @click="editingProject = null; dialogVisible = true" />
        <Button
          v-if="isServerBacked && !qualified && projectStore.currentProjectId"
          label="Memory Map"
          icon="pi pi-sitemap"
          class="p-button-text p-button-sm"
          @click="openMemoryMap"
        />
        <Button
          v-if="projectStore.currentProjectId"
          label="Audit"
          icon="pi pi-shield"
          class="p-button-text p-button-sm"
          @click="openProjectAudit"
        />
        <template v-if="activeProject">
          <Button
            label="Edit"
            :disabled="qualified && !availability?.write"
            icon="pi pi-pencil"
            class="p-button-text p-button-sm"
            @click="showEditProjectDialog(activeProject)"
          />
          <Button
            label="Export"
            icon="pi pi-download"
            class="p-button-text p-button-sm"
            :disabled="exportInProgress || (qualified && !availability?.export)"
            :loading="exportInProgress"
            @click="onExportProject(activeProject)"
          />
          <Button v-if="qualified" label="Remove Project" icon="pi pi-trash" class="p-button-text p-button-danger p-button-sm"
            :disabled="!availability?.delete" @click="removeDialog = true; removeName = ''" />
        </template>
    </WorkspaceHeader>

    <p v-if="qualified" role="status">{{ availabilityError || availability?.limitations }}</p>
    <!-- Loading -------------------------------------------------------- -->
    <div v-if="projectStore.isLoading && !projectStore.projects.length" class="empty-state">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <p>Loading projects…</p>
    </div>

    <!-- No projects at all -->
    <div v-else-if="!projectStore.projects.length" class="empty-state">
      <p class="empty-state__title">No projects yet.</p>
      <p class="empty-state__hint">
        Choose New Project to start with your own data, or New Analysis on the Dashboard.
      </p>
    </div>

    <!-- Projects exist but none selected -->
    <div v-else-if="!activeProject" class="empty-state">
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
      <div v-if="objectErrors.length" role="alert">Could not load {{ objectErrors.join(", ") }}.
        <Button label="Retry" @click="loadObjects(activeProject.id)" />
      </div>
      <!-- Active project header section ----------------------------- -->
      <section class="current-section">
        <div class="current-head">
          <div class="current-head__main">
            <span class="eyebrow">Current Project</span>
            <h2 class="current-name">{{ activeProject.name }}</h2>
            <p v-if="activeProject.description" class="current-desc">
              {{ activeProject.description }}
            </p>
          </div>
          <span class="current-time" :title="absoluteTimestamp(activeProject.updated_at)">
            {{ formatRelative(activeProject.updated_at) }}
          </span>
        </div>

        <div class="current-meta">
          <span v-if="activeProject.technique">{{ activeProject.technique }}</span>
          <span v-if="activeProject.sample_type">{{ activeProject.sample_type }}</span>
          <span
            ><strong>{{ activeProject.experiment_count }}</strong> data</span
          >
          <span
            ><strong>{{ activeProject.workflow_count }}</strong> workflows</span
          >
          <span><strong>{{ runTotal ?? "—" }}</strong> runs</span>
          <span><strong>{{ activeProject.model_count }}</strong> artifacts</span>
          <span v-for="collection in collections" :key="collection.key"><strong>{{ collection.total }}</strong> {{ collection.label.toLowerCase() }}</span>
          <span>created {{ formatRelative(activeProject.created_at) }}</span>
        </div>


      </section>

      <section v-if="canonicalProjectMetadata" class="canonical-project-panel">
        <div class="canonical-project-panel__copy">
          <span class="eyebrow">Reviewed Scientific Package</span>
          <h3>
            {{
              canonicalApplicationReady ? "Ready to apply locally" : "Choose local inference input"
            }}
          </h3>
          <p>
            The fitted artifact and application DAG passed integrity checks during import. The
            package contains no sample data. Bind a file for interactive application, or configure a local folder watch for incoming files.
          </p>
          <p v-if="canonicalArtifactDigest" class="canonical-project-panel__digest">
            Artifact {{ canonicalArtifactDigest }}
          </p>
        </div>

        <CampaignReproduction v-if="appMode === 'local' && activeProject" :key="activeProject.id" :project-id="activeProject.id" />

        <Button v-if="appMode === 'local'" label="Configure folder watch" icon="pi pi-folder-open"
          @click="router.push({ path: '/deploy', query: { project: String(activeProject?.id) } })" />

        <div v-if="canonicalApplicationReady" class="canonical-project-panel__actions">
          <span class="lifecycle-pill ready">Local data bound</span>
          <Button
            label="Open application workflow"
            icon="pi pi-arrow-right"
            iconPos="right"
            class="p-button-sm"
            @click="openCanonicalWorkflow"
          />
        </div>

        <div v-else-if="canonicalDependencyBlocked" class="canonical-project-panel__blocked">
          <span class="lifecycle-pill failed">Dependency blocked</span>
          <p>{{ canonicalDependencyRemediation }}</p>
        </div>

        <div v-else class="canonical-binding-form">
          <div v-if="!experiments.length" class="canonical-binding-form__empty">
            <p>For interactive application, add a local dataset to this project. Folder watches read incoming files directly.</p>
            <Button
              label="Add local data"
              icon="pi pi-database"
              class="p-button-sm p-button-outlined"
              @click="openData"
            />
          </div>
          <template v-else>
            <label>
              <span>Dataset</span>
              <Dropdown
                v-model="canonicalExperimentId"
                :options="canonicalExperimentOptions"
                optionLabel="label"
                optionValue="value"
                placeholder="Choose a dataset"
                class="canonical-binding-form__select"
              />
            </label>
            <label>
              <span>Exact file</span>
              <Dropdown
                v-model="canonicalFileId"
                :options="canonicalFileOptions"
                optionLabel="label"
                optionValue="value"
                :loading="canonicalFilesLoading"
                :disabled="canonicalExperimentId === null"
                placeholder="Choose a file"
                class="canonical-binding-form__select"
              />
            </label>
            <label v-if="canonicalAssets.length">
              <span>Scientific asset</span>
              <Dropdown
                v-model="canonicalAssetId"
                :options="canonicalAssetOptions"
                optionLabel="label"
                optionValue="value"
                :loading="canonicalAssetsLoading"
                placeholder="Choose an exact asset"
                class="canonical-binding-form__select"
              />
            </label>
            <small v-if="canonicalAssetError" class="canonical-binding-form__error">
              {{ canonicalAssetError }}
            </small>
            <Button
              label="Bind data to application DAG"
              icon="pi pi-link"
              class="p-button-sm"
              :loading="canonicalBinding"
              :disabled="canonicalBindingDisabled"
              @click="bindCanonicalData"
            />
          </template>
        </div>
      </section>

      <!-- Data ------------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Data</span>
            <span class="object-section__count">{{ experiments.length }}</span>
          </div>
          <Button
            label="Data"
            icon="pi pi-arrow-right"
            iconPos="right"
            class="p-button-text p-button-sm"
            @click="openData"
          />
        </div>

        <div v-if="experiments.length" class="object-list">
          <div
            v-for="experiment in experiments"
            :key="experiment.id"
            class="object-row"
            role="button"
            tabindex="0"
            @click="openData"
            @keydown.enter.prevent="openData"
            @keydown.space.prevent="openData"
          >
            <span class="dot" :class="datasetStageTone(experiment)"></span>
            <div class="object-row__main">
              <strong>{{ experiment.name }}</strong>
              <small>
                <span
                  >{{ experiment.file_count }} file{{
                    experiment.file_count === 1 ? "" : "s"
                  }}</span
                >
                <span v-if="experimentDescription(experiment)">{{
                  experimentDescription(experiment)
                }}</span>
              </small>
              <div v-if="experimentFacts(experiment).length" class="data-facts">
                <span v-for="fact in experimentFacts(experiment)" :key="fact">{{ fact }}</span>
              </div>
            </div>
            <span class="object-row__time" :title="absoluteTimestamp(experiment.created_at)">
              {{ formatRelative(experiment.created_at) }}
            </span>
            <span class="lifecycle-pill" :class="datasetStageTone(experiment)">
              {{ datasetStageLabel(experiment) }}
            </span>
          </div>
        </div>
        <p v-else class="object-empty">{{ objectsLoading ? "Loading data…" : objectErrors.includes("Data") ? "Data unavailable." : "No datasets in this project." }}</p>
      </section>

      <!-- Workflows -------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Workflows</span>
            <span class="object-section__count">{{ workflows.length }}</span>
          </div>
          <Button
            label="Workflows"
            icon="pi pi-arrow-right"
            iconPos="right"
            class="p-button-text p-button-sm"
            @click="openWorkflows"
          />
        </div>

        <div v-if="workflows.length" class="object-list">
          <div
            v-for="workflow in workflows"
            :key="workflow.id"
            class="object-row"
            role="button"
            tabindex="0"
            @click="openWorkflows"
            @keydown.enter.prevent="openWorkflows"
            @keydown.space.prevent="openWorkflows"
          >
            <span class="dot" :class="workflowStageTone(workflow)"></span>
            <div class="object-row__main">
              <strong>{{ workflow.name }}</strong>
              <small>
                <span v-if="workflow.created_from_template_name"
                  >from {{ workflow.created_from_template_name }}</span
                >
                <span v-else-if="workflow.created_from_workflow_name"
                  >copied from {{ workflow.created_from_workflow_name }}</span
                >
                <span
                  >{{ workflow.node_count ?? 0 }} node{{ workflow.node_count === 1 ? "" : "s" }} ·
                  {{ workflow.edge_count ?? 0 }} edge{{
                    workflow.edge_count === 1 ? "" : "s"
                  }}</span
                >
              </small>
            </div>
            <span class="object-row__time" :title="absoluteTimestamp(workflow.updated_at)">
              {{ formatRelative(workflow.updated_at) }}
            </span>
            <span class="lifecycle-pill" :class="workflowStageTone(workflow)">
              {{ workflowStageLabel(workflow) }}
            </span>
          </div>
        </div>
        <p v-else class="object-empty">{{ objectsLoading ? "Loading workflows…" : objectErrors.includes("Workflows") ? "Workflows unavailable." : "No workflows in this project." }}</p>
      </section>

      <section class="object-section" data-testid="project-runs">
        <div class="object-section__head">
          <div class="object-section__title"><span class="eyebrow">Runs</span><span class="object-section__count">{{ runTotal ?? "—" }}</span></div>
          <Button label="Runs" icon="pi pi-arrow-right" iconPos="right" class="p-button-text p-button-sm" @click="router.push('/runs?tab=run_history')" />
        </div>
        <div v-for="run in runs" :key="run.id" class="object-row" role="button" tabindex="0"
          @click="openRun(run.id)" @keydown.enter.prevent="openRun(run.id)" @keydown.space.prevent="openRun(run.id)">
          <div class="object-row__main"><strong>{{ run.name || 'Saved run' }}</strong><small>{{ run.run_kind }}</small></div>
          <span class="object-row__time">{{ formatRelative(run.executed_at) }}</span><span>{{ run.status }}</span>
        </div>
        <p v-if="!runs.length" class="object-empty">{{ objectsLoading ? "Loading runs…" : runTotal === null ? "Runs unavailable." : "No saved runs in this project." }}</p>
        <small v-if="runTotal !== null && runTotal > runs.length">Showing {{ runs.length }} of {{ runTotal }} runs.</small>
      </section>
      <section v-for="collection in collections" :key="collection.key" class="object-section">
        <div class="object-section__head">
          <div class="object-section__title"><span class="eyebrow">{{ collection.label }}</span><span class="object-section__count">{{ collection.total }}</span></div>
          <Button :label="collection.label" icon="pi pi-arrow-right" iconPos="right" class="p-button-text p-button-sm" @click="router.push(collection.to)" />
        </div>
        <div v-for="item in collection.items" :key="item.id" class="object-row collection-summary">
          <div class="object-row__main"><strong>{{ item.title }}</strong><small>{{ item.status }}</small></div>
          <span class="object-row__time">{{ formatRelative(item.createdAt) }}</span>
        </div>
        <p v-if="!collection.items.length" class="object-empty">No {{ collection.label.toLowerCase() }} in this project.</p>
        <small v-if="collection.total > collection.items.length">Showing {{ collection.items.length }} of {{ collection.total }} {{ collection.label.toLowerCase() }}.</small>
      </section>
      <!-- Artifacts -------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Artifacts</span>
            <span class="object-section__count">{{ activeProject.model_count }}</span>
          </div>
          <Button
            label="Artifacts"
            icon="pi pi-arrow-right"
            iconPos="right"
            class="p-button-text p-button-sm"
            @click="openArtifacts"
          />
        </div>

        <div v-if="models.length" class="object-list">
          <div
            v-for="model in models"
            :key="model.artifact_uid"
            class="object-row"
            role="button"
            tabindex="0"
            @click="openArtifacts"
            @keydown.enter.prevent="openArtifacts"
            @keydown.space.prevent="openArtifacts"
          >
            <span class="dot ready"></span>
            <div class="object-row__main">
              <strong>{{ model.name }}</strong>
              <small>{{ modelSubtitle(model) }}</small>
            </div>
            <span
              class="object-row__time"
              :title="absoluteTimestamp(model.updated_at || model.created_at)"
            >
              {{ formatRelative(model.updated_at || model.created_at) }}
            </span>
            <span class="lifecycle-pill ready">Trained</span>
          </div>
        </div>
        <p v-else class="object-empty">{{ objectsLoading ? "Loading artifacts…" : objectErrors.includes("Artifacts") ? "Artifacts unavailable." : "No artifacts in this project yet." }}</p>
        <small v-if="activeProject.model_count > models.length">Showing {{ models.length }} of {{ activeProject.model_count }} artifacts.</small>
      </section>
    </template>

    <Dialog v-model:visible="removeDialog" header="Remove project" modal>
      <p>This removes the project from your catalog. Its data, history and commercial records are retained.</p>
      <label for="remove-project-name">Type {{ activeProject?.name }} to confirm</label>
      <input id="remove-project-name" v-model="removeName" />
      <template #footer><Button label="Cancel" @click="removeDialog = false" />
        <Button label="Remove project" severity="danger" :disabled="removeName !== activeProject?.name" @click="removeQualifiedProject" /></template>
    </Dialog>
    <!-- Dialogs ----------------------------------------------------- -->
    <ProjectDialog
      v-model:visible="dialogVisible"
      :edit-project="editingProject"
      @create="onCreateProject"
      @update="onUpdateProject"
    />

  </section>
</template>

<script setup lang="ts">
import { regressionMetricPresentation, regressionMetricQualification } from "@/utils/regressionMetricPresentation";
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import Dropdown from "primevue/dropdown";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import CampaignReproduction from "./CampaignReproduction.vue";
import ProjectDialog, { type ProjectFormData } from "@/components/ProjectDialog.vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import { projectCollectionsLoader, type ProjectCollection } from "@/lib/projectCollections";
import { useAdvisorStore } from "@/stores/advisor";
import { useAppConfig } from "@/composables/useAppConfig";
import { useProjectAvailability } from "@/composables/useProjectAvailability";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore, type WorkflowListItem } from "@/stores/workflow";
import type {
  ExperimentFile,
  ExperimentFileAssets,
  ExperimentSummary,
  ProjectSummary,
  ScientificAsset,
  RunListItem,
} from "@/types";

interface ModelRow {
  artifact_uid: string;
  name: string;
  model_type: string;
  n_features: number;
  n_components: number | null;
  metrics?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string;
}

const router = useRouter();
const toast = useToast();
const projectStore = useProjectStore();
const workflowStore = useWorkflowStore();
const advisorStore = useAdvisorStore();
const { qualified, availability, error: availabilityError } = useProjectAvailability();
const removeDialog = ref(false);
const removeName = ref("");
async function removeQualifiedProject() {
  if (!activeProject.value || !availability.value?.delete) return;
  if (await projectStore.deleteProject(activeProject.value.id, removeName.value)) removeDialog.value = false;
  else toast.add({ severity: "error", summary: "Project not removed", detail: projectStore.error || undefined, life: 5000 });
}
const { config: appConfig, appMode } = useAppConfig();

const isServerBacked = computed(() => appMode.value !== "local");
const activeProject = computed(() => projectStore.currentProject);
const exportInProgress = computed(
  () => !!activeProject.value && projectStore.exportingProjectIds.includes(activeProject.value.id),
);
const headerActionItems = computed(() => [
  ...(activeProject.value ? [
    { label: "Edit", icon: "pi pi-pencil", disabled: qualified.value && !availability.value?.write,
      command: () => activeProject.value && showEditProjectDialog(activeProject.value) },
    { label: "Export", icon: "pi pi-download", disabled: exportInProgress.value || (qualified.value && !availability.value?.export),
      command: () => activeProject.value && onExportProject(activeProject.value) },
    ...(qualified.value ? [{ label: "Remove Project", icon: "pi pi-trash", disabled: !availability.value?.delete,
      command: () => { removeDialog.value = true; removeName.value = ""; } }] : []),
  ] : []),
  {
    label: "New Project",
    icon: "pi pi-plus",
    disabled: appConfig.value?.siteProfile === "demo",
    command: () => { editingProject.value = null; dialogVisible.value = true; },
  },
  ...(isServerBacked.value && !qualified.value && projectStore.currentProjectId
    ? [
        {
          label: "Memory Map",
          icon: "pi pi-sitemap",
          command: openMemoryMap,
        },
      ]
    : []),
  ...(projectStore.currentProjectId
    ? [
        {
          label: "Audit",
          icon: "pi pi-shield",
          command: openProjectAudit,
        },
      ]
    : []),
]);

const dialogVisible = ref(false);
const editingProject = ref<ProjectSummary | null>(null);

// Richer per-object lists than what ProjectDetail.experiments / .workflows /
// .models carry — ExperimentBrief/WorkflowBrief don't include created_at /
// node_count / metrics, all of which the lifecycle line needs.
const experiments = ref<ExperimentSummary[]>([]);
const workflows = ref<WorkflowListItem[]>([]);
const models = ref<ModelRow[]>([]);
const runs = ref<RunListItem[]>([]);
const runTotal = ref<number | null>(null);
const collections = ref<ProjectCollection[]>([]);
const objectErrors = ref<string[]>([]);
const objectsLoading = ref(false);
let objectRequest = 0;
let disposed = false;
onUnmounted(() => { disposed = true; ++objectRequest; });
watch(projectCollectionsLoader, () => { if (projectStore.currentProjectId) void loadObjects(projectStore.currentProjectId); });
const canonicalExperimentId = ref<number | null>(null);
const canonicalFileId = ref<number | null>(null);
const canonicalFiles = ref<ExperimentFile[]>([]);
const canonicalFilesLoading = ref(false);
const canonicalAssets = ref<ScientificAsset[]>([]);
const canonicalAssetId = ref<string | null>(null);
const canonicalAssetsLoading = ref(false);
const canonicalAssetError = ref("");
const canonicalBinding = ref(false);

const canonicalProjectMetadata = computed<Record<string, unknown> | null>(() => {
  const value = activeProject.value?.metadata?.canonical_project;
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
});
const canonicalArtifactDigest = computed(() => {
  const value = canonicalProjectMetadata.value?.artifact_digest;
  return typeof value === "string" ? value : null;
});
const canonicalApplicationWorkflowId = computed(() => {
  const value = canonicalProjectMetadata.value?.application_workflow_id;
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null;
});
const canonicalWorkflow = computed(
  () =>
    workflows.value.find((workflow) => workflow.id === canonicalApplicationWorkflowId.value) ??
    null,
);
const canonicalApplicationReady = computed(() =>
  ["active", "ready", "completed", "success"].includes(
    (canonicalWorkflow.value?.status ?? "").toLowerCase(),
  ),
);
const canonicalDependencyBlocked = computed(
  () => canonicalProjectMetadata.value?.package_status === "dependency_blocked",
);
const canonicalDependencyRemediation = computed(() => {
  const readiness = canonicalProjectMetadata.value?.dependency_readiness;
  if (!readiness || typeof readiness !== "object" || Array.isArray(readiness)) {
    return "Install the application dependencies required by this canonical package.";
  }
  const remediation = (readiness as Record<string, unknown>).remediation;
  return Array.isArray(remediation) && remediation.every((value) => typeof value === "string")
    ? remediation.join(" ")
    : "Install the application dependencies required by this canonical package.";
});
const canonicalExperimentOptions = computed(() =>
  experiments.value.map((experiment) => ({
    label: `${experiment.name} (${experiment.file_count} file${experiment.file_count === 1 ? "" : "s"})`,
    value: experiment.id,
  })),
);
const canonicalFileOptions = computed(() =>
  canonicalFiles.value.map((file) => ({
    label: `${file.file_path.split(/[\\/]/).pop() ?? file.file_path} · ${file.stage}`,
    value: file.id,
  })),
);
const selectedCanonicalFile = computed(
  () => canonicalFiles.value.find((file) => file.id === canonicalFileId.value) ?? null,
);
const canonicalAssetOptions = computed(() =>
  canonicalAssets.value.map((asset) => ({
    label: `${asset.title || asset.asset_id} · ${asset.shape.join(" × ")}`,
    value: asset.asset_id,
  })),
);
const canonicalBindingDisabled = computed(
  () =>
    canonicalBinding.value ||
    canonicalWorkflow.value === null ||
    canonicalExperimentId.value === null ||
    selectedCanonicalFile.value === null ||
    canonicalAssetsLoading.value ||
    canonicalAssets.value.length === 0 ||
    canonicalAssetId.value === null,
);

// Lifecycle helpers ----------------------------------------------------

// "Linked" means at least one of this project's workflows references the
// dataset via primary_data_source_id or data_source_ids — i.e. the dataset
// has graduated from "just imported" to "actively used".
const linkedExperimentIds = computed<Set<number>>(() => {
  const set = new Set<number>();
  const wfs = activeProject.value?.workflows || [];
  for (const wf of wfs) {
    if (wf.primary_data_source_id != null) set.add(wf.primary_data_source_id);
    if (wf.data_source_ids) {
      for (const id of wf.data_source_ids) set.add(id);
    }
  }
  return set;
});

const projectExperimentsById = computed(() => {
  const map = new Map<number, { description?: string | null; facts?: string[] }>();
  for (const experiment of activeProject.value?.experiments ?? []) {
    map.set(experiment.id, {
      description: experiment.description,
      facts: experiment.facts ?? [],
    });
  }
  return map;
});

type Tone = "ready" | "neutral" | "empty" | "failed" | "running" | "";

function datasetStageTone(exp: ExperimentSummary): Tone {
  if (exp.file_count === 0) return "empty";
  if (linkedExperimentIds.value.has(exp.id)) return "ready";
  return "neutral";
}

function datasetStageLabel(exp: ExperimentSummary): string {
  if (exp.file_count === 0) return "Empty";
  if (linkedExperimentIds.value.has(exp.id)) return "Linked";
  return "Imported";
}

function experimentDescription(exp: ExperimentSummary): string | null {
  return projectExperimentsById.value.get(exp.id)?.description ?? exp.description ?? null;
}

function experimentFacts(exp: ExperimentSummary): string[] {
  return projectExperimentsById.value.get(exp.id)?.facts ?? [];
}

function workflowStageTone(wf: WorkflowListItem): Tone {
  const status = (wf.status || "").toLowerCase();
  if (["error", "failed"].includes(status)) return "failed";
  if (["completed", "ready", "active", "success"].includes(status)) return "ready";
  if (status === "running") return "running";
  if ((wf.node_count ?? 0) === 0) return "empty";
  return "neutral";
}

function workflowStageLabel(wf: WorkflowListItem): string {
  const status = (wf.status || "").toLowerCase();
  if (["error", "failed"].includes(status)) return "Failed";
  if (["completed", "ready", "active", "success"].includes(status)) return "Completed";
  if (status === "running") return "Running";
  if ((wf.node_count ?? 0) === 0) return "Empty";
  return "Draft";
}

function modelSubtitle(model: ModelRow): string {
  const parts: string[] = [model.model_type, `${model.n_features} features`];
  if (model.n_components != null) {
    parts.push(`${model.n_components} components`);
  }
  const metric = modelMetricSummary(model.metrics ?? null);
  if (metric) parts.push(metric);
  return parts.join(" · ");
}

function modelMetricSummary(metrics: Record<string, unknown> | null): string | null {
  if (!metrics) return null;
  const qualification = regressionMetricQualification(metrics);
  if (qualification) return qualification;
  metrics = regressionMetricPresentation(metrics);
  for (const key of ["r2", "rmse", "accuracy", "f1", "mae"]) {
    const value = metrics[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return `${key.toUpperCase()} ${formatMetric(value)}`;
    }
  }
  return null;
}

function formatMetric(value: number): string {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

// Data loading --------------------------------------------------------

onMounted(async () => {
  await projectStore.fetchProjects();
  const projectId = projectStore.currentProjectId ?? projectStore.recentProjects[0]?.id ?? null;
  if (projectId != null) {
    await Promise.allSettled([projectStore.fetchProject(projectId), loadObjects(projectId)]);
  }
  void syncAdvisorForProject();
});

watch(
  () => projectStore.currentProjectId,
  async (next) => {
    canonicalExperimentId.value = null; canonicalFileId.value = null;
    if (next != null) {
      await loadObjects(next);
      void syncAdvisorForProject();
    } else {
      ++objectRequest;
      experiments.value = []; workflows.value = []; models.value = []; runs.value = []; runTotal.value = null; collections.value = []; objectErrors.value = []; objectsLoading.value = false;
    }
  },
);

watch(canonicalExperimentId, async (experimentId, _, onCleanup) => {
  let current = true;
  onCleanup(() => { current = false; });
  canonicalFileId.value = null;
  canonicalFiles.value = [];
  if (experimentId === null) return;
  canonicalFilesLoading.value = true;
  try {
    const response = await api.get<ExperimentFile[]>(`/experiments/${experimentId}/files`);
    if (!current) return;
    canonicalFiles.value = response.data;
    if (response.data.length === 1) canonicalFileId.value = response.data[0].id;
  } catch (err) {
    if (!current) return;
    console.warn("[project] failed to load canonical source files", err);
    toast.add({
      severity: "error",
      summary: "Could not load dataset files",
      life: 3500,
    });
  } finally {
    if (current) canonicalFilesLoading.value = false;
  }
});

watch(canonicalFileId, async (fileId, _, onCleanup) => {
  let current = true;
  onCleanup(() => { current = false; });
  canonicalAssets.value = [];
  canonicalAssetId.value = null;
  canonicalAssetError.value = "";
  if (fileId === null || canonicalExperimentId.value === null) return;
  canonicalAssetsLoading.value = true;
  try {
    const response = await api.get<ExperimentFileAssets>(
      `/experiments/${canonicalExperimentId.value}/files/${fileId}/scientific-assets`,
    );
    if (!current) return;
    canonicalAssets.value = response.data.assets;
    if (response.data.assets.length === 1) {
      canonicalAssetId.value = response.data.assets[0].asset_id;
    }
  } catch {
    if (!current) return;
    canonicalAssetError.value = "Could not inspect this file's scientific assets.";
  } finally {
    if (current) canonicalAssetsLoading.value = false;
  }
});

async function loadObjects(projectId: number): Promise<void> {
  const request = ++objectRequest;
  objectsLoading.value = true;
  experiments.value = []; workflows.value = []; models.value = []; runs.value = []; runTotal.value = null; collections.value = []; objectErrors.value = [];
  const provider = projectCollectionsLoader.value;
  const [data, sheets, artifacts, history, extra] = await Promise.allSettled([
    api.get<ExperimentSummary[]>("/experiments", { params: { project_id: projectId } }),
    workflowStore.listWorkflows(projectId),
    api.get<ModelRow[]>("/models", { params: { limit: 50, project_id: projectId } }),
    api.get<{ runs: RunListItem[]; total: number }>("/runs", { params: { project_id: projectId, limit: 5 } }),
    provider ? provider(projectId) : Promise.resolve([] as ProjectCollection[]),
  ]);
  if (disposed || request !== objectRequest || projectStore.currentProjectId !== projectId) return;
  objectsLoading.value = false;
  if (data.status === "fulfilled") experiments.value = data.value.data;
  else objectErrors.value.push("Data");
  if (sheets.status === "fulfilled") workflows.value = [...sheets.value].sort((a,b) => b.updated_at.localeCompare(a.updated_at));
  else objectErrors.value.push("Workflows");
  if (artifacts.status === "fulfilled") models.value = artifacts.value.data || [];
  else objectErrors.value.push("Artifacts");
  if (history.status === "fulfilled") { runs.value = history.value.data.runs; runTotal.value = history.value.data.total; }
  else objectErrors.value.push("Runs");
  if (extra.status === "fulfilled") collections.value = extra.value;
  else objectErrors.value.push("Campaigns");
  if (canonicalProjectMetadata.value && !canonicalApplicationReady.value && canonicalExperimentId.value === null && experiments.value.length === 1)
    canonicalExperimentId.value = experiments.value[0].id;
}

function openRun(id: number): void {
  void router.push({ path: `/runs/${id}`, query: { project: projectStore.currentProjectId } });
}

async function syncAdvisorForProject(): Promise<void> {
  const projectId = projectStore.currentProjectId;
  if (projectId == null) return;
  try {
    await advisorStore.switchScope({
      projectId,
      tabKey: "project",
      subscopeKey: "overview",
      title: "Overview",
    });
  } catch (err) {
    console.warn("[project] switchScope failed", err);
  }
}

// Navigation helpers --------------------------------------------------

function openMemoryMap(): void {
  router.push("/project/memory-map");
}

function openProjectAudit(): void {
  const projectId = projectStore.currentProjectId;
  if (!projectId) return;
  void router.push({
    path: "/audit",
    query: {
      scope_type: "Project",
      scope_id: String(projectId),
      target_type: "Project",
      target_id: String(projectId),
    },
  });
}

function openData(): void {
  router.push("/data");
}

function openWorkflows(): void {
  router.push("/workflow");
}

async function openCanonicalWorkflow(): Promise<void> {
  if (canonicalWorkflow.value) {
    await workflowStore.loadWorkflow(canonicalWorkflow.value.id);
  }
  await router.push("/workflow");
}

async function bindCanonicalData(): Promise<void> {
  const workflow = canonicalWorkflow.value;
  const experimentId = canonicalExperimentId.value;
  const file = selectedCanonicalFile.value;
  if (!workflow || experimentId === null || !file) return;

  canonicalBinding.value = true;
  try {
    const result = await projectStore.bindCanonicalProjectSource(workflow.id, {
      experimentId,
      fileId: file.id,
      stage: file.stage,
      assetId: canonicalAssetId.value,
    });
    if (!result) {
      toast.add({
        severity: "error",
        summary: "Data binding failed",
        detail: projectStore.error || undefined,
        life: 4500,
      });
      return;
    }
    await loadObjects(activeProject.value!.id);
    toast.add({
      severity: result.status === "ready_for_application" ? "success" : "warn",
      summary:
        result.status === "ready_for_application"
          ? "Local data bound to canonical DAG"
          : "Application dependencies are unavailable",
      life: 3500,
    });
  } finally {
    canonicalBinding.value = false;
  }
}

function openArtifacts(): void {
  router.push("/runs?tab=artifacts");
}

// Project CRUD --------------------------------------------------------

function showEditProjectDialog(project: ProjectSummary): void {
  editingProject.value = project;
  dialogVisible.value = true;
}

async function onCreateProject(data: ProjectFormData): Promise<void> {
  const project = await projectStore.createProject(data);
  if (project) {
    await projectStore.selectProject(project.id);
    await loadObjects(project.id);
    toast.add({ severity: "success", summary: "Project created", life: 2000 });
  } else {
    toast.add({ severity: "error", summary: "Project not created", detail: projectStore.error || undefined, life: 5000 });
  }
}

async function onUpdateProject(data: ProjectFormData): Promise<void> {
  const project = editingProject.value;
  if (!project) return;
  const updated = await projectStore.updateProject(project.id, {
    name: data.name,
    description: data.description || null,
    technique: data.technique,
    sample_type: data.sample_type,
  });
  if (updated) {
    toast.add({
      severity: "success",
      summary: "Updated",
      life: 2000,
    });
    editingProject.value = null;
    dialogVisible.value = false;
  }
}

async function onExportProject(project: ProjectSummary): Promise<void> {
  await projectStore.exportProject(project.id);
  if (projectStore.error) {
    toast.add({
      severity: "error",
      summary: "Export failed",
      detail: projectStore.error,
      life: 3500,
    });
  } else if (projectStore.lastExportOmittedModels > 0) {
    toast.add({
      severity: "warn",
      summary: "Partial project archive downloaded",
      detail: `${projectStore.lastExportOmittedModels} saved model artifact(s) lacked portable training-source provenance and were omitted. The archive records their identities; workflows using them may need retraining. This is not a deployable winner package.`,
      life: 9000,
    });
  }
}

// Date helpers --------------------------------------------------------

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
</script>

<style scoped>
/*
  Zen language — same vocabulary as Dashboard V2. Hairlines instead of
  boxed cards; one accent color (primary) for "ready" / "linked" lifecycle
  states only; red for failed; everything else neutral. Single type and
  spacing rhythm so the three object surfaces (Data / Workflows /
  Artifacts) read as one continuous page.
*/

.project-content {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

:global(.content:has(.project-content)) {
  background: #e4e0fa;
}

/* Header ----------------------------------------------------------- */

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* Empty state ----------------------------------------------------- */

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

.empty-state__hint,
.empty-state p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.875rem;
}

/* Current Project section ----------------------------------------- */

.current-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--surface-border);
}

.current-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.current-head__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.current-name {
  font-size: 1.5rem;
  font-weight: 500;
  margin: 0;
  letter-spacing: 0;
}

.current-desc {
  color: var(--text-color-secondary);
  font-size: 0.9375rem;
  margin: 0.25rem 0 0 0;
  max-width: none;
}

.current-time {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.current-meta {
  display: flex;
  flex-wrap: wrap;
  font-size: 0.875rem;
  color: var(--text-color-secondary);
}

.current-meta span {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
}

.current-meta span + span::before {
  content: "·";
  margin: 0 0.6rem;
  color: var(--surface-border);
}

.current-meta strong {
  color: var(--text-color);
  font-weight: 500;
}

.current-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.5rem;
  margin-left: -0.5rem;
  align-items: center;
}

.canonical-project-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(18rem, 0.9fr);
  gap: 1.5rem;
  padding: 1.25rem;
  border: 1px solid color-mix(in srgb, var(--primary-color) 32%, var(--surface-border));
  border-radius: 0.75rem;
  background: color-mix(in srgb, var(--primary-color) 5%, var(--surface-card));
}

.canonical-project-panel h3,
.canonical-project-panel p {
  margin: 0;
}

.canonical-project-panel h3 {
  margin-top: 0.2rem;
  font-size: 1.05rem;
  font-weight: 600;
}

.canonical-project-panel__copy,
.canonical-project-panel__actions,
.canonical-project-panel__blocked,
.canonical-binding-form,
.canonical-binding-form__empty {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
}

.canonical-project-panel__digest {
  color: var(--text-color-secondary);
  font-family: var(--font-family-monospace, monospace);
  font-size: 0.75rem;
  overflow-wrap: anywhere;
}

.canonical-project-panel__actions,
.canonical-project-panel__blocked {
  align-items: flex-start;
  justify-content: center;
}

.canonical-binding-form label {
  display: grid;
  grid-template-columns: 5.5rem minmax(0, 1fr);
  gap: 0.75rem;
  align-items: center;
}

.canonical-binding-form label > span {
  color: var(--text-color-secondary);
  font-size: 0.82rem;
  font-weight: 600;
}

.canonical-binding-form__select {
  width: 100%;
}

@media (max-width: 760px) {
  .canonical-project-panel {
    grid-template-columns: 1fr;
  }

  .canonical-binding-form label {
    grid-template-columns: 1fr;
    gap: 0.25rem;
  }
}

.action-sep {
  display: inline-block;
  width: 1px;
  height: 1.2rem;
  background: var(--surface-border);
  margin: 0 0.4rem;
}

/* Object sections (Data / Workflows / Artifacts) ----------------- */

.object-section {
  display: flex;
  flex-direction: column;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--surface-border);
}

.object-section:last-of-type {
  border-bottom: none;
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

.object-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--surface-border);
  cursor: pointer;
  user-select: none;
  transition: color 0.15s ease;
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
  display: flex;
  flex-wrap: wrap;
}

.object-row__main small > span + span::before {
  content: "·";
  margin: 0 0.4rem;
  color: var(--surface-border);
}

.data-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.25rem;
}

.data-facts span {
  display: inline-flex;
  align-items: center;
  min-height: 1.35rem;
  padding: 0.05rem 0.45rem;
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  color: var(--text-color-secondary);
  font-size: 0.75rem;
  line-height: 1.2;
  background: transparent;
}

.object-row__time {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}

.object-empty {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  margin: 0.5rem 0 0;
}

/* Lifecycle indicators ------------------------------------------- */

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

.dot.failed {
  background: var(--red-500);
  border-color: var(--red-500);
  opacity: 1;
}

.dot.running {
  background: var(--yellow-500);
  border-color: var(--yellow-500);
  opacity: 1;
}

.dot.empty {
  border-color: var(--surface-border);
  opacity: 1;
}

.lifecycle-pill {
  display: inline-flex;
  align-items: center;
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.02em;
  text-transform: lowercase;
  border: 1px solid var(--surface-border);
  border-radius: 4px;
  padding: 0.05rem 0.45rem;
  color: var(--text-color-secondary);
  white-space: nowrap;
  flex-shrink: 0;
  min-width: 4.5rem;
  justify-content: center;
}

.lifecycle-pill.ready {
  border-color: color-mix(in srgb, var(--primary-color) 35%, transparent);
  color: var(--primary-color);
}

.lifecycle-pill.failed {
  border-color: color-mix(in srgb, var(--red-500) 35%, transparent);
  color: var(--red-500);
}

.lifecycle-pill.running {
  border-color: color-mix(in srgb, var(--yellow-500) 50%, transparent);
  color: var(--yellow-600, var(--yellow-500));
}

.lifecycle-pill.empty {
  color: var(--text-color-secondary);
}

/* Shared --------------------------------------------------------- */

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
  .current-head {
    flex-direction: column;
  }
  .current-actions {
    flex-direction: column;
    align-items: stretch;
    margin-left: 0;
  }
  .action-sep {
    display: none;
  }
  .object-row {
    flex-wrap: wrap;
  }
  .object-row__time,
  .lifecycle-pill {
    margin-left: 1.25rem;
  }
}
</style>
