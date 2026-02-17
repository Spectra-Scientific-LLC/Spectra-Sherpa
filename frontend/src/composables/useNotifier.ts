import { useNotificationStore, type AppNotification } from "@/stores/notification";

type JobUpdateNotification = {
  jobId: number;
  status?: string | null;
  message?: string | null;
};

type DeployOutcomeNotification = {
  success: boolean;
  message: string;
};

type SystemEventNotification = {
  severity?: AppNotification["severity"];
  title: string;
  message: string;
};

const TERMINAL_JOB_STATUSES = new Set(["completed", "failed"]);

export function useNotifier() {
  const store = useNotificationStore();

  function notifyJobUpdate(input: JobUpdateNotification) {
    const status = (input.status ?? "").toLowerCase();
    if (!TERMINAL_JOB_STATUSES.has(status)) {
      return;
    }

    const completed = status === "completed";
    store.add({
      source: "job",
      severity: completed ? "success" : "error",
      title: completed ? "Job Completed" : "Job Failed",
      message: input.message || `Job #${input.jobId} ${status}`,
      entityRef: { type: "job", id: input.jobId },
    });
  }

  function notifyDeployOutcome(input: DeployOutcomeNotification) {
    store.add({
      source: "deploy",
      severity: input.success ? "success" : "error",
      title: input.success ? "Deploy Succeeded" : "Deploy Failed",
      message: input.message,
    });
  }

  function notifySystemEvent(input: SystemEventNotification) {
    store.add({
      source: "system",
      severity: input.severity ?? "info",
      title: input.title,
      message: input.message,
    });
  }

  return {
    notifyJobUpdate,
    notifyDeployOutcome,
    notifySystemEvent,
  };
}
