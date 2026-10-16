import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { persistWarningAndErrorToasts, type ToastServiceApi } from "@/lib/toastNotifications";
import { useNotificationStore } from "@/stores/notification";

describe("toast to notification centre", () => {
  let shown: ReturnType<typeof vi.fn>;
  let toast: ToastServiceApi;

  beforeEach(() => {
    setActivePinia(createPinia());
    shown = vi.fn();
    toast = { add: shown };
    const store = useNotificationStore();
    persistWarningAndErrorToasts(toast, (notification) => store.add(notification));
  });

  it("keeps each warning and error once and leaves success and info transient", () => {
    toast.add!({ severity: "error", summary: "Delete failed", detail: "Could not delete the key." });
    toast.add!({ severity: "warn", summary: "Autosave", detail: "Saved in this browser only." });
    toast.add!({ severity: "success", summary: "Saved", detail: "Key saved." });
    toast.add!({ severity: "info", summary: "Copied", detail: "Copied to clipboard." });

    expect(shown).toHaveBeenCalledTimes(4);
    const kept = useNotificationStore().notifications;
    expect(kept.map((n) => [n.severity, n.title, n.message])).toEqual(
      expect.arrayContaining([
        ["error", "Delete failed", "Could not delete the key."],
        ["warning", "Autosave", "Saved in this browser only."],
      ]),
    );
    expect(kept).toHaveLength(2);
  });

  it("does not stack a repeated failure", () => {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      toast.add!({ severity: "error", summary: "Delete failed", detail: "Could not delete the key." });
    }
    expect(shown).toHaveBeenCalledTimes(3);
    expect(useNotificationStore().notifications).toHaveLength(1);
  });

  it("names a failure that has no summary and keeps structured detail readable", () => {
    toast.add!({ severity: "error", detail: { status: 500 } });
    const [kept] = useNotificationStore().notifications;
    expect(kept.title).toBe("Error");
    expect(kept.detail).toContain('"status": 500');
  });
});
