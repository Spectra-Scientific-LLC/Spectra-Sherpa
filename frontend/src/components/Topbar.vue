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
        </Dropdown>
      </div>
    </div>

    <div class="topbar-center">
      <!-- Status Indicators (Traffic Lights) -->
      <div class="status-indicators">
        <div
          class="status-light"
          :class="backendStatus.class"
          role="img"
          tabindex="0"
          :aria-label="backendStatus.tooltip"
          :title="backendStatus.tooltip"
        >
          <span class="status-tooltip">{{ backendStatus.tooltip }}</span>
        </div>
        <div
          class="status-light"
          :class="dataStatus.class"
          role="img"
          tabindex="0"
          :aria-label="dataStatus.tooltip"
          :title="dataStatus.tooltip"
        >
          <span class="status-tooltip">{{ dataStatus.tooltip }}</span>
        </div>
        <div
          class="status-light"
          :class="workflowStatus.class"
          role="img"
          tabindex="0"
          :aria-label="workflowStatus.tooltip"
          :title="workflowStatus.tooltip"
        >
          <span class="status-tooltip">{{ workflowStatus.tooltip }}</span>
        </div>
        <div
          class="status-light"
          :class="llmStatus.class"
          role="img"
          tabindex="0"
          :aria-label="llmStatus.tooltip"
          :title="llmStatus.tooltip"
        >
          <span class="status-tooltip">{{ llmStatus.tooltip }}</span>
        </div>
        <div
          class="status-light"
          :class="computeStatus.class"
          role="img"
          tabindex="0"
          :aria-label="computeStatus.tooltip"
          :title="computeStatus.tooltip"
        >
          <span class="status-tooltip">{{ computeStatus.tooltip }}</span>
        </div>
      </div>
    </div>

    <div class="topbar-right">
      <Button
        v-if="showChatToggle !== false"
        icon="pi pi-comments"
        class="p-button-text topbar-bare-icon"
        aria-label="Toggle chat panel"
        :title="chatToggleTitle"
        @click="emit('toggle-chat')"
      />
      <Button
        icon="pi pi-bell"
        class="p-button-text topbar-bare-icon"
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
        class="p-button-text topbar-bare-icon"
        aria-label="User menu"
        title="Open user menu"
        @click="toggleUserMenu"
      />
      <Menu ref="userMenu" :model="userMenuItems" :popup="true" />
      <AboutDialog v-model:visible="aboutVisible" />
    </div>

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
import { useWorkflowStore } from "@/stores/workflow";
import { useExperimentStore } from "@/stores/experiment";
import { useLlmStore } from "@/stores/llm";
import { useAuthStore } from "@/stores/auth";
import { useRouter } from "vue-router";
import { useBackendStatus } from "@/composables/useBackendStatus";
import { useTopbarMenu } from "@/composables/useTopbarMenu";
import { useAppConfig } from "@/composables/useAppConfig";
import { useNotifier } from "@/composables/useNotifier";
import NotificationCenterDrawer from "./NotificationCenterDrawer.vue";
import AboutDialog from "./AboutDialog.vue";

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
const { appMode, hasLLMConfigured, reloadConfig } = useAppConfig();
const notificationDrawerVisible = ref(false);
const aboutVisible = ref(false);

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
  {
    label: "About SpectraSherpa",
    icon: "pi pi-info-circle",
    command: () => {
      aboutVisible.value = true;
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

// Refresh status immediately when the BYO-chat config is saved, instead of
// waiting up to 60s for the next poll tick. The settings panel dispatches
// "llm-config-changed" after a successful save (and after a successful
// test-then-save in the same handler).
const handleLlmConfigChange = async () => {
  await reloadConfig();
  await llmStore.checkConfigChange();
};

const syncLocalLlmPolling = () => {
  if (appMode.value === "local") {
    llmStore.startConfigPolling();
  } else {
    llmStore.stopConfigPolling();
  }
};

onMounted(() => {
  syncLocalLlmPolling();
  window.addEventListener("llm-config-changed", handleLlmConfigChange);
});

onUnmounted(() => {
  llmStore.stopConfigPolling();
  window.removeEventListener("llm-config-changed", handleLlmConfigChange);
});

watch(appMode, syncLocalLlmPolling);

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

/* Truly bare icon buttons: no background, no border, no hover shape — just
 * the icon. PrimeVue's `p-button-text` keeps a hover/focus background that
 * reads as a rectangular shape; override to keep them flat at all states. */
:deep(.topbar-bare-icon.p-button),
:deep(.topbar-bare-icon.p-button:hover),
:deep(.topbar-bare-icon.p-button:focus),
:deep(.topbar-bare-icon.p-button:enabled:hover),
:deep(.topbar-bare-icon.p-button:enabled:focus),
:deep(.topbar-bare-icon.p-button:enabled:active) {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
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

.status-light:hover,
.status-light:focus-visible {
  transform: scale(1.3);
}

.status-light:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 3px;
}

.status-light:hover .status-tooltip,
.status-light:focus-visible .status-tooltip {
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

/* Status colors — flat mid-tone fills; the pulse animation still glows
   on transitional states (connecting, offline). */
.status-green {
  background: #16a34a;
}

.status-yellow {
  background: #ca8a04;
}

.status-red {
  background: #dc2626;
}

.status-blue {
  background: #2563eb;
}

.status-gray {
  background: #94a3b8;
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
