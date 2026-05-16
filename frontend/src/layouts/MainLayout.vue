<template>
  <!--
    Public routes (login, register) and standalone tools render
    full-bleed without the OSS shell — sidebar + topbar + chat
    panel are workspace affordances aimed at authenticated users,
    and visually compete with centered auth Cards and focused detail
    views. Toast and upgrade modals are still mounted so error /
    upgrade flows work on these pages.
  -->
  <div v-if="isShelllessRoute" class="public-shell">
    <Toast position="top-right" />
    <SherpaUpgradeModal />
    <DemoUpgradeModal />
    <GuidanceToast />
    <GuidanceGlowOverlay />
    <router-view />
  </div>

  <div v-else class="app-shell" :class="{ 'chat-open': !chatCollapsed }" :style="layoutStyle">
    <Toast position="top-right" />
    <SherpaUpgradeModal />
    <DemoUpgradeModal />
    <GuidanceToast />
    <GuidanceGlowOverlay />

    <!-- Backend Status Banner -->
    <div v-if="!backendConnected" class="backend-status-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <span>Unable to reach the backend server. Please check your connection.</span>
      <button @click="checkBackendStatus" class="retry-btn" :disabled="checkingStatus">
        <i class="pi pi-refresh" :class="{ 'pi-spin': checkingStatus }"></i>
        {{ checkingStatus ? "Checking..." : "Retry" }}
      </button>
    </div>

    <div v-else-if="backendDegraded" class="backend-warning-banner">
      <i class="pi pi-exclamation-circle"></i>
      <span>
        Some plugins failed to load{{ pluginFailureCount ? ` (${pluginFailureCount})` : "" }}.
        Workflow nodes from those plugins may be unavailable until the backend is fixed.
      </span>
    </div>

    <Sidebar :collapsed="effectiveNavCollapsed" />
    <div class="workspace">
      <div class="main">
        <Topbar
          :nav-collapsed="effectiveNavCollapsed"
          :chat-collapsed="chatCollapsed"
          :show-chat-toggle="true"
          @toggle-nav="toggleNav"
          @toggle-chat="toggleChat"
        />
        <main class="content">
          <router-view />
        </main>
        <AppFooter />
      </div>
      <div
        v-show="!chatCollapsed && !isNarrow"
        class="chat-resize-handle"
        :class="{ active: isResizing }"
        @mousedown="startResize"
      ></div>
      <ChatPanel
        v-show="!isNarrow || !chatCollapsed"
        :compact="true"
        :collapsed="chatCollapsed"
        @toggle="toggleChat"
      />
    </div>

    <!-- Narrow-mode expanded nav drawer. Tapping a link or scrim closes it. -->
    <PrimeSidebar
      v-if="isNarrow"
      v-model:visible="navDrawerOpen"
      position="left"
      :style="{ width: '224px' }"
      class="nav-drawer"
    >
      <Sidebar :collapsed="false" @click="navDrawerOpen = false" />
    </PrimeSidebar>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import ChatPanel from "@/components/ChatPanel.vue";
import GuidanceGlowOverlay from "@/components/guidance/GuidanceGlowOverlay.vue";
import GuidanceToast from "@/components/guidance/GuidanceToast.vue";
import SherpaUpgradeModal from "@/components/SherpaUpgradeModal.vue";
import DemoUpgradeModal from "@/components/DemoUpgradeModal.vue";

import Sidebar from "@/components/Sidebar.vue";
import Topbar from "@/components/Topbar.vue";
import AppFooter from "@/components/AppFooter.vue";
import Toast from "primevue/toast";
import PrimeSidebar from "primevue/sidebar";
import { useBackendStatus } from "@/composables/useBackendStatus";
import { useActivityTracker } from "@/composables/useActivityTracker";
import { useAppConfig } from "@/composables/useAppConfig";
import { useGuidance } from "@/composables/useGuidance";
import { useViewport } from "@/composables/useViewport";
import { useAuthStore } from "@/stores/auth";
import { useJobStore } from "@/stores/job";

const { appMode, appConfig } = useAppConfig();
const guidance = useGuidance();
const activityTracker = useActivityTracker();
const authStore = useAuthStore();
const jobStore = useJobStore();
const route = useRoute();

const readBooleanPreference = (key: string, defaultValue: boolean): boolean => {
  const rawValue = localStorage.getItem(key);
  if (rawValue === null) {
    return defaultValue;
  }
  return rawValue === "true";
};

const navCollapsed = ref(localStorage.getItem("navCollapsed") === "true");
const chatCollapsed = ref(readBooleanPreference("chatCollapsed", true));
const chatWidth = ref(360);
const isResizing = ref(false);
const layoutMounted = ref(false);
const guidanceRuntimeStarted = ref(false);
const guidanceRuntimeStarting = ref(false);
const isPublicRoute = computed(() => Boolean(route.meta.public));
const isStandaloneRoute = computed(() => Boolean(route.meta.standalone));
const isShelllessRoute = computed(() => isPublicRoute.value || isStandaloneRoute.value);

// Narrow viewport (smartphone / portrait). At this width the sidebar
// always renders as the icon rail and main vs. chat are mutually
// exclusive — chat takes over the workspace when toggled open.
const { isNarrow } = useViewport();
const navDrawerOpen = ref(false);
const effectiveNavCollapsed = computed(() => isNarrow.value || navCollapsed.value);

// Backend connection status
const {
  backendConnected,
  backendDegraded,
  checkingStatus,
  pluginFailureCount,
  checkBackendStatus,
  startHealthCheck,
  stopHealthCheck,
} = useBackendStatus();

const clampChatWidth = (value: number) => {
  const minWidth = 280;
  const maxWidth = Math.max(320, Math.round(window.innerWidth * 0.45));
  return Math.min(Math.max(value, minWidth), maxWidth);
};

const layoutStyle = computed(() => ({
  "--nav-width": effectiveNavCollapsed.value ? "72px" : "224px",
  "--chat-width": chatCollapsed.value ? "0px" : `${chatWidth.value}px`,
}));

const toggleNav = () => {
  if (isNarrow.value) {
    navDrawerOpen.value = !navDrawerOpen.value;
    return;
  }
  navCollapsed.value = !navCollapsed.value;
  localStorage.setItem("navCollapsed", String(navCollapsed.value));
};

watch(
  () => route.fullPath,
  () => {
    if (navDrawerOpen.value) navDrawerOpen.value = false;
  },
);

watch(isNarrow, (narrow) => {
  if (!narrow && navDrawerOpen.value) navDrawerOpen.value = false;
});

const toggleChat = () => {
  chatCollapsed.value = !chatCollapsed.value;
  localStorage.setItem("chatCollapsed", String(chatCollapsed.value));
};

const startResize = (event: MouseEvent) => {
  if (chatCollapsed.value) {
    return;
  }
  event.preventDefault();
  isResizing.value = true;
  document.body.classList.add("chat-resizing");
};

const onResizeMove = (event: MouseEvent) => {
  if (!isResizing.value) {
    return;
  }
  const nextWidth = clampChatWidth(window.innerWidth - event.clientX);
  chatWidth.value = nextWidth;
};

const stopResize = () => {
  if (!isResizing.value) {
    return;
  }
  isResizing.value = false;
  document.body.classList.remove("chat-resizing");
};

const handleWindowResize = () => {
  if (chatCollapsed.value) {
    return;
  }
  chatWidth.value = clampChatWidth(chatWidth.value);
};

const isGuidanceRuntimeReady = (): boolean =>
  layoutMounted.value &&
  appMode.value !== "local" &&
  backendConnected.value &&
  !!authStore.user &&
  !!appConfig.value?.features?.sherpaGuidance;

const stopGuidanceRuntime = () => {
  // Also tear down a startup that is still in flight — guidance.start()
  // can be mid-retry/backoff; guidance.stop() cancels it (review
  // finding: previously only a fully-started runtime was stopped, so a
  // logout during startup left the retry loop running).
  if (!guidanceRuntimeStarted.value && !guidanceRuntimeStarting.value) {
    return;
  }
  guidance.stop();
  activityTracker.stop();
  guidanceRuntimeStarted.value = false;
};

const maybeStartGuidanceRuntime = async () => {
  if (guidanceRuntimeStarted.value || guidanceRuntimeStarting.value) {
    return;
  }
  if (!isGuidanceRuntimeReady()) {
    return;
  }
  guidanceRuntimeStarting.value = true;
  let restartAfterCancelledStart = false;
  try {
    const guidanceStarted = await guidance.start();
    if (!guidanceStarted) {
      guidance.stop();
      restartAfterCancelledStart = isGuidanceRuntimeReady();
      return;
    }
    // The settings fetch can retry across a backoff window that spans a
    // logout / backend drop, and stopGuidanceRuntime() may have
    // cancelled this very startup.  Re-check readiness before attaching
    // the activity tracker so we never bind it to a torn-down session
    // (review finding).
    if (!isGuidanceRuntimeReady()) {
      guidance.stop();
      return;
    }
    activityTracker.start();
    guidanceRuntimeStarted.value = true;
  } catch (error) {
    guidanceRuntimeStarted.value = false;
    console.warn("[guidance] startup failed", error);
  } finally {
    guidanceRuntimeStarting.value = false;
    if (restartAfterCancelledStart) {
      void maybeStartGuidanceRuntime();
    }
  }
};

watch(
  [
    layoutMounted,
    backendConnected,
    () => authStore.user,
    () => appConfig.value?.features?.sherpaGuidance,
    appMode,
  ],
  () => {
    if (!isGuidanceRuntimeReady()) {
      stopGuidanceRuntime();
      return;
    }
    void maybeStartGuidanceRuntime();
  },
  { immediate: true },
);

onMounted(() => {
  layoutMounted.value = true;
  if (localStorage.getItem("chatCollapsed") === null) {
    localStorage.setItem("chatCollapsed", "true");
  }
  const storedWidth = Number(localStorage.getItem("chatWidth"));
  const initialWidth =
    Number.isFinite(storedWidth) && storedWidth > 0
      ? storedWidth
      : Math.round(window.innerWidth * 0.3);
  chatWidth.value = clampChatWidth(initialWidth);
  window.addEventListener("mousemove", onResizeMove);
  window.addEventListener("mouseup", stopResize);
  window.addEventListener("resize", handleWindowResize);

  // Start backend health check
  startHealthCheck();
});

onBeforeUnmount(() => {
  window.removeEventListener("mousemove", onResizeMove);
  window.removeEventListener("mouseup", stopResize);
  window.removeEventListener("resize", handleWindowResize);
  stopHealthCheck();
  stopGuidanceRuntime();
  jobStore.disconnect();
});

watch(chatWidth, (value) => {
  localStorage.setItem("chatWidth", String(value));
});

// Connect the job store WS when the backend becomes available so that
// background job progress (batch predict, folder watches) reaches the UI.
// Use authStore.user (not isAuthenticated) to avoid connecting with a stale
// localStorage token before /auth/me validates it.
watch([backendConnected, () => authStore.user], ([isConnected, user]) => {
  if (isConnected && (user || appMode.value === "local")) {
    jobStore.connect().catch(() => undefined);
  } else {
    jobStore.disconnect();
  }
});
</script>

<style scoped>
.backend-status-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10000;
  background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
  color: white;
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: slideDown 0.3s ease-out;
}

.backend-warning-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 10000;
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
  padding: 12px 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  animation: slideDown 0.3s ease-out;
}

@keyframes slideDown {
  from {
    transform: translateY(-100%);
  }
  to {
    transform: translateY(0);
  }
}

.backend-status-banner i.pi {
  font-size: 1.2rem;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.6;
  }
}

.backend-status-banner span {
  font-size: 14px;
  font-weight: 500;
}

.backend-warning-banner span {
  font-size: 14px;
  font-weight: 500;
}

.backend-status-banner code {
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: "Monaco", "Courier New", monospace;
  font-size: 13px;
}

.backend-status-banner .retry-btn {
  background: rgba(255, 255, 255, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: white;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.backend-status-banner .retry-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.3);
  border-color: rgba(255, 255, 255, 0.5);
}

.backend-status-banner .retry-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.backend-status-banner .retry-btn i.pi-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

/* Adjust app layout when banners are shown */
.app-shell:has(.backend-status-banner),
.app-shell:has(.backend-warning-banner) {
  padding-top: 48px;
}
</style>
