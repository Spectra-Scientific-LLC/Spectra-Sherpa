import type { NewNotification } from "@/stores/notification";

export type ToastMessage = {
  severity?: string;
  summary?: unknown;
  detail?: unknown;
  life?: number;
};

/** How long a confirmation stays visible; warnings, errors and refusals stay until dismissed. */
export const CONFIRMATION_LIFE_MS = 4000;

/**
 * A toast answers something the user just did. A confirmation (success or
 * info) closes by itself; a warning, failure or refusal stays until the user
 * dismisses it, because it may change what they do next. State that is true
 * without a click belongs in page text, not in a toast.
 */
export function applyToastLife(message: ToastMessage): void {
  if (notificationSeverityFromToast(message.severity)) {
    delete message.life;
  } else if (message.life == null) {
    message.life = CONFIRMATION_LIFE_MS;
  }
}

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
 * the notification centre exactly once and stays on screen until dismissed;
 * success and info toasts close by themselves (see `applyToastLife`). Callers just call `toast.add` and must not also add the same
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
    applyToastLife(message);
    originalAdd(message);
  };
}
