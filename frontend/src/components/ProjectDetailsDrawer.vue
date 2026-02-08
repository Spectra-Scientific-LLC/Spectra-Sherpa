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
        <h3 class="section-title">{{ project.metadata.name }}</h3>
        <p v-if="project.metadata.description" class="project-description">
          {{ project.metadata.description }}
        </p>

        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">Author</span>
            <span class="meta-value">{{ project.metadata.author }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Created</span>
            <span class="meta-value">{{ formatDate(project.metadata.created) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Modified</span>
            <span class="meta-value">{{ formatDate(project.metadata.modified) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Version</span>
            <span class="meta-value">{{ project.metadata.version }}</span>
          </div>
        </div>

        <div v-if="project.metadata.tags.length" class="tags-container">
          <Tag
            v-for="tag in project.metadata.tags"
            :key="tag"
            :value="tag"
            severity="info"
            class="project-tag"
          />
        </div>
      </section>

      <!-- Experiments Section -->
      <section class="section">
        <div class="section-header">
          <h4 class="section-subtitle">
            <i class="pi pi-flask"></i>
            Experiments ({{ projectExperiments.length }})
          </h4>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm"
            title="Go to Experiments"
            @click="navigateToExperiments"
          />
        </div>

        <div v-if="loading" class="loading-state">
          <ProgressSpinner style="width: 30px; height: 30px" />
          <span>Loading experiments...</span>
        </div>

        <div v-else-if="projectExperiments.length === 0" class="empty-state">
          <i class="pi pi-inbox"></i>
          <span>No experiments linked to this project</span>
        </div>

        <div v-else class="experiments-list">
          <div
            v-for="exp in projectExperiments"
            :key="exp.id"
            class="experiment-card"
            @click="openExperiment(exp.id)"
          >
            <div class="exp-header">
              <span class="exp-name">{{ exp.name }}</span>
              <Badge :value="exp.file_count || 0" severity="info" />
            </div>
            <div class="exp-details">
              <span v-if="exp.description" class="exp-description">
                {{ truncate(exp.description, 60) }}
              </span>
              <span class="exp-date">{{ formatDate(exp.created_at) }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Workflows Section -->
      <section class="section">
        <div class="section-header">
          <h4 class="section-subtitle">
            <i class="pi pi-sitemap"></i>
            Workflows ({{ project.data.workflows.length }})
          </h4>
          <Button
            icon="pi pi-external-link"
            class="p-button-text p-button-sm"
            title="Go to Workflow Builder"
            @click="navigateToWorkflows"
          />
        </div>

        <div v-if="project.data.workflows.length === 0" class="empty-state">
          <i class="pi pi-inbox"></i>
          <span>No workflows in this project</span>
        </div>

        <div v-else class="workflows-list">
          <div
            v-for="workflow in project.data.workflows"
            :key="workflow"
            class="workflow-item"
            @click="openWorkflow(workflow)"
          >
            <i class="pi pi-share-alt"></i>
            <span>{{ formatWorkflowName(workflow) }}</span>
          </div>
        </div>
      </section>

      <!-- Project Settings -->
      <section v-if="Object.keys(project.data.settings).length" class="section">
        <h4 class="section-subtitle">
          <i class="pi pi-cog"></i>
          Project Settings
        </h4>
        <div class="settings-list">
          <div
            v-for="(value, key) in project.data.settings"
            :key="key"
            class="setting-item"
          >
            <span class="setting-key">{{ formatSettingKey(String(key)) }}</span>
            <span class="setting-value">{{ formatSettingValue(value) }}</span>
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
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import Sidebar from "primevue/sidebar";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Badge from "primevue/badge";
import ProgressSpinner from "primevue/progressspinner";
import { useProjectStore, type Project } from "@/stores/project";
import { useExperimentStore } from "@/stores/experiment";
import type { ExperimentSummary } from "@/types";

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const router = useRouter();
const projectStore = useProjectStore();
const experimentStore = useExperimentStore();

const loading = ref(false);
const projectExperiments = ref<ExperimentSummary[]>([]);

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const project = computed<Project | null>(() => projectStore.currentProject);

// Watch for project changes to load experiments
watch(
  () => project.value?.id,
  async (newId) => {
    if (newId && visible.value) {
      await loadProjectExperiments();
    }
  }
);

// Watch for drawer opening
watch(visible, async (isVisible) => {
  if (isVisible && project.value) {
    await loadProjectExperiments();
  }
});

async function loadProjectExperiments() {
  if (!project.value) return;

  loading.value = true;
  try {
    // Make sure experiments are loaded
    if (experimentStore.experiments.length === 0) {
      await experimentStore.fetchExperiments();
    }

    // Filter experiments that belong to this project
    const projectExpIds = project.value.data.experiments;
    projectExperiments.value = experimentStore.experiments.filter((exp) =>
      projectExpIds.includes(exp.id)
    );
  } catch (error) {
    console.error("Failed to load project experiments:", error);
  } finally {
    loading.value = false;
  }
}

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

function formatWorkflowName(workflowId: string): string {
  return workflowId
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatSettingKey(key: string): string {
  return key
    .replace(/([A-Z])/g, " $1")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

function formatSettingValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}

function navigateToExperiments() {
  visible.value = false;
  router.push("/experiments");
}

function navigateToWorkflows() {
  visible.value = false;
  router.push("/workflow-builder");
}

function openExperiment(experimentId: number) {
  visible.value = false;
  router.push("/experiments");
  // Select the experiment in the store
  experimentStore.selectExperiment(experimentId);
}

function openWorkflow(workflowId: string) {
  visible.value = false;
  router.push("/workflow-builder");
  // TODO: Load workflow when implemented
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

.loading-state,
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

.exp-date {
  font-size: 0.75rem;
  color: #94a3b8;
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
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.workflow-item:hover {
  background: #f1f5f9;
  transform: translateX(4px);
}

.workflow-item i {
  color: #64748b;
}

.settings-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.setting-key {
  font-size: 0.85rem;
  color: #64748b;
}

.setting-value {
  font-size: 0.85rem;
  color: #334155;
  font-weight: 500;
  max-width: 60%;
  text-align: right;
  word-break: break-word;
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
