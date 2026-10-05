<template>
  <section class="simplified-dashboard">
    <WorkspaceHeader
      title="Dashboard"
      :actions="headerActionItems"
    >
      <Button
        label="New Analysis"
        icon="pi pi-bolt"
        class="p-button-sm"
        @click="startAnalysisFlow"
      />
      <ProjectImportAction ref="projectImportAction" />
      <Button label="Project" icon="pi pi-arrow-right" iconPos="right"
        class="p-button-text p-button-sm" @click="router.push('/project')" />
    </WorkspaceHeader>

    <WorkspaceContext label="Dashboard context">
      <WorkspaceContextItem
        :label="activeDashboardTab === 'storage' ? 'Storage' : activeDashboardTab === 'archive' ? 'Archive' : 'Your Project'"
        :value="
          activeDashboardTab === 'storage'
            ? 'Across your projects'
            : activeDashboardTab === 'archive'
              ? `${projectStore.archivedProjects.length} archived projects`
              : projectStore.currentProject?.name || 'Choose a project'
        "
      >
        <template v-if="activeDashboardTab === 'projects'"
          >{{ projectStore.projects.length }} {{ projectStore.projects.length === 1 ? "project" : "projects" }}</template
        >
      </WorkspaceContextItem>
      <div
        v-if="activeDashboardTab === 'projects' && projectStore.currentProject"
        class="current-strip__meta"
      >
        <span
          class="current-strip__time"
          :title="absoluteTimestamp(projectStore.currentProject.updated_at)"
        >
          {{ formatRelative(projectStore.currentProject.updated_at) }}
        </span>
      </div>
    </WorkspaceContext>

    <WorkspaceTabs
      :model-value="activeDashboardTab"
      :tab-ids="['projects', 'archive', 'storage']"
      @update:model-value="selectDashboardTab"
    >
      <TabPanel header="Your Project">
        <!-- Primary surface: pick the right project from the user's set.
         Clicking the already-active card jumps into /project; clicking
         an inactive card selects it. One click pattern, two outcomes. -->
        <div class="projects-section">
          <div v-if="projectStore.projects.length" class="filter-strip">
            <InputText v-model="projectFilter" placeholder="Search" class="filter-input" />
          </div>

          <!-- Has projects + matches filter -->
          <div v-if="filteredProjects.length" class="projects-grid">
            <div
              v-for="project in filteredProjects"
              :key="project.id"
              class="project-card"
              :class="{ active: project.id === projectStore.currentProjectId }"
              role="button"
              tabindex="0"
              @click="selectProject(project)"
              @keydown.enter.prevent="selectProject(project)"
              @keydown.space.prevent="selectProject(project)"
            >
              <div class="project-card-head">
                <div class="title-stack">
                  <strong>{{ project.name }}</strong>
                  <Tag
                    v-if="project.id === projectStore.currentProjectId"
                    value="Active"
                    severity="success"
                  />
                </div>
                <div class="card-head-right">
                  <span class="last-touched" :title="absoluteTimestamp(project.updated_at)">
                    {{ formatRelative(project.updated_at) }}
                  </span>
                  <button
                    type="button"
                    class="trash-btn"
                    aria-label="Archive project"
                    @click.stop="requestArchive(project)"
                    @keydown.stop
                  >
                    <i class="pi pi-box"></i>
                  </button>
                </div>
              </div>
              <p v-if="project.description" class="project-description">
                {{ project.description }}
              </p>
              <div class="project-metrics">
                <span
                  ><strong>{{ project.experiment_count }}</strong> datasets</span
                >
                <span
                  ><strong>{{ project.workflow_count }}</strong> workflows</span
                >
                <span
                  ><strong>{{ project.model_count }}</strong> artifacts</span
                >
              </div>
            </div>
          </div>

          <!-- No projects at all -->
          <div v-else-if="!projectStore.projects.length" class="empty-state">
            <p class="empty-state__title">No projects yet.</p>
          </div>

          <!-- Has projects but none match search -->
          <div v-else class="empty-state">
            <p class="empty-state__title">No matches.</p>
          </div>
        </div>

      </TabPanel>
      <TabPanel header="Archive">
        <div class="projects-section archived-section">
          <div class="section-header">
            <h2>Archive</h2>
          </div>
          <div v-if="!projectStore.archivedProjects.length" class="empty-state">
            <p class="empty-state__title">No archived projects.</p>
          </div>
          <div v-else class="projects-grid">
            <div
              v-for="project in projectStore.archivedProjects"
              :key="project.id"
              class="project-card"
            >
              <div class="project-card-head">
                <div class="title-stack">
                  <strong>{{ project.name }}</strong>
                  <Tag value="Archived" severity="secondary" />
                </div>
              </div>
              <p v-if="project.description" class="project-description">
                {{ project.description }}
              </p>
              <div class="archive-actions">
                <Button
                  label="Restore"
                  icon="pi pi-replay"
                  class="p-button-text p-button-sm"
                  @click="restoreArchived(project)"
                />
                <Button
                  label="Permanently delete"
                  icon="pi pi-trash"
                  severity="danger"
                  class="p-button-text p-button-sm"
                  @click="requestDelete(project)"
                />
              </div>
            </div>
          </div>
        </div>
      </TabPanel>
      <TabPanel header="Storage">
        <section
          id="storage"
          ref="storageSection"
          class="projects-section"
          aria-label="Storage"
          tabindex="-1"
        >
          <RetainedStorageRecovery />
        </section>
      </TabPanel>
    </WorkspaceTabs>

    <Dialog
      v-model:visible="templateGalleryVisible"
      modal
      header="New Analysis"
      :style="{ width: '880px' }"
      class="new-analysis-dialog"
    >
      <div class="new-analysis">
        <div class="analysis-dataset-filter">
          <label for="analysis-dataset">Dataset</label>
          <Dropdown
            id="analysis-dataset"
            v-model="selectedDatasetId"
            :options="analysisDatasetOptions"
            option-label="label"
            option-value="value"
            placeholder="Choose dataset"
            class="analysis-dataset-filter__control"
          />
        </div>
        <article class="starter-card">
          <div class="starter-card__body">
            <h5>Blank Project</h5>
            <p>Start clean, then import data.</p>
          </div>
          <Button
            label="Start"
            icon="pi pi-arrow-right"
            icon-pos="right"
            class="p-button-outlined"
            :loading="isStartingAnalysis && selectedTemplateId === null"
            :disabled="(!isLocalMode && !selectedDatasetId) || isStartingAnalysis"
            @click="startBlankProject"
          />
        </article>

        <TemplateGallery
          :selected-template-id="selectedTemplateId"
          :selected-dataset-id="selectedDatasetId"
          :require-dataset-selection="true"
          :show-header="false"
          @select="startTemplateProject"
        />
      </div>
    </Dialog>

    <Dialog
      v-model:visible="archiveConfirmVisible"
      modal
      header="Archive project"
      :style="{ width: '420px' }"
    >
      <p class="delete-confirm__body">
        Archive <strong>{{ projectToArchive?.name }}</strong
        >? It will leave the active Dashboard. You can restore it from Archive without changing its
        models or evidence.
      </p>
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="archiveConfirmVisible = false" />
        <Button label="Archive" icon="pi pi-box" :loading="archiving" @click="confirmArchive" />
      </template>
    </Dialog>

    <!-- Irreversible removal is only offered for an archived project. -->
    <Dialog
      v-model:visible="deleteConfirmVisible"
      modal
      header="Permanently delete archived project"
      :style="{ width: '420px' }"
    >
      <p class="delete-confirm__body">
        Permanently remove <strong>{{ projectToDelete?.name }}</strong> from your projects? This
        cannot be undone. When a retained model depends on this project, its model and source
        evidence remain under an internal read-only provenance record; this action does not erase
        them.
      </p>
      <label class="delete-confirm__label" for="confirm-project-name"
        >Type the project name to confirm</label
      >
      <InputText
        id="confirm-project-name"
        v-model="deleteNameDraft"
        class="delete-confirm__input"
      />
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="deleteConfirmVisible = false" />
        <Button
          label="Permanently delete"
          icon="pi pi-trash"
          severity="danger"
          :disabled="deleteNameDraft !== projectToDelete?.name"
          :loading="deleting"
          @click="confirmDelete"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import Button from "primevue/button";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import ProjectImportAction from "@/components/ProjectImportAction.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import TabPanel from "primevue/tabpanel";
import RetainedStorageRecovery from "@/components/RetainedStorageRecovery.vue";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Dropdown from "primevue/dropdown";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore, type WorkflowTemplate } from "@/stores/workflow";
import type { ProjectSummary } from "@/types";
import TemplateGallery from "@/views/workflow-builder/TemplateGallery.vue";
import type { ReferenceDatasetOption } from "@/stores/workflow-types";
import { useAppConfig } from "@/composables/useAppConfig";

const DATA_ENTRY_MODE_KEY = "sherpa:data-entry-mode";
const DATA_ENTRY_PROJECT_KEY = "sherpa:data-entry-project-id";
const DATA_ENTRY_DATASET_KEY = "sherpa:data-entry-dataset-intent";

const router = useRouter();
const route = useRoute();
const storageSection = ref<HTMLElement | null>(null);
const dashboardTabFromHash = () => route.hash === "#storage" ? "storage" : route.hash === "#archive" ? "archive" : "projects";
const activeDashboardTab = ref(dashboardTabFromHash());
function selectDashboardTab(tab: string): void {
  activeDashboardTab.value = tab;
  void router.replace({ hash: tab === "projects" ? "" : `#${tab}` });
}
async function revealStorage(): Promise<void> {
  activeDashboardTab.value = dashboardTabFromHash();
  if (activeDashboardTab.value !== "storage") return;
  await nextTick();
  // The workspace scrolls inside .content, not window (Vue Router's target).
  storageSection.value?.scrollIntoView({ block: "start" });
  storageSection.value?.focus({ preventScroll: true });
}
watch(
  () => route.hash,
  () => void revealStorage(),
  { flush: "post" },
);
const toast = useToast();
const projectStore = useProjectStore();
const projectImportAction = ref<InstanceType<typeof ProjectImportAction> | null>(null);
const headerActionItems = computed(() => [
  { label: "New Analysis", icon: "pi pi-bolt", command: startAnalysisFlow },
  {
    label: "Import Project",
    icon: "pi pi-upload",
    disabled: projectImportAction.value?.disabled ?? false,
    command: () => projectImportAction.value?.triggerImport(),
  },
  { label: "Project", icon: "pi pi-arrow-right", command: () => router.push("/project") },
]);
const workflowStore = useWorkflowStore();
const { appMode } = useAppConfig();
const isLocalMode = computed(() => appMode.value === "local");

const templateGalleryVisible = ref(false);
const selectedTemplateId = ref<number | null>(null);
const selectedDatasetId = ref<string | null>(null);
const isStartingAnalysis = ref(false);

const datasetSourceLabel = (source: ReferenceDatasetOption["source"]): string => {
  if (source === "builtin") return "built-in";
  if (source === "synthetic") return "Spectra synthetic";
  if (source === "sklearn") return "scikit-learn";
  return "user-acquired";
};

const analysisDatasetOptions = computed(() =>
  (workflowStore.compatibilityMatrix?.datasets || []).map((dataset) => ({
    label: `${dataset.label} · ${datasetSourceLabel(dataset.source)}`,
    value: dataset.dataset_id || `${dataset.source}:${dataset.name}`,
  })),
);

const selectedDataset = computed<ReferenceDatasetOption | null>(() => {
  const datasetId = selectedDatasetId.value;
  if (!datasetId) return null;
  return (
    (workflowStore.compatibilityMatrix?.datasets || []).find(
      (dataset) => (dataset.dataset_id || `${dataset.source}:${dataset.name}`) === datasetId,
    ) ?? null
  );
});

const projectFilter = ref("");

const archiveConfirmVisible = ref(false);
const archiving = ref(false);
const projectToArchive = ref<ProjectSummary | null>(null);

// Delete confirmation state — small inline dialog rather than native
// confirm() so the V2 look stays consistent.
const deleteConfirmVisible = ref(false);
const deleting = ref(false);
const projectToDelete = ref<ProjectSummary | null>(null);
const deleteNameDraft = ref("");

// Projects, sorted most-recently-touched first. updated_at is the canonical
// recency field on ProjectSummary, falling back to created_at if missing.
const sortedProjects = computed<ProjectSummary[]>(() => {
  return [...projectStore.projects].sort((a, b) => {
    const ta = new Date(a.updated_at || a.created_at).getTime();
    const tb = new Date(b.updated_at || b.created_at).getTime();
    return tb - ta;
  });
});

const filteredProjects = computed<ProjectSummary[]>(() => {
  const needle = projectFilter.value.trim().toLowerCase();
  if (!needle) return sortedProjects.value;
  return sortedProjects.value.filter((p) => {
    const name = (p.name || "").toLowerCase();
    const desc = (p.description || "").toLowerCase();
    return name.includes(needle) || desc.includes(needle);
  });
});

onMounted(async () => {
  // Make sure the page lands on the project the user was last on, and that
  // we have a fresh project list + templates for the "Start New Analysis"
  // flow. Parallel; failures of one don't block the others.
  await Promise.allSettled([
    projectStore.ensureProjectForBrowserTab(),
    projectStore.fetchProjects(),
    projectStore.fetchArchivedProjects(),
    workflowStore.fetchTemplates(undefined, true),
    workflowStore.fetchCompatibilityMatrix(),
  ]);
  await revealStorage();
});

async function selectProject(project: ProjectSummary): Promise<void> {
  // Click only makes the project active — the user stays on the dashboard
  // and sees the Current Project strip light up. The arrow on that strip
  // is the dedicated path into Projects V2.
  if (project.id !== projectStore.currentProjectId) {
    await projectStore.selectProject(project.id);
  }
}

function startAnalysisFlow(): void {
  selectedTemplateId.value = null;
  templateGalleryVisible.value = true;
}

function starterProjectName(
  dataset: ReferenceDatasetOption | null,
  template?: WorkflowTemplate,
): string {
  if (!template) {
    return dataset ? `${dataset.label} analysis` : "Blank project";
  }
  return `${dataset?.label ?? "Blank project"} ${template.name}`;
}

function persistAnalysisStarterIntent(
  projectId: number,
  dataset: ReferenceDatasetOption,
  template?: WorkflowTemplate,
): void {
  try {
    window.sessionStorage.setItem(DATA_ENTRY_MODE_KEY, "analysis-starter");
    window.sessionStorage.setItem(DATA_ENTRY_PROJECT_KEY, String(projectId));
    window.sessionStorage.setItem(
      DATA_ENTRY_DATASET_KEY,
      JSON.stringify({
        schema_version: "spectra-analysis-starter-dataset-intent/1",
        project_id: projectId,
        dataset_id: dataset.dataset_id || `${dataset.source}:${dataset.name}`,
        source: dataset.source,
        name: dataset.name,
        label: dataset.label,
        template_slug: template?.slug ?? null,
      }),
    );
  } catch {
    // Session storage is an enhancement; project metadata still records the
    // starter intent.
  }
}

async function createAnalysisStarter(template?: WorkflowTemplate): Promise<void> {
  const dataset = selectedDataset.value;
  const blankLocalProject = !template && !dataset && isLocalMode.value;
  if (!dataset && !blankLocalProject) {
    toast.add({
      severity: "warn",
      summary: "Choose a Dataset",
      detail: "Select the dataset before starting the analysis.",
      life: 3500,
    });
    return;
  }

  selectedTemplateId.value = template?.id ?? null;
  isStartingAnalysis.value = true;
  try {
    const project = await projectStore.createProject({
      name: starterProjectName(dataset, template),
      description: template ? template.description || null : null,
      technique: dataset?.analysis_profile?.technique ?? dataset?.technique ?? null,
      sample_type: null,
      metadata: dataset
        ? {
            analysis_starter: {
              schema_version: "spectra-analysis-starter-dataset-intent/1",
              dataset_id: dataset.dataset_id || `${dataset.source}:${dataset.name}`,
              source: dataset.source,
              name: dataset.name,
              label: dataset.label,
              template_slug: template?.slug ?? null,
            },
          }
        : undefined,
    });
    if (!project) {
      toast.add({
        severity: "error",
        summary: "Project Not Created",
        detail: projectStore.error || undefined,
        life: 5000,
      });
      return;
    }

    if (dataset) persistAnalysisStarterIntent(project.id, dataset, template);

    await projectStore.fetchProject(project.id);

    templateGalleryVisible.value = false;
    toast.add({
      severity: "success",
      summary: "Analysis Started",
      detail: template
        ? `${project.name} is ready for data import and target selection.`
        : `${project.name} is ready for data import.`,
      life: 3500,
    });
    // A selected reference is part of the starter contract, so land on the
    // import surface where it can be admitted into this project immediately.
    // Blank local projects still open the project overview.
    await router.push(dataset ? { path: "/data", query: { tab: "import" } } : "/project");
  } catch (error: unknown) {
    toast.add({
      severity: "error",
      summary: "Analysis Not Started",
      detail: error instanceof Error ? error.message : "Could not start the analysis.",
      life: 6000,
    });
  } finally {
    isStartingAnalysis.value = false;
    selectedTemplateId.value = null;
  }
}

async function startBlankProject(): Promise<void> {
  await createAnalysisStarter();
}

async function startTemplateProject(template: WorkflowTemplate): Promise<void> {
  await createAnalysisStarter(template);
}

function requestArchive(project: ProjectSummary): void {
  projectToArchive.value = project;
  archiveConfirmVisible.value = true;
}

async function confirmArchive(): Promise<void> {
  const target = projectToArchive.value;
  if (!target) return;
  archiving.value = true;
  try {
    const ok = await projectStore.archiveProject(target.id);
    toast.add({
      severity: ok ? "info" : "error",
      summary: ok ? `Archived ${target.name}` : "Archive failed",
      detail: ok ? undefined : projectStore.error || undefined,
      life: ok ? 2500 : 4000,
    });
  } finally {
    archiving.value = false;
    archiveConfirmVisible.value = false;
    projectToArchive.value = null;
  }
}

async function restoreArchived(project: ProjectSummary): Promise<void> {
  const ok = await projectStore.restoreProject(project.id);
  toast.add({
    severity: ok ? "info" : "error",
    summary: ok ? `Restored ${project.name}` : "Restore failed",
    detail: ok ? undefined : projectStore.error || undefined,
    life: ok ? 2500 : 4000,
  });
}

function requestDelete(project: ProjectSummary): void {
  projectToDelete.value = project;
  deleteNameDraft.value = "";
  deleteConfirmVisible.value = true;
}

async function confirmDelete(): Promise<void> {
  const target = projectToDelete.value;
  if (!target) return;
  deleting.value = true;
  try {
    const ok = await projectStore.deleteProject(target.id, deleteNameDraft.value);
    if (ok) {
      toast.add({
        severity: "info",
        summary: `Deleted ${target.name}`,
        life: 2500,
      });
    } else {
      toast.add({
        severity: "error",
        summary: "Delete failed",
        detail: projectStore.error || undefined,
        life: 4000,
      });
    }
  } finally {
    deleting.value = false;
    deleteConfirmVisible.value = false;
    projectToDelete.value = null;
    deleteNameDraft.value = "";
  }
}

function formatRelative(dateStr: string): string {
  if (!dateStr) return "—";
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  if (diff < 0) return "Just now";
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
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
  Zen pass: restrained ornament, generous whitespace, one accent used only
  for active state + focus rings + the single primary CTA. Type scale and
  spacing both step on consistent multiples so the page reads as a single
  rhythm, not a collage of components.
*/

.simplified-dashboard {
  display: flex;
  flex-direction: column;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
}

:global(.content:has(.simplified-dashboard)) {
  background: #e4e0fa;
}

/* Hero -------------------------------------------------------------- */

.hero-section {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 2rem;
  padding: 2.5rem 0 1rem;
  border-bottom: 1px solid var(--surface-border);
}

.hero-content h1 {
  font-size: 1.75rem;
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: 0;
  margin: 0 0 0.5rem 0;
  /* Match `.tab-header h1` so the page title weight + height are
   * identical to every other tab. Hero layout otherwise stays distinct. */
  color: #1b1f23;
}

.hero-subtitle {
  font-size: 0.9375rem;
  color: var(--text-color-secondary);
  margin: 0;
  max-width: 56ch;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.hero-section :deep(.hero-btn) {
  font-size: 0.9375rem;
  padding: 0.6rem 1.1rem;
  border-radius: 6px;
  box-shadow: none;
}

/* Current Project hairline strip ----------------------------------- */

.current-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.9rem 0;
  border-bottom: 1px solid var(--surface-border);
}

.current-strip__main {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.current-strip__name {
  font-size: 1.125rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.current-strip__meta {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.current-strip__time {
  color: var(--text-color-secondary);
  font-size: 0.875rem;
  font-variant-numeric: tabular-nums;
}

/* Projects section ------------------------------------------------- */

.projects-section {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.archived-section {
  margin-top: 1.5rem;
  border-top: 1px solid var(--surface-border);
  padding-top: 1.5rem;
}

.archived-section .project-card {
  cursor: default;
}

.archive-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 1rem;
}

.section-header h2 {
  font-size: 1.25rem;
  font-weight: 500;
  margin: 0;
  color: var(--text-color);
}

.muted-count {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
}

.filter-strip {
  display: flex;
}

.filter-input {
  width: 100%;
  max-width: 320px;
  background: transparent;
  border: 1px solid var(--surface-border);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  box-shadow: none;
}

.filter-input:focus {
  border-color: var(--primary-color);
  box-shadow: none;
  outline: none;
}

.projects-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.project-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem 1.25rem;
  background: var(--surface-card);
  border: 1px solid var(--surface-border);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease;
  user-select: none;
}

.project-card:hover {
  border-color: var(--text-color-secondary);
}

.project-card:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

/* Active state: a single 3px accent stripe at the leading edge, no fill. */
.project-card.active {
  border-color: var(--surface-border);
}

.project-card.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0.5rem;
  bottom: 0.5rem;
  width: 3px;
  background: var(--primary-color);
  border-radius: 0 2px 2px 0;
}

.project-card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}

.title-stack {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.title-stack strong {
  font-size: 1rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Quieter "Active" tag — the stripe carries most of the signal. */
.title-stack :deep(.p-tag) {
  background: transparent;
  border: 1px solid color-mix(in srgb, var(--primary-color) 35%, transparent);
  color: var(--primary-color);
  font-size: 0.6875rem;
  font-weight: 500;
  padding: 0.05rem 0.4rem;
}

.last-touched {
  color: var(--text-color-secondary);
  font-size: 0.8125rem;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.project-description {
  color: var(--text-color-secondary);
  margin: 0;
  font-size: 0.875rem;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Metrics: text, separated by a thin middle-dot. No pills. */
.project-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  font-size: 0.8125rem;
  color: var(--text-color-secondary);
  margin-top: 0.25rem;
}

.project-metrics span {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
}

.project-metrics span + span::before {
  content: "·";
  margin: 0 0.6rem;
  color: var(--surface-border);
}

.project-metrics strong {
  color: var(--text-color);
  font-weight: 500;
}

/* Empty / no-match state */

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  padding: 3rem 1rem;
  text-align: center;
}

.empty-state__title {
  margin: 0;
  font-size: 1rem;
  font-weight: 500;
  color: var(--text-color);
}

/* Shared bits */

.eyebrow {
  display: block;
  color: var(--text-color-secondary);
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

/* New Analysis dialog ---------------------------------------------- */

.new-analysis {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  /* Breathing room above the first content row so the dialog header's
     bottom border doesn't visually clip the starter card. */
  padding-top: 0.5rem;
}

.analysis-dataset-filter {
  display: grid;
  gap: 0.4rem;
  padding: 0.9rem 1rem;
  border: 1px solid var(--surface-border);
  border-radius: 10px;
  background: color-mix(in srgb, var(--primary-color) 4%, var(--surface-card));
}

.analysis-dataset-filter label {
  font-weight: 600;
}

.analysis-dataset-filter small {
  color: var(--text-color-secondary);
}

.analysis-dataset-filter__control {
  width: 100%;
}

/* Blank Project starter — same visual language as TemplateGallery's
   template cards (border, radius, surface, internal layout), but laid
   out as a single horizontal strip so it reads as the first option. */
.starter-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 12px;
  background: var(--surface-card);
}

.starter-card__body {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.starter-card__body h5 {
  margin: 0;
  font-size: 1rem;
  font-weight: 500;
}

.starter-card__body p {
  margin: 0;
  color: var(--text-color-secondary);
  font-size: 0.9375rem;
  line-height: 1.5;
}

.delete-confirm__body {
  margin: 0;
  font-size: 0.9375rem;
  color: var(--text-color);
  line-height: 1.5;
}

.delete-confirm__label {
  display: block;
  margin: 1rem 0 0.4rem;
  font-size: 0.875rem;
  font-weight: 600;
}

.delete-confirm__input {
  width: 100%;
}

/* Trash button on each project card. Hidden until the card is hovered
   or the trash button itself receives keyboard focus — keeps the grid
   visually quiet but still discoverable. */
.card-head-right {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-shrink: 0;
}

.trash-btn {
  background: transparent;
  border: none;
  padding: 0.25rem 0.4rem;
  color: var(--text-color-secondary);
  cursor: pointer;
  border-radius: 4px;
  transition:
    color 0.15s ease,
    background 0.15s ease;
  font: inherit;
  line-height: 1;
}

.trash-btn:hover {
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
}

.trash-btn:focus-visible {
  outline: 1px solid var(--primary-color);
  outline-offset: 2px;
}

.trash-btn i {
  font-size: 0.875rem;
}

@media (max-width: 600px) {
  .starter-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }
}

/* Responsive */

@media (max-width: 1100px) {
  .projects-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .hero-section {
    flex-direction: column;
    align-items: flex-start;
    gap: 1.5rem;
    padding-top: 1.5rem;
  }
  .hero-actions {
    width: 100%;
  }
  .hero-actions > * {
    flex: 1;
  }
  .current-strip {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.5rem;
  }
}
</style>
