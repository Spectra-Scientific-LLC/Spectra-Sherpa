import type { NewNotification } from "@/stores/notification";

export type ToastMessage = {
  severity?: string;
  summary?: unknown;
  detail?: unknown;
};

export type ToastServiceApi = {
  add?: (message: ToastMessage) => void;
};

export function stringifyErrorDetail(value: unknown): string | undefined {
  if (!value) return undefined;
  if (value instanceof Error) {
    return value.stack || value.message;
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function notificationSeverityFromToast(
  severity: string | undefined,
): "warning" | "error" | null {
  if (severity === "warn" || severity === "warning") return "warning";
  if (severity === "error") return "error";
  return null;
}

/**
 * The single path from toasts to the notification centre.
 *
 * Every warning or error toast, from the shell or a server module, is kept in
 * the notification centre exactly once; success and info toasts stay
 * transient. Callers just call `toast.add` and must not also add the same
 * message to the notification store.
 */
export function persistWarningAndErrorToasts(
  toastService: ToastServiceApi | undefined,
  record: (notification: NewNotification) => void,
): void {
  if (!toastService?.add) return;
  const originalAdd = toastService.add.bind(toastService);
  toastService.add = (message: ToastMessage) => {
    const severity = notificationSeverityFromToast(message.severity);
    if (severity) {
      const title =
        typeof message.summary === "string" && message.summary.trim()
          ? message.summary
          : severity === "error"
            ? "Error"
            : "Warning";
      const detail =
        typeof message.detail === "string"
          ? message.detail
          : stringifyErrorDetail(message.detail);
      record({
        source: "system",
        severity,
        title,
        message: detail || "A warning or error occurred.",
        detail,
      });
    }
    originalAdd(message);
  };
}
