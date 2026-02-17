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
    </div>

    <!-- Action bar -->
    <div v-if="displayedNotifications.length > 0" class="notif-actions">
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

    <!-- Notification list -->
    <div v-if="displayedNotifications.length > 0" class="notif-list">
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
          </div>
          <div class="notif-message">{{ n.message }}</div>
          <div class="notif-meta">
            <span class="notif-time">{{ timeAgo(n.timestamp) }}</span>
            <span class="notif-source">{{ n.source }}</span>
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
            : "No notifications yet"
        }}
      </p>
      <small v-if="activeTab === 'all'">
        Notifications from jobs, deployments, and system events will appear
        here.
      </small>
    </div>
  </Sidebar>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import Sidebar from "primevue/sidebar";
import Button from "primevue/button";
import {
  useNotificationStore,
  type AppNotification,
} from "@/stores/notification";

const props = defineProps<{
  modelValue: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: boolean): void;
}>();

const store = useNotificationStore();
const activeTab = ref<"all" | "action">("all");

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

function timeAgo(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  return `${days}d ago`;
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

.unread-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: #ef4444;
  color: #ffffff;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Tabs */
.notif-tabs {
  display: flex;
  gap: 4px;
  padding: 0 0 12px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 12px;
}

.notif-tab {
  padding: 6px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.notif-tab:hover {
  background: #f1f5f9;
  color: #334155;
}

.notif-tab.active {
  background: #dbeafe;
  color: #1d4ed8;
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
  background: #ffffff;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}

.notif-item:hover {
  background: #f8fafc;
  border-color: #e2e8f0;
}

.notif-item.unread {
  background: #f0f9ff;
  border-color: #bae6fd;
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
  background: #dcfce7;
  color: #16a34a;
}

.severity-error {
  background: #fee2e2;
  color: #dc2626;
}

.severity-warning {
  background: #fef3c7;
  color: #d97706;
}

.severity-info {
  background: #dbeafe;
  color: #2563eb;
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
  color: #1e293b;
}

.notif-unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3b82f6;
  flex-shrink: 0;
}

.notif-message {
  font-size: 0.85rem;
  color: #475569;
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
  color: #94a3b8;
}

.notif-source {
  font-size: 0.7rem;
  color: #94a3b8;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Empty state */
.notif-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 24px;
  color: #94a3b8;
  text-align: center;
}

.notif-empty i {
  font-size: 2.5rem;
  margin-bottom: 12px;
}

.notif-empty p {
  margin: 0;
  font-size: 1rem;
  color: #64748b;
  font-weight: 500;
}

.notif-empty small {
  margin-top: 8px;
  font-size: 0.85rem;
  color: #94a3b8;
  max-width: 280px;
  line-height: 1.4;
}
</style>
