<template>
  <Sidebar
    v-model:visible="visible"
    position="right"
    :style="{ width: '450px' }"
    class="project-details-drawer"
  >
    <template #header>
      <div class="drawer-header">
        <i class="pi pi-folder-open header-icon"></i>
        <span class="header-title">Project Details</span>
      </div>
    </template>

    <div v-if="project" class="drawer-content">
      <!-- Project Metadata -->
      <section class="section">
        <h3 class="section-title">{{ project.name }}</h3>
        <p v-if="project.description" class="project-description">
          {{ project.description }}
        </p>

        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">Technique</span>
            <span class="meta-value">{{ project.technique || "\u2014" }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Sample Type</span>
            <span class="meta-value">{{ project.sample_type || "\u2014" }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Created</span>
            <span class="meta-value">{{ formatDate(project.created_at) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Modified</span>
            <span class="meta-value">{{ formatDate(project.updated_at) }}</span>
          </div>
        </div>

        <div class="tags-container">
          <Tag v-if="project.technique" :value="project.technique" severity="info" class="project-tag" />
          <Tag v-if="project.sample_type" :value="project.sample_type" severity="secondary" class="project-tag" />
        </div>
      </section>

      <!-- Data Sources Section -->
      <section class="section">
        <div class="section-header">
          <h4 class="section-subtitle">
            <i class="pi pi-database"></i>
            Data Sources ({{ project.data_sources?.length ?? 0 }})
          </h4>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm"
            title="Go to Data"
            @click="navigateToData"
          />
        </div>

        <div v-if="(project.data_sources?.length ?? 0) === 0" class="empty-state">
          <i class="pi pi-inbox"></i>
          <span>No data sources detected for this project</span>
        </div>

        <div v-else class="data-source-list">
          <div
            v-for="dataSource in project.data_sources ?? []"
            :key="dataSource.id"
            class="data-source-card"
          >
            <div class="data-source-header">
              <span
                class="data-source-color"
                :style="{ backgroundColor: dataSource.color }"
                aria-hidden="true"
              ></span>
              <div class="data-source-copy">
                <span class="data-source-name">{{ dataSource.display_name }}</span>
                <span class="data-source-meta">{{ dataSource.source_type }}</span>
              </div>
            </div>
            <div class="data-source-workflows">
              <span class="data-source-label">Sheets</span>
              <span class="data-source-value">
                {{ workflowNamesForDataSource(dataSource.id) || "\u2014" }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- Experiments Section -->
      <section class="section">
        <div class="section-header">
          <h4 class="section-subtitle">
            <i class="pi pi-flask"></i>
            Experiments ({{ project.experiments.length }})
          </h4>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm"
            title="Go to Data"
            @click="navigateToData"
          />
        </div>

        <div v-if="project.experiments.length === 0" class="empty-state">
          <i class="pi pi-inbox"></i>
          <span>No experiments linked to this project</span>
        </div>

        <div v-else class="experiments-list">
          <div
            v-for="exp in project.experiments"
            :key="exp.id"
            class="experiment-card"
            @click="openExperiment(exp.id)"
          >
            <div class="exp-header">
              <span class="exp-name">{{ exp.name }}</span>
              <Badge :value="exp.file_count || 0" severity="info" />
            </div>
            <div v-if="exp.description" class="exp-details">
              <span class="exp-description">{{ truncate(exp.description, 60) }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Workflows Section -->
      <section class="section">
        <div class="section-header">
          <h4 class="section-subtitle">
            <i class="pi pi-sitemap"></i>
            Workflows ({{ project.workflows.length }})
          </h4>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm"
            title="Go to Workflow Builder"
            @click="navigateToWorkflows"
          />
        </div>

        <div v-if="project.workflows.length === 0" class="empty-state">
          <i class="pi pi-inbox"></i>
          <span>No workflows in this project</span>
        </div>

        <div v-else class="workflows-list">
          <div
            v-for="wf in project.workflows"
            :key="wf.id"
            class="workflow-item"
            :class="{ active: isActiveWorkflow(wf.id) }"
            @click="openWorkflow(wf.id)"
          >
            <i class="pi pi-share-alt"></i>
            <div class="workflow-info">
              <span class="workflow-name">{{ wf.name }}</span>
              <span class="workflow-status">{{ wf.status }}</span>
              <span v-if="workflowPrimaryDataName(wf)" class="workflow-data">
                {{ workflowPrimaryDataName(wf) }}
              </span>
              <span v-if="wf.created_from_template_name" class="workflow-template">
                Created from {{ wf.created_from_template_name }}
              </span>
              <span v-else-if="wf.created_from_workflow_id" class="workflow-template ai-generated">
                <i class="pi pi-sparkles"></i>
                <span class="ai-chip">AI</span>
                Generated from: {{ wf.created_from_workflow_name || `Sheet #${wf.created_from_workflow_id}` }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <!-- Sub-Projects -->
      <section v-if="project.children && project.children.length" class="section">
        <h4 class="section-subtitle">
          <i class="pi pi-folder"></i>
          Sub-Projects ({{ project.children.length }})
        </h4>
        <div class="children-list">
          <div
            v-for="child in project.children"
            :key="child.id"
            class="child-item"
            @click="openSubProject(child.id)"
          >
            <i class="pi pi-folder"></i>
            <span>{{ child.name }}</span>
          </div>
        </div>
      </section>
    </div>

    <div v-else class="drawer-empty">
      <i class="pi pi-folder"></i>
      <p>No project selected</p>
    </div>
  </Sidebar>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useToast } from "primevue/usetoast";
import Sidebar from "primevue/sidebar";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Badge from "primevue/badge";
import { useProjectStore } from "@/stores/project";
import { useWorkbookStore } from "@/stores/workbook";
import { getErrorMessage } from "@/utils/errors";
import type { ProjectDetail, WorkflowBrief } from "@/types";

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const router = useRouter();
const toast = useToast();
const projectStore = useProjectStore();
const workbookStore = useWorkbookStore();

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const project = computed<ProjectDetail | null>(() => projectStore.currentProject);

function formatDate(dateString: string): string {
  const date = new Date(dateString);
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

function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength) + "...";
}

function workflowNamesForDataSource(dataSourceId: number): string {
  const names =
    project.value?.workflows
      .filter((workflow) => workflow.data_source_ids?.includes(dataSourceId))
      .map((workflow) => workflow.name) ?? [];
  return names.join(", ");
}

function workflowPrimaryDataName(workflow: WorkflowBrief): string {
  const dataSourceId = workflow.primary_data_source_id;
  if (!dataSourceId) return "";
  const dataSource = project.value?.data_sources?.find((item) => item.id === dataSourceId);
  return dataSource ? `Data: ${dataSource.display_name}` : "";
}

async function navigateToData() {
  // Pin the drawer's project as the destination context so the Data view
  // doesn't read from a stale `currentProjectId` set by an earlier session.
  const targetProjectId = project.value?.id ?? projectStore.currentProjectId;
  visible.value = false;
  if (targetProjectId !== null && projectStore.currentProjectId !== targetProjectId) {
    await projectStore.selectProject(targetProjectId);
  }
  router.push({
    path: "/data",
    query: targetProjectId !== null ? { project_id: String(targetProjectId) } : {},
  });
}

async function navigateToWorkflows() {
  const targetProjectId = project.value?.id ?? projectStore.currentProjectId;
  visible.value = false;
  if (targetProjectId !== null && projectStore.currentProjectId !== targetProjectId) {
    await projectStore.selectProject(targetProjectId);
  }
  router.push({
    path: "/workflow",
    query: targetProjectId !== null ? { project_id: String(targetProjectId) } : {},
  });
}

async function openExperiment(_experimentId: number) {
  const targetProjectId = project.value?.id ?? projectStore.currentProjectId;
  visible.value = false;
  if (targetProjectId !== null && projectStore.currentProjectId !== targetProjectId) {
    await projectStore.selectProject(targetProjectId);
  }
  router.push({
    path: "/data",
    query: targetProjectId !== null ? { project_id: String(targetProjectId) } : {},
  });
}

function isActiveWorkflow(workflowId: number): boolean {
  return workbookStore.activeSheet?.workflowId === workflowId;
}

async function openWorkflow(workflowId: number) {
  const targetProjectId = project.value?.id ?? projectStore.currentProjectId;
  if (targetProjectId === null) {
    return;
  }

  try {
    await workbookStore.selectWorkflowSheet(workflowId, targetProjectId);
    visible.value = false;
    await router.push("/workflow");
  } catch (err: unknown) {
    toast.add({
      severity: "error",
      summary: "Workflow Selection Failed",
      detail: getErrorMessage(err, "Unable to open the selected workflow"),
      life: 4000,
    });
  }
}

async function openSubProject(projectId: number) {
  await projectStore.selectProject(projectId);
  // Stay on drawer to see the sub-project details
}
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  font-size: 1.2rem;
  color: #3b82f6;
}

.header-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: #1e293b;
}

.drawer-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding: 8px 0;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: #1e293b;
}

.project-description {
  margin: 0;
  color: #64748b;
  font-size: 0.9rem;
  line-height: 1.5;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.meta-label {
  font-size: 0.75rem;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.meta-value {
  font-size: 0.9rem;
  color: #334155;
  font-weight: 500;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.project-tag {
  font-size: 0.75rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.section-subtitle {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #475569;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-subtitle i {
  color: #64748b;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px;
  color: #94a3b8;
  text-align: center;
}

.empty-state i {
  font-size: 2rem;
}

.experiments-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.data-source-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.data-source-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.data-source-color {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid rgba(15, 23, 42, 0.16);
  flex: 0 0 auto;
}

.data-source-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.data-source-name {
  color: #1e293b;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.data-source-meta,
.data-source-label,
.workflow-data,
.workflow-template {
  color: #64748b;
  font-size: 0.75rem;
}

.ai-generated i {
  color: #a855f7;
  font-size: 0.7rem;
  margin-right: 4px;
}

.ai-chip {
  background: #a855f7;
  border-radius: 4px;
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
  margin-right: 4px;
  padding: 1px 4px;
}

.data-source-workflows {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 8px;
  align-items: start;
}

.data-source-value {
  color: #334155;
  font-size: 0.78rem;
  line-height: 1.3;
}

.experiment-card {
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s;
}

.experiment-card:hover {
  background: #f1f5f9;
  border-color: #cbd5e1;
  transform: translateX(4px);
}

.exp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.exp-name {
  font-weight: 500;
  color: #1e293b;
}

.exp-details {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.exp-description {
  font-size: 0.85rem;
  color: #64748b;
}

.workflows-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.workflow-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.workflow-item:hover {
  background: #f1f5f9;
  transform: translateX(4px);
}

.workflow-item.active {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.workflow-item i {
  color: #64748b;
}

.workflow-info {
  display: flex;
  flex-direction: column;
}

.workflow-name {
  font-weight: 500;
  color: #1e293b;
}

.workflow-status {
  font-size: 0.75rem;
  color: #94a3b8;
}

.children-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.child-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #f8fafc;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.child-item:hover {
  background: #f1f5f9;
  transform: translateX(4px);
}

.child-item i {
  color: #d97706;
}

.drawer-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #94a3b8;
}

.drawer-empty i {
  font-size: 3rem;
  margin-bottom: 12px;
}
</style>
