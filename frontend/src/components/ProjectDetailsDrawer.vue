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
            @click="openWorkflow(wf.id)"
          >
            <i class="pi pi-share-alt"></i>
            <div class="workflow-info">
              <span class="workflow-name">{{ wf.name }}</span>
              <span class="workflow-status">{{ wf.status }}</span>
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
import Sidebar from "primevue/sidebar";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Badge from "primevue/badge";
import { useProjectStore } from "@/stores/project";
import type { ProjectDetail } from "@/types";

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const router = useRouter();
const projectStore = useProjectStore();

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

function navigateToData() {
  visible.value = false;
  router.push("/data");
}

function navigateToWorkflows() {
  visible.value = false;
  router.push("/workflow");
}

function openExperiment(_experimentId: number) {
  visible.value = false;
  router.push("/data");
}

function openWorkflow(_workflowId: number) {
  visible.value = false;
  router.push("/workflow");
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
