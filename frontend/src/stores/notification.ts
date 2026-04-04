import { defineStore } from "pinia";
import { computed, ref } from "vue";

export interface AppNotification {
  id: string;
  source: "job" | "deploy" | "batch" | "system" | "sherpa";
  severity: "info" | "success" | "warning" | "error";
  title: string;
  message: string;
  detail?: string;  // expandable error detail (stack trace, response body)
  timestamp: number;
  readAt: number | null;
  entityRef?: {
    type: "job" | "workflow" | "experiment";
    id: number;
  };
}

type NewNotification = Omit<AppNotification, "id" | "timestamp" | "readAt">;

const MAX_NOTIFICATIONS = 200;
const DEDUPE_WINDOW_MS = 5000;

export const useNotificationStore = defineStore("notification", () => {
  const notifications = ref<AppNotification[]>([]);

  const unreadCount = computed(
    () => notifications.value.filter((n) => n.readAt === null).length
  );

  const hasUnread = computed(() => unreadCount.value > 0);

  const actionRequired = computed(() =>
    notifications.value.filter(
      (n) =>
        n.readAt === null &&
        (n.severity === "error" || n.severity === "warning")
    )
  );

  function add(input: NewNotification) {
    // Dedupe: if a matching notification exists within the window, update it
    if (input.entityRef) {
      const now = Date.now();
      const existing = notifications.value.find(
        (n) =>
          n.source === input.source &&
          n.entityRef?.type === input.entityRef!.type &&
          n.entityRef?.id === input.entityRef!.id &&
          now - n.timestamp < DEDUPE_WINDOW_MS
      );
      if (existing) {
        existing.severity = input.severity;
        existing.title = input.title;
        existing.message = input.message;
        existing.detail = input.detail;
        existing.timestamp = now;
        existing.readAt = null;
        return;
      }
    }

    const notification: AppNotification = {
      ...input,
      id: crypto.randomUUID(),
      timestamp: Date.now(),
      readAt: null,
    };

    notifications.value.unshift(notification);

    // Cap at max
    if (notifications.value.length > MAX_NOTIFICATIONS) {
      notifications.value = notifications.value.slice(0, MAX_NOTIFICATIONS);
    }
  }

  function markRead(id: string) {
    const n = notifications.value.find((n) => n.id === id);
    if (n && n.readAt === null) {
      n.readAt = Date.now();
    }
  }

  function markAllRead() {
    const now = Date.now();
    for (const n of notifications.value) {
      if (n.readAt === null) {
        n.readAt = now;
      }
    }
  }

  function remove(id: string) {
    notifications.value = notifications.value.filter((n) => n.id !== id);
  }

  function clearAll() {
    notifications.value = [];
  }

  return {
    notifications,
    unreadCount,
    hasUnread,
    actionRequired,
    add,
    markRead,
    markAllRead,
    remove,
    clearAll,
  };
});
