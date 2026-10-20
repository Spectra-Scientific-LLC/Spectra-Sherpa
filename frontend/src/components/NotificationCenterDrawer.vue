<template>
  <Sidebar
    v-model:visible="visible"
    position="right"
    :style="{ width: '400px' }"
    class="notification-drawer"
  >
    <template #header>
      <div class="drawer-header">
        <i class="pi pi-bell header-icon"></i>
        <span class="header-title">Notifications</span>
        <span v-if="store.unreadCount > 0" class="unread-badge">
          {{ store.unreadCount }}
        </span>
      </div>
    </template>

    <!-- Tab bar -->
    <div class="notif-tabs">
      <button
        class="notif-tab"
        :class="{ active: activeTab === 'all' }"
        @click="activeTab = 'all'"
      >
        All ({{ store.notifications.length }})
      </button>
      <button
        class="notif-tab"
        :class="{ active: activeTab === 'action' }"
        @click="activeTab = 'action'"
      >
        Action Required ({{ store.actionRequired.length }})
      </button>
      <button
        v-if="guidanceEnabled"
        class="notif-tab guidance-tab"
        :class="{ active: activeTab === 'guidance' }"
        @click="activeTab = 'guidance'"
      >
        Guidance ({{ guidance.notifications.length }})
      </button>
    </div>

    <!-- Action bar -->
    <div v-if="activeTab !== 'guidance' && displayedNotifications.length > 0" class="notif-actions">
      <Button
        label="Mark all read"
        icon="pi pi-check"
        class="p-button-text p-button-sm"
        @click="store.markAllRead()"
      />
      <Button
        label="Clear all"
        icon="pi pi-trash"
        class="p-button-text p-button-sm"
        @click="store.clearAll()"
      />
    </div>
    <div v-else-if="activeTab === 'guidance'" class="notif-actions">
      <Button
        label="Refresh"
        icon="pi pi-refresh"
        class="p-button-text p-button-sm"
        :loading="guidance.loading"
        @click="refreshGuidance"
      />
    </div>

    <!-- Notification list -->
    <div v-if="activeTab !== 'guidance' && displayedNotifications.length > 0" class="notif-list">
      <div
        v-for="n in displayedNotifications"
        :key="n.id"
        class="notif-item"
        :class="{ unread: !n.readAt }"
        @click="onNotificationClick(n)"
      >
        <div class="notif-icon" :class="`severity-${n.severity}`">
          <i :class="severityIcon(n.severity)"></i>
        </div>
        <div class="notif-body">
          <div class="notif-title-row">
            <span class="notif-title">{{ n.title }}</span>
            <span v-if="!n.readAt" class="notif-unread-dot"></span>
            <div class="notif-row-actions">
              <button
                class="notif-icon-btn"
                :title="copiedId === n.id ? 'Copied' : 'Copy notification'"
                type="button"
                @click.stop="copyNotification(n)"
              >
                <i :class="copiedId === n.id ? 'pi pi-check' : 'pi pi-copy'"></i>
              </button>
              <button
                v-if="n.detail"
                class="notif-icon-btn"
                title="Show details"
                type="button"
                @click.stop="toggleExpand(n)"
              >
                <i
                  :class="
                    expandedId === n.id
                      ? 'pi pi-chevron-up'
                      : 'pi pi-chevron-down'
                  "
                ></i>
              </button>
            </div>
          </div>
          <div class="notif-message">{{ n.message }}</div>
          <div v-if="n.detail && expandedId === n.id" class="notif-detail">
            <pre class="notif-detail-text">{{ n.detail }}</pre>
          </div>
          <div class="notif-meta">
            <span class="notif-time"><RelativeTime :value="n.timestamp" /></span>
            <span class="notif-source">{{ n.source }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-else-if="activeTab === 'guidance' && guidance.notifications.length > 0" class="notif-list">
      <div
        v-for="n in guidance.notifications"
        :key="n.id"
        class="notif-item guidance-item"
        :class="{ unread: !n.shown_at && !n.clicked_at && !n.dismissed_at }"
      >
        <div class="notif-icon severity-guidance">
          <i class="pi pi-bell"></i>
        </div>
        <div class="notif-body">
          <div class="notif-title-row">
            <span class="notif-title">{{ n.title }}</span>
            <span class="guidance-rule">{{ guidanceRuleLabel(n.rule_id) }}</span>
          </div>
          <div v-if="n.body" class="notif-message">{{ n.body }}</div>
          <div class="guidance-actions">
            <button
              v-if="guidanceActionLabel(n)"
              class="guidance-link"
              type="button"
              @click.stop="guidance.clickNotification(n)"
            >
              {{ guidanceActionLabel(n) }}
            </button>
            <button
              v-if="!n.dismissed_at && !n.clicked_at"
              class="guidance-link muted"
              type="button"
              @click.stop="guidance.dismissNotification(n)"
            >
              Dismiss
            </button>
          </div>
          <div class="notif-meta">
            <span class="notif-time"><RelativeTime :value="Date.parse(n.created_at)" /></span>
            <span class="notif-source">{{ guidanceStatus(n) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else class="notif-empty">
      <i class="pi pi-check-circle"></i>
      <p>
        {{
          activeTab === "action"
            ? "No action required"
            : activeTab === "guidance"
              ? "No guidance yet"
            : "No notifications yet"
        }}
      </p>
      <small v-if="activeTab === 'guidance'">
        Guidance suggestions will appear here after they are shown.
      </small>
      <small v-if="activeTab === 'all'">
        Notifications from jobs, deployments, and system events will appear
        here.
      </small>
    </div>
  </Sidebar>
</template>

<script setup lang="ts">
import RelativeTime from "@/components/RelativeTime.vue";
import { ref, computed, watch } from "vue";
import Sidebar from "primevue/sidebar";
import Button from "primevue/button";
import { resolveGuidanceAction } from "@/lib/actionOntology";
import { guidanceRuleLabel } from "@/lib/guidanceRules";
import type { GuidanceNotification } from "@/lib/guidanceAdapter";
import {
  useNotificationStore,
  type AppNotification,
} from "@/stores/notification";
import { useAppConfig } from "@/composables/useAppConfig";
import { useGuidanceStore } from "@/stores/guidance";

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const store = useNotificationStore();
const guidance = useGuidanceStore();
const { isFeatureEnabled } = useAppConfig();
const guidanceEnabled = computed(() => isFeatureEnabled("sherpaGuidance"));
const activeTab = ref<"all" | "action" | "guidance">("all");
const expandedId = ref<string | null>(null);
const copiedId = ref<string | null>(null);

function toggleExpand(n: AppNotification) {
  expandedId.value = expandedId.value === n.id ? null : n.id;
  store.markRead(n.id);
}

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit("update:modelValue", value),
});

const displayedNotifications = computed(() => {
  if (activeTab.value === "action") {
    return store.actionRequired;
  }
  return store.notifications;
});

function onNotificationClick(n: AppNotification) {
  store.markRead(n.id);
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

async function copyNotification(n: AppNotification) {
  const text = [
    `[${n.severity.toUpperCase()}] ${n.title}`,
    n.message,
    n.detail ? `\n${n.detail}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  try {
    await copyText(text);
    copiedId.value = n.id;
    window.setTimeout(() => {
      if (copiedId.value === n.id) copiedId.value = null;
    }, 1500);
  } catch (err) {
    console.warn("[Notifications] Failed to copy notification", err);
  }
}

function refreshGuidance() {
  if (!guidanceEnabled.value) return;
  void guidance.loadNotifications({ includeDismissed: true, limit: 100 });
}

function guidanceActionLabel(n: GuidanceNotification): string | null {
  return resolveGuidanceAction(n.action_id)?.label ?? null;
}

function guidanceStatus(n: GuidanceNotification): string {
  if (n.clicked_at) return "clicked";
  if (n.dismissed_at) return "dismissed";
  if (n.shown_at) return "shown";
  return n.source;
}

watch(guidanceEnabled, (enabled) => {
  if (!enabled && activeTab.value === "guidance") activeTab.value = "all";
});

watch(
  () => [visible.value, activeTab.value] as const,
  ([isVisible, tab]) => {
    if (isVisible && tab === "guidance") {
      refreshGuidance();
    }
  },
  { immediate: true }
);

function severityIcon(severity: AppNotification["severity"]): string {
  switch (severity) {
    case "success":
      return "pi pi-check-circle";
    case "error":
      return "pi pi-times-circle";
    case "warning":
      return "pi pi-exclamation-triangle";
    case "info":
    default:
      return "pi pi-info-circle";
  }
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
  color: var(--ss-action);
}

.header-title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--ss-text-strong);
}

.unread-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: var(--ss-danger);
  color: var(--ss-on-action);
  font-size: 0.75rem;
  font-weight: 600;
}

/* Tabs */
.notif-tabs {
  display: flex;
  gap: 4px;
  padding: 0 0 12px;
  border-bottom: 1px solid var(--ss-border);
  margin-bottom: 12px;
}

.notif-tab {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--ss-text-muted);
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.notif-tab:hover {
  background: var(--ss-surface-subtle);
  color: var(--ss-action-text);
}

.notif-tab.active {
  background: var(--ss-action-tint);
  color: var(--ss-action);
}

/* Action bar */
.notif-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-bottom: 12px;
}

/* Notification list */
.notif-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.notif-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  border-radius: 8px;
  background: var(--ss-surface);
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  user-select: text;
  -webkit-user-select: text;
}

.notif-item:hover {
  background: var(--ss-surface-subtle);
  border-color: var(--ss-border);
}

.notif-item.unread {
  background: var(--ss-info-surface);
  border-color: var(--ss-info-surface);
}

/* Severity icons */
.notif-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  flex-shrink: 0;
}

.notif-icon i {
  font-size: 1rem;
}

.severity-success {
  background: var(--ss-success-surface);
  color: var(--ss-success);
}

.severity-error {
  background: var(--ss-danger-surface);
  color: var(--ss-danger);
}

.severity-warning {
  background: var(--ss-warning-surface);
  color: var(--ss-warning);
}

.severity-info {
  background: var(--ss-action-tint);
  color: var(--ss-action);
}

.severity-guidance {
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
}

/* Body */
.notif-body {
  flex: 1;
  min-width: 0;
}

.notif-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.notif-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--ss-text-strong);
  flex: 1;
  min-width: 0;
}

.notif-unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ss-action);
  flex-shrink: 0;
}

.notif-message {
  font-size: 0.85rem;
  color: var(--ss-text-secondary);
  margin-top: 2px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.notif-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.notif-time {
  font-size: 0.75rem;
  color: var(--ss-text-muted);
}

.notif-source {
  font-size: 0.7rem;
  color: var(--ss-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.guidance-item {
  border-color: var(--ss-accent-faint);
}

.guidance-rule {
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--ss-accent-faint);
  color: var(--ss-accent);
  font-size: 0.68rem;
  font-weight: 700;
}

.guidance-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.guidance-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--ss-accent);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 700;
}

.guidance-link:hover {
  color: var(--ss-accent);
  text-decoration: underline;
}

.guidance-link.muted {
  color: var(--ss-text-muted);
}

/* Empty state */
.notif-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 24px;
  color: var(--ss-text-muted);
  text-align: center;
}

.notif-empty i {
  font-size: 2.5rem;
  margin-bottom: 12px;
}

.notif-empty p {
  margin: 0;
  font-size: 1rem;
  color: var(--ss-text-muted);
  font-weight: 500;
}

.notif-empty small {
  margin-top: 8px;
  font-size: 0.85rem;
  color: var(--ss-text-muted);
  max-width: 280px;
  line-height: 1.4;
}

.notif-row-actions {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  user-select: none;
  -webkit-user-select: none;
}

.notif-icon-btn {
  background: none;
  border: none;
  color: var(--ss-text-muted);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  line-height: 1;
}

.notif-icon-btn:hover {
  color: var(--ss-text-secondary);
  background: var(--ss-surface-subtle);
}

.notif-detail {
  margin-top: 8px;
  padding: 8px 12px;
  background: var(--ss-surface-subtle);
  border-radius: 6px;
  border: 1px solid var(--ss-border);
}

.notif-detail-text {
  font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace;
  font-size: 0.75rem;
  color: var(--ss-action-text);
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  max-height: 200px;
  overflow-y: auto;
}
</style>
