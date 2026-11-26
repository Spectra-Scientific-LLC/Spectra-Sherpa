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
          aria-label="Select Project"
          class="project-dropdown"
          @change="onProjectChange"
        >
          <template #value="slotProps">
            <span v-if="slotProps.value" class="project-value" :title="getProjectName(slotProps.value)">
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
      <details class="connection-status">
        <summary>{{ connectionLabel }}</summary>
        <div class="connection-details">
      <!-- Each status is a line of text with its colour dot, not a bare dot with a hover tooltip. -->
      <ul class="status-list" aria-label="Current project availability">
        <li v-for="record in provenanceLights" :key="record.kind">
          <button type="button" class="status-row" @click="router.push('/project/provenance')">
            <span class="status-dot" :class="`status-${availabilityState(record) === 'healthy' ? 'green' : availabilityState(record) === 'faulty' ? 'red' : 'gray'}`" aria-hidden="true" />
            {{ provenanceTooltip(record) }}
          </button>
        </li>
      </ul>
      <ul class="status-list" aria-label="System readiness">
        <li v-for="item in [backendStatus, llmStatus, computeStatus]" :key="item.tooltip" class="status-row">
          <span class="status-dot" :class="item.class" aria-hidden="true" />
          {{ item.tooltip }}
        </li>
      </ul>
        </div>
      </details>
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
import { availabilityDetail, availabilityState, useProjectProvenanceStore, type ProjectProvenanceRecord } from "@/stores/projectProvenance";
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
const provenanceStore = useProjectProvenanceStore();
const llmStore = useLlmStore();
const authStore = useAuthStore();
const router = useRouter();
const { backendConnected } = useBackendStatus();
const { appMode, siteProfile, hasLLMConfigured, aiPlacement, reloadConfig } = useAppConfig();
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

const connectionLabel = computed(() => `${appMode.value === "local" ? "Local" : siteProfile.value === "demo" ? "Hosted demo" : "Hosted"} · ${backendConnected.value ? "connected" : "server unavailable"}`);
// Readiness details stay available behind the labeled status chip.
const backendStatus = computed(() => {
  if (backendConnected.value) {
    return { class: "status-green", tooltip: "Backend: Connected" };
  }
  return { class: "status-red status-pulse", tooltip: "Backend: Server offline" };
});

const provenanceKinds = ["source", "dataset", "workflow", "run", "environment", "model", "campaign", "package"] as const;
const provenanceLabels = ["Source", "Dataset", "Workflow", "Run", "Environment", "Model", "Campaign", "Package"];
const activeProvenance = computed(() => provenanceStore.projectId === projectStore.currentProjectId ? provenanceStore.summary : null);
const provenanceLights = computed<ProjectProvenanceRecord[]>(() => provenanceKinds.map((kind, index) =>
  activeProvenance.value?.records.find((record) => record.kind === kind) ?? {
    kind, label: provenanceLabels[index], state: provenanceStore.error ? "faulty" : "missing",
    name: null, digest: null, record_id: null,
    detail: provenanceStore.error ?? "No active evidence in this project.",
    destination: "/project/provenance",
  },
));
const provenanceTooltip = (record: ProjectProvenanceRecord): string =>
  `${record.label}: ${availabilityDetail(record)}${activeProvenance.value?.verified_at ? ` • checked ${new Date(activeProvenance.value.verified_at).toLocaleTimeString()}` : ""}`;

// One light for the AI: where it runs (Local, Hosted or Off) and its connection state.
const aiWhere = computed(() =>
  aiPlacement.value === "local"
    ? "AI: Local. The AI runs on this computer."
    : "AI: Hosted. Data you share with the AI is sent to its provider.",
);
const llmStatus = computed(() => {
  if (llmStore.connectionStatus === "connected") {
    return { class: "status-green", tooltip: `${aiWhere.value} Connected.` };
  }
  if (llmStore.connectionStatus === "connecting") {
    return { class: "status-yellow status-pulse", tooltip: `${aiWhere.value} Connecting...` };
  }
  if (llmStore.configStatus === "configured" || hasLLMConfigured.value) {
    return { class: "status-blue", tooltip: `${aiWhere.value} Ready.` };
  }
  if (llmStore.configStatus === "unknown") {
    return { class: "status-yellow", tooltip: "AI: Checking..." };
  }
  // AI is optional. Reserve red for failures in required services.
  return { class: "status-gray", tooltip: "AI: Off. No AI provider is configured (optional)." };
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

const refreshProjectEvidence = () => {
  if (projectStore.currentProjectId != null) void provenanceStore.refresh(projectStore.currentProjectId, false);
};

onMounted(() => {
  syncLocalLlmPolling();
  // Deep links must populate the selector even when Dashboard/Project was never opened.
  if (authStore.user || appMode.value === "local") void projectStore.fetchProjects();
  window.addEventListener("llm-config-changed", handleLlmConfigChange);
  window.addEventListener("focus", refreshProjectEvidence);
});

onUnmounted(() => {
  llmStore.stopConfigPolling();
  window.removeEventListener("llm-config-changed", handleLlmConfigChange);
  window.removeEventListener("focus", refreshProjectEvidence);
});

watch(appMode, syncLocalLlmPolling);
watch(() => projectStore.currentProjectId, (id) => { void provenanceStore.refresh(id); }, { immediate: true });
watch(() => router.currentRoute.value.fullPath, refreshProjectEvidence);

const computeStatus = computed(() => {
  if (appMode.value === "enterprise" && siteProfile.value === "demo") {
    return { class: "status-blue", tooltip: "Compute: Hosted" };
  }
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
  return project?.name ||
    (projectStore.currentProject?.id === projectId ? projectStore.currentProject.name : "Unknown Project");
};

const onProjectChange = async () => {
  if (selectedProjectId.value) {
    const previousProjectId = projectStore.currentProjectId;
    if (selectedProjectId.value === previousProjectId) return;
    if (workflowStore.hasUnsavedChanges && workflowStore.workflowId !== null) {
      try {
        await workflowStore.saveWorkflow({ createVersion: false });
      } catch {
        selectedProjectId.value = previousProjectId;
        toast.add({
          severity: "error",
          summary: "Project Switch Stopped",
          detail: "The active workflow could not be saved. Your project was not changed.",
          life: 5000,
        });
        return;
      }
    }
    // The project selector already shows the new project; no toast repeats it.
    await projectStore.selectProject(selectedProjectId.value);
  }
};
</script>

<style scoped>
.connection-status { position: relative; font-size: .8rem; }
.connection-status > summary { cursor: pointer; border: 1px solid var(--surface-border); border-radius: 1rem; padding: .3rem .65rem; list-style: none; }
.connection-status > summary::after { content: " ▾"; }
.connection-details { position: absolute; right: 0; top: calc(100% + .4rem); z-index: 1000; padding: 1rem; display: grid; gap: .75rem; background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: .5rem; }

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: var(--ss-workspace-paper);
  border-bottom: 1px solid var(--ss-border);
  height: 56px;
  gap: 16px;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}

.nav-collapse-toggle {
  flex-shrink: 0;
  align-items: center;
  background: transparent;
  border: 1px solid var(--ss-border-strong);
  border-radius: 4px;
  color: var(--ss-text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 26px;
  justify-content: center;
  padding: 0;
  transition: all 0.15s ease;
  width: 26px;
}

.nav-collapse-toggle:hover {
  background: var(--ss-surface-subtle);
  border-color: var(--ss-border-strong);
  color: var(--ss-action-text);
}

.nav-collapse-toggle i {
  font-size: 0.7rem;
}

.topbar-center {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 16px;
}

.provenance-indicators {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  background: var(--ss-info-surface);
  border: 1px solid var(--ss-info-surface);
  border-radius: 20px;
}

.provenance-indicators .status-light {
  border: 0;
  padding: 0;
  flex: 0 0 14px;
}

.topbar-right {
  flex-shrink: 0;
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
  background: var(--ss-surface-subtle);
  border-radius: 8px;
  border: 1px solid var(--ss-border);
  min-width: 0;
  max-width: 100%;
}

.project-icon {
  color: var(--ss-text-muted);
  font-size: 1rem;
}

.project-dropdown {
  border: none;
  background: transparent;
  min-width: 0;
  max-width: 100%;
}

.project-dropdown :deep(.p-dropdown-label) {
  padding: 4px 8px;
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-dropdown :deep(.p-dropdown-trigger) {
  width: 2rem;
}

.project-value {
  font-weight: 500;
  color: var(--ss-action-text);
}

.project-placeholder {
  color: var(--ss-text-muted);
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
  color: var(--ss-text-muted);
}

/* Status Indicators (Traffic Lights) */
.status-indicators {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  background: var(--ss-surface-subtle);
  border-radius: 20px;
  border: 1px solid var(--ss-border);
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
  outline: 2px solid var(--ss-action);
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
  background: var(--ss-panel);
  color: var(--ss-panel-text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.8rem;
  white-space: nowrap;
  opacity: 0;
  visibility: hidden;
  transition: all 0.2s ease;
  z-index: 1000;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--ss-shadow-color) 20%, transparent);
}

.status-tooltip::before {
  content: "";
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-bottom-color: var(--ss-panel);
}

/* Status colors — flat mid-tone fills; the pulse animation still glows
   on transitional states (connecting, offline). */
.status-green {
  background: var(--ss-success);
}

.status-indicators .status-light:nth-child(1).status-green,
.status-indicators .status-light:nth-child(2).status-green {
  background: var(--ss-success);
}

.status-yellow {
  background: var(--ss-warning);
}

.status-red {
  background: var(--ss-danger);
}

.status-blue {
  background: var(--ss-action);
}

.status-gray {
  background: var(--ss-border-strong);
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

/* Keep project identity and switching available at narrow widths. */
@media (max-width: 768px) {
  .topbar {
    padding: 8px 12px;
    gap: 8px;
  }

  .topbar-left {
    gap: 6px;
  }

  .project-selector {
    padding: 2px;
  }

  .project-icon {
    display: none;
  }

  .project-dropdown :deep(.p-dropdown-label) {
    padding-inline: 4px;
  }
}

@media (max-width: 540px) {
  .topbar {
    display: grid;
    height: auto;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 4px 8px;
  }

  .topbar-left {
    display: contents;
  }

  .nav-collapse-toggle {
    grid-area: 1 / 1;
  }

  .topbar-right {
    grid-area: 1 / 2;
  }

  .project-selector {
    grid-row: 2;
    grid-column: 1 / -1;
  }

  .project-dropdown {
    width: 100%;
  }

  .topbar-center {
    display: none;
  }
}
.status-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .35rem; min-width: 22rem; }
.status-row { display: flex; align-items: baseline; gap: .5rem; padding: 0; border: 0; background: none; color: var(--text-color); font: inherit; font-size: .85rem; text-align: left; cursor: default; }
button.status-row { cursor: pointer; }
button.status-row:hover { text-decoration: underline; }
.status-dot { flex: 0 0 .6rem; height: .6rem; border-radius: 50%; }
</style>
