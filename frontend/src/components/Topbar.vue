<template>
  <header class="topbar">
    <div class="topbar-left">
      <button
        type="button"
        class="nav-collapse-toggle"
        :aria-label="props.navCollapsed ? 'Expand navigation' : 'Collapse navigation'"
        :title="props.navCollapsed ? 'Expand navigation' : 'Collapse navigation'"
        @click="emit('toggle-nav')"
      >
        <i class="pi" :class="props.navCollapsed ? 'pi-chevron-right' : 'pi-chevron-left'"></i>
      </button>

      <!-- Global Project Context - Hidden when chat is open -->
      <div v-if="chatCollapsed" class="project-selector">
        <i class="pi pi-folder-open project-icon"></i>
        <span
          v-if="projectStore.currentProject"
          class="active-project-title"
          data-test="active-project-title"
          :title="projectStore.currentProject.name"
        >
          {{ projectStore.currentProject.name }}
        </span>
        <Dropdown
          v-model="selectedProjectId"
          :options="projectStore.projectList"
          optionLabel="name"
          optionValue="id"
          placeholder="Select Project"
          class="project-dropdown"
          @change="onProjectChange"
        >
          <template #value="slotProps">
            <span v-if="slotProps.value" class="project-value">
              {{ getProjectName(slotProps.value) }}
            </span>
            <span v-else class="project-placeholder">No Project</span>
          </template>
          <template #option="slotProps">
            <div class="project-option">
              <span class="project-option-name">{{ slotProps.option.name }}</span>
              <span class="project-option-date">{{ slotProps.option.modified }}</span>
            </div>
          </template>
          <template #footer>
            <div class="project-dropdown-footer">
              <Button
                label="New Project"
                icon="pi pi-plus"
                class="p-button-text p-button-sm"
                @click="showNewProjectDialog"
              />
              <Button
                label="Import"
                icon="pi pi-upload"
                class="p-button-text p-button-sm"
                @click="triggerImport"
              />
            </div>
          </template>
        </Dropdown>
        <Button
          v-if="projectStore.currentProject"
          icon="pi pi-info-circle"
          class="p-button-text p-button-rounded p-button-sm project-info-btn"
          aria-label="Project details"
          title="View project details"
          @click="showProjectDetails"
        />
        <Button
          v-if="projectStore.currentProject"
          icon="pi pi-cog"
          class="p-button-text p-button-rounded p-button-sm project-settings-btn"
          aria-label="Project settings"
          title="Edit project settings"
          @click="showEditProjectDialog"
        />
      </div>
    </div>

    <div class="topbar-center">
      <!-- Status Indicators (Traffic Lights) -->
      <div class="status-indicators">
        <div class="status-light" :class="backendStatus.class">
          <span class="status-tooltip">{{ backendStatus.tooltip }}</span>
        </div>
        <div class="status-light" :class="dataStatus.class">
          <span class="status-tooltip">{{ dataStatus.tooltip }}</span>
        </div>
        <div class="status-light" :class="workflowStatus.class">
          <span class="status-tooltip">{{ workflowStatus.tooltip }}</span>
        </div>
        <div class="status-light" :class="llmStatus.class">
          <span class="status-tooltip">{{ llmStatus.tooltip }}</span>
        </div>
        <div class="status-light" :class="computeStatus.class">
          <span class="status-tooltip">{{ computeStatus.tooltip }}</span>
        </div>
      </div>
    </div>

    <div class="topbar-right">
      <Button
        v-if="projectStore.currentProject"
        icon="pi pi-download"
        class="p-button-text p-button-rounded"
        aria-label="Export project"
        title="Export Project"
        @click="exportCurrentProject"
      />
      <Button
        v-if="showChatToggle !== false"
        icon="pi pi-comments"
        class="p-button-text p-button-rounded"
        aria-label="Toggle chat panel"
        :title="chatToggleTitle"
        @click="emit('toggle-chat')"
      />
      <Button
        icon="pi pi-bell"
        class="p-button-text p-button-rounded"
        aria-label="Notifications"
        title="Open notifications"
        :badge="
          notificationStore.unreadCount > 0 ? String(notificationStore.unreadCount) : undefined
        "
        badgeClass="p-badge-danger"
        @click="notificationDrawerVisible = !notificationDrawerVisible"
      />
      <!-- Admin shield: the /admin route is registered dynamically by
           the server-provided admin module when the user has
           capabilities.admin. Until that module registers the route,
           navigating to /admin is a no-op, so gating the button on the
           capability (rather than on the route existing) is correct. -->
      <Button
        v-if="authStore.user?.capabilities?.admin && appMode !== 'local'"
        icon="pi pi-shield"
        class="p-button-text p-button-rounded p-button-danger"
        aria-label="Admin Dashboard"
        title="Admin Dashboard"
        @click="router.push('/admin')"
      />
      <Button
        icon="pi pi-user"
        class="p-button-text p-button-rounded"
        aria-label="User menu"
        title="Open user menu"
        @click="toggleUserMenu"
      />
      <Menu ref="userMenu" :model="userMenuItems" :popup="true" />
    </div>

    <!-- Project Dialog -->
    <ProjectDialog
      v-model:visible="projectDialogVisible"
      :edit-project="editingProject"
      @create="onCreateProject"
      @update="onUpdateProject"
    />

    <!-- Hidden file input for import -->
    <input
      ref="fileInput"
      type="file"
      accept=".spectrapy,.json"
      style="display: none"
      @change="onFileSelected"
    />

    <!-- Project Details Drawer -->
    <ProjectDetailsDrawer v-model="projectDetailsVisible" />

    <!-- Notification Drawer -->
    <NotificationCenterDrawer v-model="notificationDrawerVisible" />
  </header>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import Button from "primevue/button";
import Dropdown from "primevue/dropdown";
import Menu from "primevue/menu";
import { useToast } from "primevue/usetoast";
import { useProjectStore } from "@/stores/project";
import { useNotificationStore } from "@/stores/notification";
import type { ProjectSummary } from "@/types";
import type { ProjectFormData } from "./ProjectDialog.vue";
import { useWorkflowStore } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import { useLlmStore } from "@/stores/llm";
import { useAuthStore } from "@/stores/auth";
import { useRouter } from "vue-router";
import { useBackendStatus } from "@/composables/useBackendStatus";
import { useTopbarMenu } from "@/composables/useTopbarMenu";
import { useAppConfig } from "@/composables/useAppConfig";
import { useNotifier } from "@/composables/useNotifier";
import ProjectDialog from "./ProjectDialog.vue";
import ProjectDetailsDrawer from "./ProjectDetailsDrawer.vue";
import NotificationCenterDrawer from "./NotificationCenterDrawer.vue";

const props = defineProps<{
  navCollapsed: boolean;
  chatCollapsed: boolean;
  showChatToggle?: boolean;
}>();

const emit = defineEmits<{
  (event: "toggle-nav"): void;
  (event: "toggle-chat"): void;
}>();

const toast = useToast();
const projectStore = useProjectStore();
const notificationStore = useNotificationStore();
const { notifySystemEvent } = useNotifier();
const workflowStore = useWorkflowStore();
const experimentStore = useExperimentStore();
const llmStore = useLlmStore();
const authStore = useAuthStore();
const router = useRouter();
const { backendConnected } = useBackendStatus();
const { appMode, hasLLMConfigured } = useAppConfig();
const fileInput = ref<HTMLInputElement | null>(null);
const notificationDrawerVisible = ref(false);

// User menu. Managed-auth items (My Profile, Change Password, Sign Out)
// are contributed at runtime by the server-provided auth module via
// `useTopbarMenu` when the server is present. OSS ships only the items
// that work without a server.
const userMenu = ref();
const { items: contributedMenuItems } = useTopbarMenu();

const userMenuItems = computed(() => [
  {
    label: authStore.user?.username || "User",
    icon: "pi pi-user",
    disabled: true,
    class: "user-menu-header",
  },
  { separator: true },
  {
    label: "Settings",
    icon: "pi pi-cog",
    command: () => {
      router.push("/settings");
    },
  },
  {
    label: "Documentation",
    icon: "pi pi-book",
    command: () => {
      window.open("https://docs.spectrascientific.ai", "_blank");
    },
  },
  // Server-module contributions (Sign Out / My Profile / Change Password
  // in managed-auth modes). Empty array in local mode.
  ...contributedMenuItems.value,
]);

const toggleUserMenu = (event: Event) => {
  userMenu.value.toggle(event);
};

const chatToggleTitle = computed(() =>
  props.chatCollapsed ? "Open chat panel" : "Collapse chat panel",
);

// Status indicator computed properties (Traffic Lights)
const backendStatus = computed(() => {
  if (backendConnected.value) {
    return { class: "status-green", tooltip: "Backend: Connected" };
  }
  return { class: "status-red status-pulse", tooltip: "Backend: Server offline" };
});

const dataStatus = computed(() => {
  const hasExperiments = experimentStore.experiments.length > 0;
  const hasNodeOutput = workflowStore.nodes.some((n) => n.executionState?.status === "completed");
  if (hasExperiments || hasNodeOutput) {
    return { class: "status-green", tooltip: "Data: Loaded" };
  }
  return { class: "status-gray", tooltip: "Data: No data loaded" };
});

const workflowStatus = computed(() => {
  if (workflowStore.nodes.length === 0) {
    return { class: "status-gray", tooltip: "Workflow: Empty canvas" };
  }
  if (workflowStore.hasUnsavedChanges) {
    return { class: "status-yellow", tooltip: "Workflow: Unsaved changes" };
  }
  return { class: "status-green", tooltip: "Workflow: Ready" };
});

const llmStatus = computed(() => {
  if (llmStore.connectionStatus === "connected") {
    return { class: "status-green", tooltip: "LLM: Connected" };
  }
  if (llmStore.connectionStatus === "connecting") {
    return { class: "status-yellow status-pulse", tooltip: "LLM: Connecting..." };
  }
  if (llmStore.configStatus === "configured" || hasLLMConfigured.value) {
    return { class: "status-blue", tooltip: "LLM: Ready" };
  }
  if (llmStore.configStatus === "unknown") {
    return { class: "status-yellow", tooltip: "LLM: Checking..." };
  }
  return { class: "status-red", tooltip: "LLM: Not Configured" };
});

onMounted(() => {
  // Only poll LLM config in local mode — server owns model selection in hybrid/enterprise
  if (appMode.value === "local") {
    llmStore.startConfigPolling();
  }
});

onUnmounted(() => {
  llmStore.stopConfigPolling();
});

const computeStatus = computed(() => {
  return { class: "status-blue", tooltip: "Compute: Local" };
});

// Project selection
const selectedProjectId = ref<number | null>(projectStore.currentProjectId);

// Sync with store
watch(
  () => projectStore.currentProjectId,
  (id) => {
    selectedProjectId.value = id;
  },
);

// System notifications: backend online/offline transitions
let backendInitialized = false;
watch(backendConnected, (connected) => {
  // Skip the initial health check result
  if (!backendInitialized) {
    backendInitialized = true;
    return;
  }
  if (connected) {
    notifySystemEvent({
      severity: "success",
      title: "Backend Online",
      message: "Connection restored",
    });
  } else {
    notifySystemEvent({
      severity: "error",
      title: "Backend Offline",
      message: "Lost connection to the server",
    });
  }
});

const getProjectName = (projectId: number): string => {
  const project = projectStore.projectList.find((p) => p.id === projectId);
  return project?.name || "Unknown Project";
};

const onProjectChange = async () => {
  if (selectedProjectId.value) {
    await projectStore.selectProject(selectedProjectId.value);
    const project = projectStore.currentProject;
    if (project) {
      toast.add({
        severity: "info",
        summary: "Project Loaded",
        detail: `Switched to "${project.name}"`,
        life: 2000,
      });
    }
  }
};

// Project dialog
const projectDialogVisible = ref(false);
const editingProject = ref<ProjectSummary | null>(null);

// Project details drawer
const projectDetailsVisible = ref(false);

const showProjectDetails = () => {
  projectDetailsVisible.value = true;
};

const showNewProjectDialog = () => {
  editingProject.value = null;
  projectDialogVisible.value = true;
};

const showEditProjectDialog = () => {
  if (projectStore.currentProject) {
    editingProject.value = projectStore.currentProject;
  }
  projectDialogVisible.value = true;
};

const onCreateProject = async (data: ProjectFormData) => {
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
};

const onUpdateProject = async (data: ProjectFormData) => {
  if (projectStore.currentProjectId) {
    const updated = await projectStore.updateProject(projectStore.currentProjectId, {
      name: data.name,
      description: data.description || null,
      technique: data.technique,
      sample_type: data.sample_type,
    });
    if (updated) {
      toast.add({
        severity: "success",
        summary: "Project Updated",
        detail: "Changes saved successfully",
        life: 2000,
      });
    }
  }
};

// Export/Import
const exportCurrentProject = async () => {
  if (projectStore.currentProjectId) {
    await projectStore.exportProject(projectStore.currentProjectId);
    toast.add({
      severity: "success",
      summary: "Project Exported",
      detail: "Project file downloaded",
      life: 2000,
    });
  }
};

const triggerImport = () => {
  fileInput.value?.click();
};

const onFileSelected = async (event: Event) => {
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

  // Clear the input
  input.value = "";
};
</script>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  height: 56px;
  gap: 16px;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.nav-collapse-toggle {
  align-items: center;
  background: transparent;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  color: #64748b;
  cursor: pointer;
  display: inline-flex;
  height: 26px;
  justify-content: center;
  padding: 0;
  transition: all 0.15s ease;
  width: 26px;
}

.nav-collapse-toggle:hover {
  background: #f8fafc;
  border-color: #94a3b8;
  color: #334155;
}

.nav-collapse-toggle i {
  font-size: 0.7rem;
}

.topbar-center {
  display: flex;
  align-items: center;
  gap: 16px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* Project Selector */
.project-selector {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
}

.project-icon {
  color: #64748b;
  font-size: 1rem;
}

.active-project-title {
  color: #0f172a;
  font-size: 0.95rem;
  font-weight: 700;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-dropdown {
  border: none;
  background: transparent;
  min-width: 150px;
}

.project-dropdown :deep(.p-dropdown-label) {
  padding: 4px 8px;
  font-weight: 500;
}

.project-dropdown :deep(.p-dropdown-trigger) {
  width: 2rem;
}

.project-value {
  font-weight: 500;
  color: #334155;
}

.project-placeholder {
  color: #94a3b8;
}

.project-option {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 0;
}

.project-option-name {
  font-weight: 500;
}

.project-option-date {
  font-size: 0.75rem;
  color: #94a3b8;
}

.project-dropdown-footer {
  display: flex;
  justify-content: space-between;
  padding: 8px;
  border-top: 1px solid #e2e8f0;
}

.project-info-btn {
  color: #3b82f6;
}

.project-info-btn:hover {
  background: rgba(59, 130, 246, 0.1) !important;
}

.project-settings-btn {
  margin-left: 2px;
}

/* Status Indicators (Traffic Lights) */
.status-indicators {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  background: #f1f5f9;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
}

.status-light {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  position: relative;
  cursor: pointer;
  transition:
    transform 0.2s,
    box-shadow 0.2s;
}

.status-light:hover {
  transform: scale(1.3);
}

.status-light:hover .status-tooltip {
  opacity: 1;
  visibility: visible;
  transform: translateX(-50%) translateY(0);
}

.status-tooltip {
  position: absolute;
  top: calc(100% + 10px);
  left: 50%;
  transform: translateX(-50%) translateY(-4px);
  background: #1e293b;
  color: #f8fafc;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.status-tooltip::before {
  content: "";
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-bottom-color: #1e293b;
}

/* Status colors */
.status-green {
  background: radial-gradient(circle at 30% 30%, #4ade80, #16a34a);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.5);
}

.status-yellow {
  background: radial-gradient(circle at 30% 30%, #facc15, #ca8a04);
  box-shadow: 0 0 6px rgba(250, 204, 21, 0.5);
}

.status-red {
  background: radial-gradient(circle at 30% 30%, #f87171, #dc2626);
  box-shadow: 0 0 6px rgba(248, 113, 113, 0.5);
}

.status-blue {
  background: radial-gradient(circle at 30% 30%, #60a5fa, #2563eb);
  box-shadow: 0 0 6px rgba(96, 165, 250, 0.5);
}

.status-gray {
  background: radial-gradient(circle at 30% 30%, #94a3b8, #64748b);
  box-shadow: 0 0 4px rgba(148, 163, 184, 0.3);
}

/* Pulse animation for active/connecting states */
.status-pulse {
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 6px currentColor;
  }
  50% {
    box-shadow:
      0 0 12px currentColor,
      0 0 18px currentColor;
  }
}

/*
 * At narrow widths the topbar drops the project selector first
 * (hamburger stays in topbar-left to open the nav drawer; status
 * lights and the right-side actions stay). If even that overflows,
 * the status indicators drop next.
 */
@media (max-width: 768px) {
  .topbar {
    padding: 8px 12px;
    gap: 8px;
  }

  .project-selector {
    display: none;
  }
}

@media (max-width: 480px) {
  .topbar-center {
    display: none;
  }
}
</style>
