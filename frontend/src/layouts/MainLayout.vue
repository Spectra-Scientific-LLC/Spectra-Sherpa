<template>
  <div class="app-shell" :style="layoutStyle">
    <Toast position="top-right" />
    <SherpaUpgradeModal />
    <DemoUpgradeModal />

    <!-- Backend Status Banner -->
    <div v-if="!backendConnected" class="backend-status-banner">
      <i class="pi pi-exclamation-triangle"></i>
      <span>Unable to reach the backend server. Please check your connection.</span>
      <button @click="checkBackendStatus" class="retry-btn" :disabled="checkingStatus">
        <i class="pi pi-refresh" :class="{ 'pi-spin': checkingStatus }"></i>
        {{ checkingStatus ? 'Checking...' : 'Retry' }}
      </button>
    </div>

    <!-- Offline Mode Badge (local mode only) -->
    <div v-if="appMode === 'local' && backendConnected" class="offline-mode-badge">
      <i class="pi pi-wifi-off"></i>
      <span>Offline Mode</span>
    </div>

    <Sidebar :collapsed="navCollapsed" />
    <div class="workspace">
      <div class="main">
        <Topbar
          :nav-collapsed="navCollapsed"
          :chat-collapsed="chatCollapsed"
          @toggle-nav="toggleNav"
          @toggle-chat="toggleChat"
        />
        <main class="content">
          <router-view />
        </main>
      </div>
      <div
        v-show="!chatCollapsed"
        class="chat-resize-handle"
        :class="{ active: isResizing }"
        @mousedown="startResize"
      ></div>
      <ChatPanel
        :compact="true"
        :collapsed="chatCollapsed"
        @toggle="toggleChat"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import ChatPanel from "@/components/ChatPanel.vue";
import SherpaUpgradeModal from "@/components/SherpaUpgradeModal.vue";
import DemoUpgradeModal from "@/components/DemoUpgradeModal.vue";

import Sidebar from "@/components/Sidebar.vue";
import Topbar from "@/components/Topbar.vue";
import Toast from "primevue/toast";
import { useBackendStatus } from "@/composables/useBackendStatus";
import { useAppConfig } from "@/composables/useAppConfig";
import { useAuthStore } from "@/stores/auth";
import { useJobStore } from "@/stores/job";

const { appMode } = useAppConfig();
const authStore = useAuthStore();
const jobStore = useJobStore();

const navCollapsed = ref(localStorage.getItem("navCollapsed") === "true");
const chatCollapsed = ref(localStorage.getItem("chatCollapsed") !== "false");
const chatWidth = ref(360);
const isResizing = ref(false);

// Backend connection status
const { backendConnected, checkingStatus, checkBackendStatus, startHealthCheck, stopHealthCheck } = useBackendStatus();

const clampChatWidth = (value: number) => {
  const minWidth = 280;
  const maxWidth = Math.max(320, Math.round(window.innerWidth * 0.45));
  return Math.min(Math.max(value, minWidth), maxWidth);
};

const layoutStyle = computed(() => ({
  "--nav-width": navCollapsed.value ? "72px" : "240px",
  "--chat-width": chatCollapsed.value ? "0px" : `${chatWidth.value}px`,
}));

const toggleNav = () => {
  navCollapsed.value = !navCollapsed.value;
  localStorage.setItem("navCollapsed", String(navCollapsed.value));
};

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

onMounted(() => {
  const storedWidth = Number(localStorage.getItem("chatWidth"));
  const initialWidth = Number.isFinite(storedWidth) && storedWidth > 0
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
  jobStore.disconnect();
});

watch(chatWidth, (value) => {
  localStorage.setItem("chatWidth", String(value));
});

// Connect the job store WS when the backend becomes available so that
// background job progress (batch predict, folder watches) reaches the UI.
// Use authStore.user (not isAuthenticated) to avoid connecting with a stale
// localStorage token before /auth/me validates it.
watch(
  [backendConnected, () => authStore.user],
  ([isConnected, user]) => {
    if (isConnected && (user || appMode.value === "local")) {
      jobStore.connect().catch(() => undefined);
    } else {
      jobStore.disconnect();
    }
  }
);
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
  0%, 100% {
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

.backend-status-banner code {
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
  font-family: 'Monaco', 'Courier New', monospace;
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
.app-shell:has(.backend-status-banner) {
  padding-top: 48px;
}

/* Offline mode badge */
.offline-mode-badge {
  position: fixed;
  top: 8px;
  right: 16px;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: var(--surface-200, #e5e7eb);
  color: var(--text-color-secondary, #6b7280);
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  opacity: 0.8;
  pointer-events: none;
}

.offline-mode-badge i {
  font-size: 11px;
}
</style>
