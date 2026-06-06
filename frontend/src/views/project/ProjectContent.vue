<template>
  <section class="project-content">
    <!-- Header --------------------------------------------------------- -->
    <header class="tab-header">
      <h1>Project</h1>
      <ResponsiveHeaderActions :items="headerActionItems">
        <Button
          v-if="isServerBacked && projectStore.currentProjectId"
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
        <Button
          label="Import"
          icon="pi pi-upload"
          class="p-button-outlined p-button-sm"
          :disabled="projectImportDisabled"
          @click="triggerImport"
        />
      </ResponsiveHeaderActions>
    </header>

    <!-- Loading -------------------------------------------------------- -->
    <div v-if="projectStore.isLoading && !projectStore.projects.length" class="empty-state">
      <ProgressSpinner style="width: 28px; height: 28px" />
      <p>Loading projects…</p>
    </div>

    <!-- No projects at all -->
    <div v-else-if="!projectStore.projects.length" class="empty-state">
      <p class="empty-state__title">No projects yet.</p>
      <p class="empty-state__hint">Start from New Analysis on the Dashboard, or import a project package.</p>
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
          <span><strong>{{ activeProject.experiment_count }}</strong> data</span>
          <span><strong>{{ activeProject.workflow_count }}</strong> workflows</span>
          <span><strong>{{ activeProject.model_count }}</strong> artifacts</span>
          <span>created {{ formatRelative(activeProject.created_at) }}</span>
        </div>

        <div class="current-actions">
          <Button label="Edit" icon="pi pi-pencil" class="p-button-text p-button-sm" @click="showEditProjectDialog(activeProject)" />
          <Button label="Export" icon="pi pi-download" class="p-button-text p-button-sm" @click="onExportProject(activeProject)" />
        </div>
      </section>

      <!-- Data ------------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Data</span>
            <span class="object-section__count">{{ experiments.length }}</span>
          </div>
          <Button label="Open Data" icon="pi pi-arrow-right" iconPos="right" class="p-button-text p-button-sm" @click="openData" />
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
                <span>{{ experiment.file_count }} file{{ experiment.file_count === 1 ? "" : "s" }}</span>
                <span v-if="experimentDescription(experiment)">{{ experimentDescription(experiment) }}</span>
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
        <p v-else class="object-empty">No datasets in this project.</p>
      </section>

      <!-- Workflows -------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Workflows</span>
            <span class="object-section__count">{{ workflows.length }}</span>
          </div>
          <Button label="Open Workflows" icon="pi pi-arrow-right" iconPos="right" class="p-button-text p-button-sm" @click="openWorkflows" />
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
                <span v-if="workflow.created_from_template_name">from {{ workflow.created_from_template_name }}</span>
                <span v-else-if="workflow.created_from_workflow_name">copied from {{ workflow.created_from_workflow_name }}</span>
                <span>{{ workflow.node_count ?? 0 }} node{{ workflow.node_count === 1 ? "" : "s" }} · {{ workflow.edge_count ?? 0 }} edge{{ workflow.edge_count === 1 ? "" : "s" }}</span>
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
        <p v-else class="object-empty">No workflows in this project.</p>
      </section>

      <!-- Artifacts -------------------------------------------------- -->
      <section class="object-section">
        <div class="object-section__head">
          <div class="object-section__title">
            <span class="eyebrow">Artifacts</span>
            <span class="object-section__count">{{ models.length }}</span>
          </div>
          <Button label="Open Artifacts" icon="pi pi-arrow-right" iconPos="right" class="p-button-text p-button-sm" @click="openArtifacts" />
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
            <span class="object-row__time" :title="absoluteTimestamp(model.updated_at || model.created_at)">
              {{ formatRelative(model.updated_at || model.created_at) }}
            </span>
            <span class="lifecycle-pill ready">Trained</span>
          </div>
        </div>
        <p v-else class="object-empty">No artifacts in this project yet.</p>
      </section>
    </template>

    <!-- Dialogs ----------------------------------------------------- -->
    <ProjectDialog
      v-model:visible="dialogVisible"
      :edit-project="editingProject"
      @update="onUpdateProject"
    />

    <input
      ref="fileInput"
      type="file"
      accept=".spectrapy,.zip"
      class="hidden-file-input"
      @change="onFileSelected"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";
import api from "@/api/client";
import ProjectDialog, { type ProjectFormData } from "@/components/ProjectDialog.vue";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";
import { useAdvisorStore } from "@/stores/advisor";
import { useAppConfig } from "@/composables/useAppConfig";
import { useDemoMode } from "@/composables/useDemoMode";
import { useDataStore } from "@/stores/data";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore, type WorkflowListItem } from "@/stores/workflow";
import type { ExperimentSummary, ProjectSummary } from "@/types";

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
const dataStore = useDataStore();
const workflowStore = useWorkflowStore();
const advisorStore = useAdvisorStore();
const { appMode, isCapabilityDisabled } = useAppConfig();
const { isDemoMode, uploadsLastWeek, uploadsLimitWeek, uploadsResetWeekAt, fetchQuota } = useDemoMode();

const isServerBacked = computed(() => appMode.value !== "local");
const uploadQuotaExhausted = computed(() => (
  isDemoMode.value
  && uploadsLastWeek.value !== null
  && uploadsLimitWeek.value > 0
  && uploadsLimitWeek.value < 999999
  && uploadsLastWeek.value >= uploadsLimitWeek.value
));
const uploadDisabledMessage = computed(() => {
  if (isCapabilityDisabled("data_upload")) return "Project import is disabled for this deployment.";
  if (uploadQuotaExhausted.value) {
    const reset = uploadsResetWeekAt.value ? new Date(uploadsResetWeekAt.value).toLocaleString() : "later";
    return `Demo upload limit reached. Your next import is available ${reset}.`;
  }
  return "";
});
const dataUploadDisabled = computed(() => isCapabilityDisabled("data_upload") || uploadQuotaExhausted.value);
const projectImportDisabled = computed(
  () => dataUploadDisabled.value || isCapabilityDisabled("project_import"),
);
const activeProject = computed(() => projectStore.currentProject);
const headerActionItems = computed(() => [
  ...(isServerBacked.value && projectStore.currentProjectId
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
  {
    label: "Import",
    icon: "pi pi-upload",
    disabled: projectImportDisabled.value,
    command: triggerImport,
  },
]);

const fileInput = ref<HTMLInputElement | null>(null);
const dialogVisible = ref(false);
const editingProject = ref<ProjectSummary | null>(null);

// Richer per-object lists than what ProjectDetail.experiments / .workflows /
// .models carry — ExperimentBrief/WorkflowBrief don't include created_at /
// node_count / metrics, all of which the lifecycle line needs.
const experiments = ref<ExperimentSummary[]>([]);
const workflows = ref<WorkflowListItem[]>([]);
const models = ref<ModelRow[]>([]);

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
  await Promise.all([projectStore.fetchProjects(), fetchQuota()]);
  const projectId =
    projectStore.currentProjectId ?? projectStore.recentProjects[0]?.id ?? null;
  if (projectId != null) {
    await Promise.allSettled([
      projectStore.fetchProject(projectId),
      loadObjects(projectId),
    ]);
  }
  void syncAdvisorForProject();
});

watch(
  () => projectStore.currentProjectId,
  async (next) => {
    if (next != null) {
      await loadObjects(next);
      void syncAdvisorForProject();
    } else {
      experiments.value = [];
      workflows.value = [];
      models.value = [];
    }
  },
);

async function loadObjects(projectId: number): Promise<void> {
  // All three lifecycle surfaces in parallel; tolerate individual failures.
  await Promise.allSettled([
    loadExperiments(projectId),
    loadWorkflows(projectId),
    loadModels(projectId),
  ]);
}

async function loadExperiments(projectId: number): Promise<void> {
  try {
    await dataStore.fetchExperiments(projectId);
    experiments.value = [...dataStore.experiments];
  } catch (err) {
    console.warn("[project] failed to load experiments", err);
    experiments.value = [];
  }
}

async function loadWorkflows(projectId: number): Promise<void> {
  try {
    const list = await workflowStore.listWorkflows(projectId);
    workflows.value = [...list].sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
    );
  } catch (err) {
    console.warn("[project] failed to load workflows", err);
    workflows.value = [];
  }
}

async function loadModels(projectId: number): Promise<void> {
  try {
    const response = await api.get<ModelRow[]>("/models", {
      params: { limit: 50, project_id: projectId },
    });
    models.value = response.data || [];
  } catch (err) {
    console.warn("[project] failed to load models", err);
    models.value = [];
  }
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

function openArtifacts(): void {
  router.push("/runs");
}

// Project CRUD --------------------------------------------------------

function showEditProjectDialog(project: ProjectSummary): void {
  editingProject.value = project;
  dialogVisible.value = true;
}

function triggerImport(): void {
  if (projectImportDisabled.value) {
    toast.add({
      severity: "warn",
      summary: "Import Disabled",
      detail: uploadDisabledMessage.value || "Project import is disabled for this deployment.",
      life: 4000,
    });
    return;
  }
  fileInput.value?.click();
}

async function onFileSelected(event: Event): Promise<void> {
  if (projectImportDisabled.value) return;
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  const project = await projectStore.importProject(file);
  if (project) {
    await fetchQuota();
    toast.add({
      severity: "success",
      summary: `Imported ${project.name}`,
      life: 2500,
    });
  } else {
    toast.add({
      severity: "error",
      summary: "Import failed",
      detail: projectStore.error || undefined,
      life: 3500,
    });
  }
  input.value = "";
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
  max-width: 70ch;
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

.hidden-file-input {
  display: none;
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
