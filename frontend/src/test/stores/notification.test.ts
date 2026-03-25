import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import { useNotificationStore, type AppNotification } from "@/stores/notification";

describe("Notification Store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("initializes empty", () => {
    const store = useNotificationStore();
    expect(store.notifications).toEqual([]);
    expect(store.unreadCount).toBe(0);
    expect(store.hasUnread).toBe(false);
  });

  describe("add", () => {
    it("adds a notification with generated id and timestamp", () => {
      const store = useNotificationStore();
      store.add({
        source: "job",
        severity: "success",
        title: "Job Done",
        message: "Job #1 completed",
      });

      expect(store.notifications.length).toBe(1);
      expect(store.notifications[0].title).toBe("Job Done");
      expect(store.notifications[0].id).toBeTruthy();
      expect(store.notifications[0].readAt).toBeNull();
      expect(store.unreadCount).toBe(1);
    });

    it("prepends new notifications", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "info", title: "First", message: "1" });
      store.add({ source: "job", severity: "info", title: "Second", message: "2" });

      expect(store.notifications[0].title).toBe("Second");
      expect(store.notifications[1].title).toBe("First");
    });

    it("caps at max notifications", () => {
      const store = useNotificationStore();
      for (let i = 0; i < 210; i++) {
        store.add({ source: "system", severity: "info", title: `N${i}`, message: `m${i}` });
      }
      expect(store.notifications.length).toBe(200);
    });

    it("deduplicates by entityRef within time window", () => {
      const store = useNotificationStore();
      store.add({
        source: "job",
        severity: "info",
        title: "Running",
        message: "Job #5 running",
        entityRef: { type: "job", id: 5 },
      });
      store.add({
        source: "job",
        severity: "success",
        title: "Done",
        message: "Job #5 done",
        entityRef: { type: "job", id: 5 },
      });

      // Should have updated the existing one, not created a new one
      expect(store.notifications.length).toBe(1);
      expect(store.notifications[0].title).toBe("Done");
      expect(store.notifications[0].severity).toBe("success");
    });
  });

  describe("markRead / markAllRead", () => {
    it("marks a single notification as read", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "info", title: "T", message: "M" });
      const id = store.notifications[0].id;

      store.markRead(id);

      expect(store.notifications[0].readAt).not.toBeNull();
      expect(store.unreadCount).toBe(0);
    });

    it("marks all notifications as read", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "info", title: "A", message: "1" });
      store.add({ source: "job", severity: "info", title: "B", message: "2" });
      expect(store.unreadCount).toBe(2);

      store.markAllRead();

      expect(store.unreadCount).toBe(0);
      expect(store.hasUnread).toBe(false);
    });
  });

  describe("remove / clearAll", () => {
    it("removes a single notification by id", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "info", title: "T", message: "M" });
      const id = store.notifications[0].id;

      store.remove(id);

      expect(store.notifications.length).toBe(0);
    });

    it("clears all notifications", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "info", title: "A", message: "1" });
      store.add({ source: "job", severity: "info", title: "B", message: "2" });

      store.clearAll();

      expect(store.notifications.length).toBe(0);
    });
  });

  describe("actionRequired", () => {
    it("returns only unread error/warning notifications", () => {
      const store = useNotificationStore();
      store.add({ source: "job", severity: "error", title: "E", message: "err" });
      store.add({ source: "job", severity: "info", title: "I", message: "info" });
      store.add({ source: "system", severity: "warning", title: "W", message: "warn" });

      expect(store.actionRequired.length).toBe(2);
      expect(store.actionRequired.map((n) => n.severity)).toEqual(["warning", "error"]);
    });
  });
});
