import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { reactive } from "vue";
import { useClipboardStore } from "@/stores/clipboard";
import { useNotificationStore } from "@/stores/notification";
import { createSherpaRequestId } from "@/lib/sherpaEvents";

const auth = reactive({ user: { id: 1 } as { id: number } | null, sessionRevision: 1 });
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));

describe("production login boundaries", () => {
  it("can notify and correlate requests without secure-context randomUUID", () => {
    setActivePinia(createPinia());
    const uuid = vi.spyOn(crypto, "randomUUID").mockImplementation(undefined as never);
    // Plain LAN HTTP exposes crypto but not randomUUID.
    Object.defineProperty(crypto, "randomUUID", { configurable: true, value: undefined });
    try {
      const notifications = useNotificationStore();
      notifications.add({ source: "system", severity: "info", title: "HTTP", message: "available" });
      expect(notifications.notifications).toHaveLength(1);
      expect(createSherpaRequestId()).toMatch(/^[0-9a-f-]{36}$/);
      expect(createSherpaRequestId()).not.toBe(createSherpaRequestId());
    } finally {
      uuid.mockRestore();
    }
  });
  beforeEach(() => {
    setActivePinia(createPinia());
    auth.user = { id: 1 };
    auth.sessionRevision += 1;
  });

  it("clears copied scientific context on logout, without depending on the canvas being mounted", () => {
    const store = useClipboardStore();
    store.set({ nodes: [{ id: "pca", type: "model.pca", x: 0, y: 0,
      params: { private_annotation: "account-one" } }], edges: [], sourceWorkflowId: 7 });
    auth.user = null;
    expect(store.get()).toBeNull();
    expect(store.isEmpty()).toBe(true);
  });

  it("clears notifications when the account changes", () => {
    const store = useNotificationStore();
    store.add({ source: "job", severity: "error", title: "Private analysis", message: "account-one result" });
    auth.user = { id: 2 };
    expect(store.notifications).toEqual([]);
    expect(store.unreadCount).toBe(0);
  });

  it("clears both on an explicit new login to the same account", () => {
    const clipboard = useClipboardStore();
    const notifications = useNotificationStore();
    clipboard.set({ nodes: [{ id: "pca", type: "model.pca", x: 0, y: 0, params: {} }], edges: [], sourceWorkflowId: 7 });
    notifications.add({ source: "job", severity: "info", title: "Old login", message: "old" });
    auth.sessionRevision += 1;
    expect(clipboard.isEmpty()).toBe(true);
    expect(notifications.notifications).toEqual([]);
  });

  it("retains same-login clipboard and notifications when account identity is unchanged", () => {
    const clipboard = useClipboardStore();
    const notifications = useNotificationStore();
    clipboard.set({ nodes: [{ id: "pca", type: "model.pca", x: 0, y: 0, params: {} }], edges: [], sourceWorkflowId: 7 });
    notifications.add({ source: "job", severity: "info", title: "Current login", message: "current" });
    auth.user = { id: 1 };
    expect(clipboard.get()?.sourceWorkflowId).toBe(7);
    expect(notifications.notifications).toHaveLength(1);
  });
});
