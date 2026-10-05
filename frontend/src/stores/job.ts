import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import type { JobInfo } from "@/types";
import { buildAuthMessage, buildWsUrl, resolveWsPolicyClose, withCredentials } from "@/utils/ws";
import { useAuthStore } from "@/stores/auth";
import { useNotifier } from "@/composables/useNotifier";

export const useJobStore = defineStore("job", () => {
  const authStore = useAuthStore();
  // NOTE: useNotifier only accesses Pinia stores, which is safe inside
  // defineStore.  Do NOT add useToast() or other component-context APIs
  // inside useNotifier — those require a component setup context.
  const { notifyJobUpdate } = useNotifier();
  const jobs = ref<JobInfo[]>([]);
  const connected = ref(false);
  const wsRef = ref<WebSocket | null>(null);
  const connectionStatus = ref<"disconnected" | "connecting" | "connected">(
    "disconnected"
  );
  const lastError = ref<string | null>(null);
  const reconnectAttempts = ref(0);
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let allowReconnect = true;
  let connectionGeneration = 0;
  let policyCloseController: AbortController | null = null;

  const cancelPolicyProbe = () => {
    policyCloseController?.abort();
    policyCloseController = null;
  };

  const resolveCurrentPolicyClose = async (generation: number) => {
    cancelPolicyProbe();
    const controller = new AbortController();
    policyCloseController = controller;
    const resolution = await resolveWsPolicyClose(controller.signal);
    if (policyCloseController === controller) policyCloseController = null;
    if (generation !== connectionGeneration || controller.signal.aborted || !allowReconnect) return null;
    return resolution;
  };

  let pendingConnect: Promise<void> | null = null;

  const jobMap = computed(() => {
    const map = new Map<number, JobInfo>();
    jobs.value.forEach((job) => map.set(job.id, job));
    return map;
  });

  const fetchJobs = async () => {
    const response = await api.get<JobInfo[]>("/jobs");
    jobs.value = response.data;
  };

  const fetchJob = async (jobId: number) => {
    const response = await api.get<JobInfo>(`/jobs/${jobId}`);
    const existingIndex = jobs.value.findIndex((job) => job.id === jobId);
    if (existingIndex >= 0) {
      jobs.value[existingIndex] = response.data;
    } else {
      jobs.value.unshift(response.data);
    }
    return response.data;
  };

  const updateJob = (payload: Partial<JobInfo> & { id: number }) => {
    const existing = jobMap.value.get(payload.id);
    if (!existing) {
      return;
    }
    if (payload.status !== undefined) {
      existing.status = payload.status;
    }
    if (payload.progress !== undefined) {
      existing.progress = payload.progress;
    }
    if (payload.progress_message !== undefined) {
      existing.progress_message = payload.progress_message;
    }
  };

  const clearReconnect = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const MAX_RECONNECT_ATTEMPTS = 10;

  const scheduleReconnect = () => {
    if (!allowReconnect || reconnectTimer !== null) {
      return;
    }
    reconnectAttempts.value += 1;
    if (reconnectAttempts.value > MAX_RECONNECT_ATTEMPTS) {
      connectionStatus.value = "disconnected";
      lastError.value = "Max reconnection attempts reached";
      return;
    }
    const delay = Math.min(1000 * 2 ** (reconnectAttempts.value - 1), 30000);
    connectionStatus.value = "connecting";
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect().catch(() => undefined);
    }, delay);
  };

  const connect = (): Promise<void> => {
    if (wsRef.value && wsRef.value.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    if (wsRef.value && wsRef.value.readyState === WebSocket.CONNECTING) {
      return pendingConnect || Promise.resolve();
    }
    clearReconnect();
    cancelPolicyProbe();
    const generation = ++connectionGeneration;
    allowReconnect = true;
    connectionStatus.value = "connecting";
    lastError.value = null;
    const wsUrl = withCredentials(buildWsUrl());
    const socket = new WebSocket(wsUrl);
    wsRef.value = socket;

    socket.addEventListener("open", () => {
      if (generation !== connectionGeneration) return;
      socket.send(buildAuthMessage());
    });

    socket.addEventListener("message", async (event) => {
      if (generation !== connectionGeneration) return;
      try {
        const payload = JSON.parse(event.data);
        if (payload?.type === "authenticated") {
          connected.value = true;
          connectionStatus.value = "connected";
          reconnectAttempts.value = 0;
          const userChannel = authStore.user?.id ? `jobs:${authStore.user.id}` : "jobs";
          socket.send(JSON.stringify({ action: "subscribe", channel: userChannel }));
          fetchJobs().catch(() => undefined);
          return;
        }
        if (payload?.type === "ping") {
          socket.send(JSON.stringify({ action: "pong" }));
          return;
        }
        if (payload?.type === "pong") {
          return;
        }
        if (payload?.job_id) {
          const jobId = Number(payload.job_id);
          if (!jobMap.value.has(jobId)) {
            await fetchJob(jobId);
          } else {
            updateJob({
              id: jobId,
              status: payload.status,
              progress: payload.progress,
              progress_message: payload.message,
            });
          }
          // Dispatch DOM event so BatchRunTab and other listeners can react
          window.dispatchEvent(
            new CustomEvent("job-update", { detail: payload })
          );

          // Emit notification on terminal job states.
          notifyJobUpdate({
            jobId,
            status: payload.status,
            message: payload.message,
          });
        }

        // Dispatch workflow node status events (from workflow:{id} channels)
        if (payload?.type === "node_status" && payload?.node_id) {
          window.dispatchEvent(
            new CustomEvent("workflow-node-status", { detail: payload })
          );
        }
      } catch {
        // Ignore malformed payloads
      }
    });

    socket.addEventListener("close", (event) => {
      if (generation !== connectionGeneration) return;
      connected.value = false;
      wsRef.value = null;
      connectionStatus.value = "disconnected";
      if (event.code === 1008) {
        // 1008 conflates credential rejection with policy closures (managed
        // trial pause, live-session revalidation). Never discard the stored
        // session speculatively: confirm it over HTTP first — the api
        // client's shared logout path handles confirmed rejection.
        void resolveCurrentPolicyClose(generation).then((resolution) => {
          if (!resolution || resolution === "cancelled") return;
          if (resolution === "retry-with-api-key") {
            reconnectAttempts.value = 0;
            scheduleReconnect();
            return;
          }
          if (resolution === "session-confirmed" || resolution === "session-unconfirmed") {
            lastError.value = "Live updates paused by server policy. Reconnecting.";
            scheduleReconnect();
            return;
          }
          lastError.value = "Unauthorized. Check your credentials.";
          allowReconnect = false;
        });
        return;
      }
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      if (generation !== connectionGeneration) return;
      lastError.value = "WebSocket error.";
    });

    pendingConnect = new Promise((resolve, reject) => {
      const handleOpen = () => {
        if (generation === connectionGeneration) pendingConnect = null;
        resolve();
      };
      const handleClose = (event: CloseEvent) => {
        if (generation === connectionGeneration) pendingConnect = null;
        reject(
          new Error(
            event.code === 1008 ? "Unauthorized WebSocket connection." : "WebSocket closed."
          )
        );
      };
      socket.addEventListener("open", handleOpen, { once: true });
      socket.addEventListener("close", handleClose, { once: true });
    });

    return pendingConnect;
  };

  const disconnect = () => {
    connectionGeneration += 1;
    cancelPolicyProbe();
    allowReconnect = false;
    clearReconnect();
    wsRef.value?.close();
    wsRef.value = null;
    connected.value = false;
    connectionStatus.value = "disconnected";
  };

  const reconnect = async () => {
    disconnect();
    allowReconnect = true;
    reconnectAttempts.value = 0;
    await connect();
  };

  return {
    jobs,
    connected,
    wsRef,
    fetchJobs,
    fetchJob,
    connect,
    disconnect,
    reconnect,
    connectionStatus,
    lastError,
  };
});
