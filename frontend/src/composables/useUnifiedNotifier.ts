import { useToast } from "primevue/usetoast";
import {
  useNotificationStore,
  type AppNotification,
} from "@/stores/notification";

type Severity = AppNotification["severity"];

interface NotifyOptions {
  severity: Severity;
  summary: string;
  detail: string;
  /** Extended detail for notification center (stack trace, response body) */
  extendedDetail?: string;
  /** Toast lifetime in ms. Default: 4000 for info/success, 6000 for error/warning */
  life?: number;
  /** Source for notification center. Default: "system" */
  source?: AppNotification["source"];
  /** Entity reference for deduplication */
  entityRef?: AppNotification["entityRef"];
}

// PrimeVue toast uses "warn" instead of "warning"
type ToastSeverity = "info" | "success" | "warn" | "error";
function toToastSeverity(s: Severity): ToastSeverity {
  return s === "warning" ? "warn" : s;
}

export function useUnifiedNotifier() {
  const toast = useToast();
  const store = useNotificationStore();

  function notify(options: NotifyOptions) {
    const life =
      options.life ??
      (options.severity === "error" || options.severity === "warning"
        ? 6000
        : 4000);

    // Always show transient toast
    toast.add({
      severity: toToastSeverity(options.severity),
      summary: options.summary,
      detail: options.detail,
      life,
    });

    // Persist error and warning notifications in the notification center
    if (options.severity === "error" || options.severity === "warning") {
      store.add({
        source: options.source ?? "system",
        severity: options.severity,
        title: options.summary,
        message: options.detail,
        detail: options.extendedDetail,
        entityRef: options.entityRef,
      });
    }
  }

  /** Convenience: fire error toast + persist to notification center */
  function notifyError(
    summary: string,
    detail: string,
    extendedDetail?: string,
  ) {
    notify({ severity: "error", summary, detail, extendedDetail });
  }

  /** Convenience: fire warning toast + persist to notification center */
  function notifyWarning(
    summary: string,
    detail: string,
    extendedDetail?: string,
  ) {
    notify({ severity: "warning", summary, detail, extendedDetail });
  }

  /** Convenience: fire success toast only (no persistence) */
  function notifySuccess(summary: string, detail: string) {
    toast.add({ severity: "success", summary, detail, life: 4000 });
  }

  /** Convenience: fire info toast only (no persistence) */
  function notifyInfo(summary: string, detail: string) {
    toast.add({ severity: "info", summary, detail, life: 3000 });
  }

  return { notify, notifyError, notifyWarning, notifySuccess, notifyInfo };
}
