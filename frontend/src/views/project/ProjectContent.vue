<template>
  <section class="project-content">
    <OnboardingBanner />
    <div class="section-header">
      <div>
        <h1>Projects</h1>
        <p class="section-subtitle">
          Organize your spectral analysis work into projects
        </p>
      </div>
      <div class="header-actions">
        <Button
          label="Import"
          icon="pi pi-upload"
          class="p-button-outlined"
          @click="triggerImport"
        />
        <Button
          label="New Project"
          icon="pi pi-plus"
          @click="showNewProjectDialog"
        />
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="projectStore.isLoading && !projectStore.projects.length" class="loading-container">
      <ProgressSpinner style="width: 40px; height: 40px" />
      <span>Loading projects...</span>
    </div>

    <!-- Empty state -->
    <div v-else-if="!projectStore.projects.length" class="empty-state">
      <i class="pi pi-folder-open"></i>
      <h3>No projects yet</h3>
      <p>Create your first project to organize experiments, workflows, and reusable templates.</p>
      <Button label="Create Project" icon="pi pi-plus" @click="showNewProjectDialog" />

      <div class="templates-panel empty-templates-panel">
        <div class="templates-header">
          <div>
            <h3>Workflow Templates</h3>
            <p>Create a project first, then launch one of the validated templates below into that project.</p>
          </div>
        </div>
        <TemplateGallery :selected-template-id="selectedTemplateId" :show-header="false" @select="openTemplateWizard" />
      </div>
    </div>

    <template v-else>
      <!-- Current Project Banner -->
      <div v-if="projectStore.currentProject" class="current-project-banner">
        <div class="banner-left">
          <i class="pi pi-folder-open banner-icon"></i>
          <div class="banner-info">
            <span class="banner-label">Active Project</span>
            <h2 class="banner-name">{{ projectStore.currentProject.name }}</h2>
            <p v-if="projectStore.currentProject.description" class="banner-desc">
              {{ projectStore.currentProject.description }}
            </p>
          </div>
        </div>
        <div class="banner-actions">
          <div class="banner-tags">
            <Tag v-if="projectStore.currentProject.technique" :value="projectStore.currentProject.technique" severity="info" class="project-tag" />
            <Tag v-if="projectStore.currentProject.sample_type" :value="projectStore.currentProject.sample_type" severity="secondary" class="project-tag" />
          </div>
          <div class="banner-stats">
            <span class="stat" title="Experiments">
              <i class="pi pi-chart-bar"></i> {{ projectStore.currentProject.experiment_count }}
            </span>
            <span class="stat" title="Workflows">
              <i class="pi pi-sitemap"></i> {{ projectStore.currentProject.workflow_count }}
            </span>
            <span class="stat" title="Scripts">
              <i class="pi pi-code"></i> {{ projectStore.currentProject.script_count }}
            </span>
            <span class="stat" title="Models">
              <i class="pi pi-box"></i> {{ projectStore.currentProject.model_count }}
            </span>
            <span class="stat" title="Versions">
              <i class="pi pi-history"></i> {{ projectStore.currentProject.version_count }}
            </span>
          </div>
          <div class="banner-buttons">
            <Button
              label="Save"
              icon="pi pi-save"
              class="p-button-outlined"
              @click="openSaveDialog"
            />
            <Button
              label="Continue"
              icon="pi pi-arrow-right"
              iconPos="right"
              @click="continueProject"
            />
          </div>
        </div>
      </div>

      <div class="projects-section templates-panel">
        <div class="templates-header">
          <div>
            <h3 class="section-title">Workflow Templates</h3>
            <p class="templates-subtitle">
              Start common chemometric workflows from validated backend templates inside the active project.
            </p>
          </div>
        </div>
        <TemplateGallery :selected-template-id="selectedTemplateId" :show-header="false" @select="openTemplateWizard" />
      </div>

      <!-- Version History (when active project has versions) -->
      <div v-if="projectStore.currentProject && projectStore.versions.length" class="projects-section">
        <h3 class="section-title">Version History</h3>
        <div class="version-list">
          <div
            v-for="ver in projectStore.versions"
            :key="ver.id"
            class="version-row"
          >
            <div class="version-info">
              <span class="version-number">v{{ ver.version_number }}</span>
              <span class="version-desc">{{ ver.change_description || 'No description' }}</span>
            </div>
            <div class="version-meta">
              <Tag v-if="ver.include_raw_data" value="Raw Data" severity="info" class="version-tag" />
              <span class="version-date">{{ formatDate(ver.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Recent Projects -->
      <div class="projects-section">
        <h3 class="section-title">Recent Projects</h3>
        <div class="projects-grid">
          <div
            v-for="project in projectStore.recentProjects"
            :key="project.id"
            class="project-card"
            :class="{ active: project.id === projectStore.currentProjectId }"
            @click="selectAndOpen(project.id)"
          >
            <div class="card-header">
              <div class="card-icon" :class="iconClass(project)">
                <i :class="techniqueIcon(project)"></i>
              </div>
              <div class="card-meta">
                <h4 class="card-name">{{ project.name }}</h4>
                <span class="card-date">{{ formatDate(project.updated_at) }}</span>
              </div>
              <Button
                icon="pi pi-ellipsis-v"
                class="p-button-text p-button-rounded p-button-sm card-menu-btn"
                @click.stop="toggleMenu($event, project.id)"
              />
            </div>
            <p v-if="project.description" class="card-description">
              {{ truncate(project.description, 120) }}
            </p>
            <div class="card-footer">
              <div class="card-stats">
                <span class="stat" title="Workflows">
                  <i class="pi pi-sitemap"></i> {{ project.workflow_count }}
                </span>
                <span class="stat" title="Experiments">
                  <i class="pi pi-chart-bar"></i> {{ project.experiment_count }}
                </span>
                <span class="stat" title="Models">
                  <i class="pi pi-box"></i> {{ project.model_count }}
                </span>
              </div>
              <div class="card-tags">
                <Tag v-if="project.technique" :value="project.technique" severity="secondary" class="card-tag" />
                <Tag v-if="project.sample_type" :value="project.sample_type" severity="secondary" class="card-tag" />
              </div>
            </div>
          </div>

          <!-- New Project Card -->
          <div class="project-card new-project-card" @click="showNewProjectDialog">
            <div class="new-card-content">
              <i class="pi pi-plus-circle"></i>
              <span>Create New Project</span>
            </div>
          </div>
        </div>
      </div>

      <!-- All Projects Table (shown when > 5 projects) -->
      <div v-if="projectStore.projects.length > 5" class="projects-section">
        <h3 class="section-title">All Projects ({{ projectStore.projects.length }})</h3>
        <div class="projects-table">
          <div class="table-header">
            <span class="th name">Name</span>
            <span class="th desc">Description</span>
            <span class="th tech">Technique</span>
            <span class="th date">Modified</span>
            <span class="th actions-col">Actions</span>
          </div>
          <div
            v-for="project in allProjectsSorted"
            :key="project.id"
            class="table-row"
            :class="{ active: project.id === projectStore.currentProjectId }"
            @click="selectAndOpen(project.id)"
          >
            <span class="td name">
              <i class="pi pi-folder"></i>
              {{ project.name }}
            </span>
            <span class="td desc">{{ truncate(project.description || '', 80) }}</span>
            <span class="td tech">{{ project.technique || '\u2014' }}</span>
            <span class="td date">{{ formatDate(project.updated_at) }}</span>
            <span class="td actions-col">
              <Button
                icon="pi pi-ellipsis-h"
                class="p-button-text p-button-rounded p-button-sm"
                @click.stop="toggleMenu($event, project.id)"
              />
            </span>
          </div>
        </div>
      </div>
    </template>

    <!-- Context Menu -->
    <Menu ref="menu" :model="menuItems" :popup="true" />

    <!-- Project Dialog (create/edit) -->
    <ProjectDialog
      v-model:visible="dialogVisible"
      :edit-project="editingProject"
      @create="onCreateProject"
      @update="onUpdateProject"
    />

    <TemplateWizardModal
      ref="templateWizardRef"
      v-model="templateWizardVisible"
      @instantiated="onTemplateInstantiated"
    />

    <!-- Save Dialog -->
    <Dialog
      v-model:visible="saveDialogVisible"
      header="Save Project"
      :modal="true"
      :style="{ width: '420px' }"
    >
      <div class="save-form">
        <div class="field">
          <label>Description (optional)</label>
          <InputText v-model="saveDescription" placeholder="What changed?" />
        </div>
        <div class="field-checkbox">
          <Checkbox v-model="saveIncludeRaw" :binary="true" inputId="include-raw" />
          <label for="include-raw">Include raw data files</label>
        </div>
      </div>
      <template #footer>
        <Button label="Cancel" class="p-button-text" @click="saveDialogVisible = false" />
        <Button label="Save Snapshot" icon="pi pi-save" @click="onSaveProject" />
      </template>
    </Dialog>

    <!-- Hidden file input for import -->
    <input
      ref="fileInput"
      type="file"
      accept=".spectrapy,.zip"
      style="display: none"
      @change="onFileSelected"
    />
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Menu from "primevue/menu";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Checkbox from "primevue/checkbox";
import ProgressSpinner from "primevue/progressspinner";
import { useToast } from "primevue/usetoast";
import { useAdvisorStore } from "@/stores/advisor";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore, type WorkflowTemplate } from "@/stores/workflow";
import type { ProjectSummary } from "@/types";
import ProjectDialog from "@/components/ProjectDialog.vue";
import type { ProjectFormData } from "@/components/ProjectDialog.vue";
import OnboardingBanner from "@/components/OnboardingBanner.vue";
import TemplateGallery from "@/views/workflow-builder/TemplateGallery.vue";
import TemplateWizardModal from "@/views/workflow-builder/modals/TemplateWizardModal.vue";

const router = useRouter();
const toast = useToast();
const projectStore = useProjectStore();
const workflowStore = useWorkflowStore();
const advisorStore = useAdvisorStore();

// R4 — Single-scope Sherpa Advisor routing for the Project tab.
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
const menu = ref();
const fileInput = ref<HTMLInputElement | null>(null);
const dialogVisible = ref(false);
const editingProject = ref<ProjectSummary | null>(null);
const activeMenuProjectId = ref<number | null>(null);
const templateWizardVisible = ref(false);
const templateWizardRef = ref<InstanceType<typeof TemplateWizardModal> | null>(null);
const selectedTemplateId = ref<number | null>(null);

// Save dialog
const saveDialogVisible = ref(false);
const saveDescription = ref("");
const saveIncludeRaw = ref(false);

onMounted(async () => {
  await projectStore.fetchProjects();
  try {
    await workflowStore.fetchTemplates();
  } catch {
    // Gallery renders the store-owned error state.
  }
  // If there's a current project, load its versions
  if (projectStore.currentProjectId) {
    await projectStore.fetchProject(projectStore.currentProjectId);
    await projectStore.fetchVersions(projectStore.currentProjectId);
  }
  void syncAdvisorForProject();
});

watch(
  () => projectStore.currentProjectId,
  (next) => {
    if (next != null) void syncAdvisorForProject();
  },
);

const allProjectsSorted = computed(() =>
  [...projectStore.projects].sort(
    (a, b) =>
      new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  )
);

const menuItems = computed(() => [
  {
    label: "Open",
    icon: "pi pi-folder-open",
    command: () => selectAndOpen(activeMenuProjectId.value!),
  },
  {
    label: "Edit",
    icon: "pi pi-pencil",
    command: () => editProject(activeMenuProjectId.value!),
  },
  {
    label: "Export",
    icon: "pi pi-download",
    command: () => doExportProject(activeMenuProjectId.value!),
  },
  { separator: true },
  {
    label: "Delete",
    icon: "pi pi-trash",
    class: "p-menuitem-danger",
    command: () => doDeleteProject(activeMenuProjectId.value!),
  },
]);

function toggleMenu(event: Event, projectId: number) {
  activeMenuProjectId.value = projectId;
  menu.value.toggle(event);
}

async function selectAndOpen(projectId: number) {
  await projectStore.selectProject(projectId);
  await projectStore.fetchVersions(projectId);
  router.push("/data");
}

function openTemplateWizard(template: WorkflowTemplate) {
  if (!projectStore.projects.length) {
    toast.add({
      severity: "warn",
      summary: "Create a Project First",
      detail: "Templates now belong to Projects so workflows keep their analysis context.",
      life: 4000,
    });
    return;
  }

  if (!projectStore.currentProjectId) {
    toast.add({
      severity: "warn",
      summary: "Select an Active Project",
      detail: "Choose the target project from the project context first, then launch the template.",
      life: 4000,
    });
    return;
  }

  selectedTemplateId.value = template.id;
  templateWizardVisible.value = true;
  templateWizardRef.value?.open(template);
}

async function onTemplateInstantiated(result: { workflowId: number; projectId: number | null; slug?: string }) {
  if (result.slug) {
    const matchedTemplate = workflowStore.templates.find((template) => template.slug === result.slug);
    if (matchedTemplate) {
      selectedTemplateId.value = matchedTemplate.id;
    }
  }
  if (result.projectId) {
    await projectStore.selectProject(result.projectId);
    await projectStore.fetchVersions(result.projectId);
  }
}

function continueProject() {
  router.push("/data");
}

function showNewProjectDialog() {
  editingProject.value = null;
  dialogVisible.value = true;
}

function editProject(projectId: number) {
  const project = projectStore.projects.find((p) => p.id === projectId);
  if (project) {
    editingProject.value = project;
    dialogVisible.value = true;
  }
}

async function doExportProject(projectId: number) {
  await projectStore.exportProject(projectId);
  toast.add({
    severity: "success",
    summary: "Project Exported",
    detail: "Project archive downloaded",
    life: 2000,
  });
}

async function doDeleteProject(projectId: number) {
  const project = projectStore.projects.find((p) => p.id === projectId);
  if (!project) return;

  if (confirm(`Delete "${project.name}"? This cannot be undone.`)) {
    const ok = await projectStore.deleteProject(projectId);
    if (ok) {
      toast.add({
        severity: "info",
        summary: "Project Deleted",
        detail: `"${project.name}" has been removed`,
        life: 2000,
      });
    }
  }
}

function triggerImport() {
  fileInput.value?.click();
}

async function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  const project = await projectStore.importProject(file);
  if (project) {
    toast.add({
      severity: "success",
      summary: "Project Imported",
      detail: `Imported "${project.name}"`,
      life: 2000,
    });
  } else {
    toast.add({
      severity: "error",
      summary: "Import Failed",
      detail: projectStore.error || "Unable to import project file",
      life: 3000,
    });
  }
  input.value = "";
}

async function onCreateProject(data: ProjectFormData) {
  const project = await projectStore.createProject({
    name: data.name,
    description: data.description || null,
    technique: data.technique,
    sample_type: data.sample_type,
  });
  if (project) {
    toast.add({
      severity: "success",
      summary: "Project Created",
      detail: `Created "${project.name}"`,
      life: 2000,
    });
  }
}

async function onUpdateProject(data: ProjectFormData) {
  const id = editingProject.value?.id || activeMenuProjectId.value;
  if (!id) return;

  const updated = await projectStore.updateProject(id, {
    name: data.name,
    description: data.description || null,
    technique: data.technique,
    sample_type: data.sample_type,
  });
  if (updated) {
    toast.add({
      severity: "success",
      summary: "Project Updated",
      detail: "Changes saved",
      life: 2000,
    });
  }
}

function openSaveDialog() {
  saveDescription.value = "";
  saveIncludeRaw.value = false;
  saveDialogVisible.value = true;
}

async function onSaveProject() {
  if (!projectStore.currentProjectId) return;
  saveDialogVisible.value = false;

  const ver = await projectStore.saveProject(projectStore.currentProjectId, {
    change_description: saveDescription.value || null,
    include_raw_data: saveIncludeRaw.value,
  });
  if (ver) {
    toast.add({
      severity: "success",
      summary: "Project Saved",
      detail: `Version ${ver.version_number} created`,
      life: 2000,
    });
  }
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, max) + "...";
}

function techniqueIcon(project: ProjectSummary): string {
  const tech = (project.technique || "").toLowerCase();
  if (["ftir", "ir", "infrared", "nir"].some((t) => tech.includes(t))) return "pi pi-wave-pulse";
  if (tech.includes("raman")) return "pi pi-sun";
  if (["nmr", "1h", "13c"].some((t) => tech.includes(t))) return "pi pi-bolt";
  if (["uv", "uv-vis", "visible"].some((t) => tech.includes(t))) return "pi pi-eye";
  return "pi pi-folder";
}

function iconClass(project: ProjectSummary): string {
  const tech = (project.technique || "").toLowerCase();
  if (["ftir", "ir", "infrared", "nir"].some((t) => tech.includes(t))) return "icon-ir";
  if (tech.includes("raman")) return "icon-raman";
  if (["nmr", "1h", "13c"].some((t) => tech.includes(t))) return "icon-nmr";
  if (["uv", "uv-vis", "visible"].some((t) => tech.includes(t))) return "icon-uv";
  return "icon-default";
}
</script>

<style scoped>
.project-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.templates-panel {
  padding: 1.25rem;
  border: 1px solid var(--surface-border);
  border-radius: 14px;
  background: var(--surface-card);
}

.empty-templates-panel {
  margin-top: 1.5rem;
  width: 100%;
  max-width: 980px;
}

.templates-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1rem;
}

.templates-header h3 {
  margin: 0 0 0.35rem;
}

.templates-subtitle,
.templates-header p {
  margin: 0;
  color: var(--text-color-secondary);
  line-height: 1.5;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-header h1 {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

/* Loading / Empty */
.loading-container,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
  color: #64748b;
  text-align: center;
}

.empty-state i {
  font-size: 3rem;
  color: #cbd5e1;
}

.empty-state h3 {
  margin: 0;
  color: #334155;
}

.empty-state p {
  margin: 0;
  max-width: 400px;
}

/* Current project banner */
.current-project-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  border: 1px solid #bfdbfe;
  border-radius: 12px;
  padding: 20px 24px;
  gap: 24px;
}

.banner-left {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex: 1;
}

.banner-icon {
  font-size: 1.75rem;
  color: #3b82f6;
  margin-top: 2px;
}

.banner-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.banner-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #3b82f6;
  font-weight: 600;
}

.banner-name {
  margin: 0;
  font-size: 1.2rem;
  font-weight: 600;
  color: #1e293b;
}

.banner-desc {
  margin: 0;
  font-size: 0.9rem;
  color: #64748b;
}

.banner-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}

.banner-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.banner-stats {
  display: flex;
  gap: 14px;
}

.banner-buttons {
  display: flex;
  gap: 8px;
}

/* Version history */
.version-list {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  overflow: hidden;
  max-height: 240px;
  overflow-y: auto;
}

.version-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
}

.version-row:last-child {
  border-bottom: none;
}

.version-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-number {
  font-weight: 600;
  color: #3b82f6;
  font-size: 0.9rem;
  min-width: 36px;
}

.version-desc {
  color: #475569;
  font-size: 0.9rem;
}

.version-meta {
  display: flex;
  align-items: center;
  gap: 12px;
}

.version-tag {
  font-size: 0.7rem;
}

.version-date {
  color: #94a3b8;
  font-size: 0.85rem;
  white-space: nowrap;
}

/* Projects sections */
.projects-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.section-title {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: #334155;
  padding-bottom: 8px;
  border-bottom: 1px solid #e2e8f0;
}

/* Project cards grid */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.project-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.project-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
}

.project-card.active {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.card-icon i {
  font-size: 1.15rem;
}

.icon-ir { background: #fef3c7; }
.icon-ir i { color: #d97706; }
.icon-raman { background: #dcfce7; }
.icon-raman i { color: #16a34a; }
.icon-nmr { background: #fce7f3; }
.icon-nmr i { color: #db2777; }
.icon-uv { background: #ede9fe; }
.icon-uv i { color: #7c3aed; }
.icon-default { background: #f1f5f9; }
.icon-default i { color: #64748b; }

.card-meta {
  flex: 1;
  min-width: 0;
}

.card-name {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.card-date {
  font-size: 0.8rem;
  color: #94a3b8;
}

.card-menu-btn {
  flex-shrink: 0;
}

.card-description {
  margin: 0;
  font-size: 0.875rem;
  color: #64748b;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
}

.card-stats {
  display: flex;
  gap: 12px;
}

.stat {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 0.8rem;
  color: #94a3b8;
}

.stat i {
  font-size: 0.85rem;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.card-tag {
  font-size: 0.7rem;
}

/* New project card */
.new-project-card {
  border-style: dashed;
  border-color: #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
}

.new-project-card:hover {
  border-color: #3b82f6;
  background: #f8fafc;
}

.new-card-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #94a3b8;
}

.new-card-content i {
  font-size: 2rem;
}

.new-card-content span {
  font-weight: 500;
}

.new-project-card:hover .new-card-content {
  color: #3b82f6;
}

/* Projects table */
.projects-table {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  overflow: hidden;
}

.table-header {
  display: grid;
  grid-template-columns: 1.5fr 2fr 100px 100px 60px;
  padding: 12px 16px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.8rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.table-row {
  display: grid;
  grid-template-columns: 1.5fr 2fr 100px 100px 60px;
  padding: 12px 16px;
  border-bottom: 1px solid #f1f5f9;
  cursor: pointer;
  transition: background 0.15s;
  align-items: center;
}

.table-row:hover {
  background: #f8fafc;
}

.table-row.active {
  background: #eff6ff;
}

.table-row:last-child {
  border-bottom: none;
}

.td.name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  color: #1e293b;
}

.td.name i {
  color: #94a3b8;
}

.td.desc {
  color: #64748b;
  font-size: 0.875rem;
}

.td.tech {
  font-size: 0.85rem;
  color: #64748b;
}

.td.date {
  font-size: 0.85rem;
  color: #94a3b8;
}

.td.actions-col {
  text-align: right;
}

.project-tag {
  font-size: 0.75rem;
}

/* Save form */
.save-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.save-form .field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.save-form .field label {
  font-weight: 500;
  font-size: 0.9rem;
  color: #334155;
}

.field-checkbox {
  display: flex;
  align-items: center;
  gap: 8px;
}

.field-checkbox label {
  font-size: 0.9rem;
  color: #475569;
}

@media (max-width: 768px) {
  .projects-grid {
    grid-template-columns: 1fr;
  }

  .current-project-banner {
    flex-direction: column;
    align-items: stretch;
  }

  .banner-actions {
    flex-direction: row;
    justify-content: space-between;
    align-items: center;
  }

  .table-header,
  .table-row {
    grid-template-columns: 1fr 100px 60px;
  }

  .th.desc,
  .th.tech,
  .td.desc,
  .td.tech {
    display: none;
  }
}
</style>
