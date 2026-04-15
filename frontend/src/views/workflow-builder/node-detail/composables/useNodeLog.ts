import { ref } from "vue";

export interface LogEntry {
  time: string;
  type: "info" | "success" | "error" | "warn";
  message: string;
  details?: string;
}

const MAX_LOG_ENTRIES = 50;

export function useNodeLog() {
  const executionLogs = ref<LogEntry[]>([]);

  const addLog = (type: LogEntry["type"], message: string, details?: string) => {
    const now = new Date();
    const time = now.toLocaleTimeString("en-US", { hour12: false });
    executionLogs.value.unshift({ time, type, message, details });
    if (executionLogs.value.length > MAX_LOG_ENTRIES) {
      executionLogs.value.pop();
    }
  };

  const clearLogs = () => {
    executionLogs.value = [];
  };

  const getLogIcon = (type: LogEntry["type"]): string => {
    switch (type) {
      case "success":
        return "pi pi-check-circle";
      case "error":
        return "pi pi-times-circle";
      case "warn":
        return "pi pi-exclamation-triangle";
      default:
        return "pi pi-info-circle";
    }
  };

  return { executionLogs, addLog, clearLogs, getLogIcon };
}
