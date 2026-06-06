<template>
  <section class="simplified-dashboard">
    <!-- Hero: the three top-level jobs of the dashboard (pick / start / import). -->
    <div class="hero-section">
      <div class="hero-content">
        <h1>Dashboard</h1>
      </div>
      <div class="hero-actions">
        <Button
          label="New Analysis"
          icon="pi pi-bolt"
          class="hero-btn"
          @click="startAnalysisFlow"
        />
      </div>
    </div>

    <!-- Current Project: explicit, low-ornament line. Eyebrow + name on
         the left; last-touched timestamp + Open arrow on the right. The
         project's card below also carries the accent stripe + tag, so the
         user gets the signal both at the top of the page and in the list. -->
    <div v-if="projectStore.currentProject" class="current-strip">
      <div class="current-strip__main">
        <span class="eyebrow">Current Project</span>
        <strong class="current-strip__name">
          {{ projectStore.currentProject.name }}
        </strong>
      </div>
      <div class="current-strip__meta">
        <span
          class="current-strip__time"
          :title="absoluteTimestamp(projectStore.currentProject.updated_at)"
        >
          {{ formatRelative(projectStore.currentProject.updated_at) }}
        </span>
        <Button
          icon="pi pi-arrow-right"
          class="p-button-text p-button-sm"
          aria-label="Open current project"
          @click="router.push('/project')"
        />
      </div>
    </div>

    <!-- Primary surface: pick the right project from the user's set.
         Clicking the already-active card jumps into /project; clicking
         an inactive card selects it. One click pattern, two outcomes. -->
    <div class="projects-section">
      <div class="section-header">
        <h2>Your Projects</h2>
        <span class="muted-count" v-if="projectStore.projects.length">
          {{ projectStore.projects.length }}
        </span>
      </div>

      <div v-if="projectStore.projects.length" class="filter-strip">
        <InputText
          v-model="projectFilter"
          placeholder="Search"
          class="filter-input"
        />
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
                aria-label="Delete project"
                @click.stop="requestDelete(project)"
                @keydown.stop
              >
                <i class="pi pi-trash"></i>
              </button>
            </div>
          </div>
          <p v-if="project.description" class="project-description">
            {{ project.description }}
          </p>
          <div class="project-metrics">
            <span><strong>{{ project.experiment_count }}</strong> datasets</span>
            <span><strong>{{ project.workflow_count }}</strong> workflows</span>
            <span><strong>{{ project.model_count }}</strong> artifacts</span>
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

    <!-- Modals (unchanged flows) -->
    <ProjectDialog
      v-model:visible="projectDialogVisible"
      :edit-project="null"
      @create="onCreateProject"
    />

    <Dialog
      v-model:visible="templateGalleryVisible"
      modal
      header="New Analysis"
      :style="{ width: '880px' }"
      class="new-analysis-dialog"
    >
      <div class="new-analysis">
        <!-- Blank Project as the first starter; the template gallery
             below already gives the user "choose template" by direct
             selection, so no parallel tile is needed. -->
        <article class="starter-card">
          <div class="starter-card__body">
            <h5>Blank Project</h5>
            <p>Empty project, no preset workflow. Add data and build workflows yourself.</p>
          </div>
          <Button
            label="Start"
            icon="pi pi-arrow-right"
            icon-pos="right"
            class="p-button-outlined"
            @click="startBlankProject"
          />
        </article>

        <TemplateGallery
          :selected-template-id="selectedTemplateId"
          :show-header="false"
          @select="openTemplateWizard"
        />
      </div>
    </Dialog>

    <TemplateWizardModal
      ref="templateWizardRef"
      v-model="templateWizardVisible"
      project-creation-mode="always"
      landing-route="/project"
      @instantiated="onTemplateInstantiated"
    />

    <!-- Delete confirmation: small, named, hairline-style. -->
    <Dialog
      v-model:visible="deleteConfirmVisible"
      modal
      header="Delete project"
      :style="{ width: '420px' }"
    >
      <p class="delete-confirm__body">
        Delete <strong>{{ projectToDelete?.name }}</strong>?
        This removes the project and its workflows, models, and history.
        It cannot be undone.
      </p>
      <template #footer>
        <Button
          label="Cancel"
          class="p-button-text"
          @click="deleteConfirmVisible = false"
        />
        <Button
          label="Delete"
          icon="pi pi-trash"
          severity="danger"
          :loading="deleting"
          @click="confirmDelete"
        />
      </template>
    </Dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import Button from "primevue/button";
import Dialog from "primevue/dialog";
import InputText from "primevue/inputtext";
import Tag from "primevue/tag";
import { useToast } from "primevue/usetoast";
import ProjectDialog, { type ProjectFormData } from "@/components/ProjectDialog.vue";
import { useProjectStore } from "@/stores/project";
import { useWorkflowStore, type WorkflowTemplate } from "@/stores/workflow";
import type { ProjectSummary } from "@/types";
import TemplateGallery from "@/views/workflow-builder/TemplateGallery.vue";
import TemplateWizardModal from "@/views/workflow-builder/modals/TemplateWizardModal.vue";

const router = useRouter();
const toast = useToast();
const projectStore = useProjectStore();
const workflowStore = useWorkflowStore();

const projectDialogVisible = ref(false);
const templateGalleryVisible = ref(false);
const templateWizardVisible = ref(false);
const templateWizardRef = ref<InstanceType<typeof TemplateWizardModal> | null>(null);
const selectedTemplateId = ref<number | null>(null);

const projectFilter = ref("");

// Delete confirmation state — small inline dialog rather than native
// confirm() so the V2 look stays consistent.
const deleteConfirmVisible = ref(false);
const deleting = ref(false);
const projectToDelete = ref<ProjectSummary | null>(null);

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
    workflowStore.fetchTemplates(),
  ]);
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
  // Opens the New Analysis modal directly. Templates can spawn their own
  // project (TemplateWizard handles that), and "Blank Project" inside the
  // modal opens the project dialog when the user chooses that path —
  // so no upfront project-required gate.
  templateGalleryVisible.value = true;
}

function startBlankProject(): void {
  // Close the New Analysis modal and open the create-project dialog.
  templateGalleryVisible.value = false;
  projectDialogVisible.value = true;
}

function requestDelete(project: ProjectSummary): void {
  projectToDelete.value = project;
  deleteConfirmVisible.value = true;
}

async function confirmDelete(): Promise<void> {
  const target = projectToDelete.value;
  if (!target) return;
  deleting.value = true;
  try {
    const ok = await projectStore.deleteProject(target.id);
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
  }
}

async function onCreateProject(data: ProjectFormData): Promise<void> {
  const project = await projectStore.createProject({
    name: data.name,
    description: data.description || null,
    technique: data.technique,
    sample_type: data.sample_type,
  });
  if (project) {
    toast.add({
      severity: "success",
      summary: `Created ${project.name}`,
      life: 2000,
    });
    projectDialogVisible.value = false;
  }
}

async function openTemplateWizard(template: WorkflowTemplate): Promise<void> {
  templateGalleryVisible.value = false;
  selectedTemplateId.value = template.id;
  templateWizardVisible.value = true;
  // Wait for the wizard modal to mount before calling open() — avoids the
  // race the older 50ms setTimeout was papering over.
  await nextTick();
  templateWizardRef.value?.open(template);
}

async function onTemplateInstantiated(result: {
  workflowId: number;
  projectId: number | null;
  slug?: string;
}): Promise<void> {
  if (result.projectId && projectStore.currentProjectId !== result.projectId) {
    await projectStore.selectProject(result.projectId);
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
  gap: 2rem;
  padding: 0 1rem;
  color: var(--text-color);
  font-size: 0.9375rem;
  line-height: 1.5;
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
  transition: color 0.15s ease, background 0.15s ease;
  font: inherit;
  line-height: 1;
}

.trash-btn:hover {
  color: var(--red-500);
  background: color-mix(in srgb, var(--red-500) 10%, transparent);
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
