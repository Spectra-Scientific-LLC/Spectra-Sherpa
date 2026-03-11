import { ref } from 'vue';
import api from '@/api/client';

const backendConnected = ref(true);
const backendDegraded = ref(false);
const checkingStatus = ref(false);
const pluginFailureCount = ref(0);
let healthCheckInterval: number | null = null;

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function probeHealth(): Promise<{ connected: boolean; degraded: boolean; pluginFailureCount: number }> {
  try {
    const response = await api.get("/health", { timeout: 3000 });
    const status = response.data?.status;
    const pluginFailureCount = Number.isFinite(response.data?.plugin_failure_count)
      ? Number(response.data.plugin_failure_count)
      : Array.isArray(response.data?.plugin_failures)
        ? response.data.plugin_failures.length
        : 0;
    return {
      connected: true,
      degraded: status === "degraded",
      pluginFailureCount,
    };
  } catch {
    return { connected: false, degraded: false, pluginFailureCount: 0 };
  }
}

export function useBackendStatus() {
  const checkBackendStatus = async () => {
    checkingStatus.value = true;
    try {
      const initial = await probeHealth();
      if (initial.connected) {
        backendConnected.value = true;
        backendDegraded.value = initial.degraded;
        pluginFailureCount.value = initial.pluginFailureCount;
        console.log("[BackendStatus] Backend connection established");
        return;
      }

      // First attempt failed — retry up to MAX_RETRIES times before reporting
      for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        await sleep(RETRY_DELAY_MS);
        const retry = await probeHealth();
        if (retry.connected) {
          backendConnected.value = true;
          backendDegraded.value = retry.degraded;
          pluginFailureCount.value = retry.pluginFailureCount;
          console.log(`[BackendStatus] Backend recovered on retry ${attempt}`);
          return;
        }
      }

      // All retries exhausted
      backendConnected.value = false;
      backendDegraded.value = false;
      pluginFailureCount.value = 0;
      console.error("[BackendStatus] Backend unreachable after retries");
    } finally {
      checkingStatus.value = false;
    }
  };

  const startHealthCheck = () => {
    // Initial check
    checkBackendStatus();

    // Periodic health check (every 30 seconds)
    if (healthCheckInterval === null) {
      healthCheckInterval = window.setInterval(checkBackendStatus, 30000);
    }
  };

  const stopHealthCheck = () => {
    if (healthCheckInterval !== null) {
      clearInterval(healthCheckInterval);
      healthCheckInterval = null;
    }
  };

  return {
    backendConnected,
    backendDegraded,
    checkingStatus,
    pluginFailureCount,
    checkBackendStatus,
    startHealthCheck,
    stopHealthCheck,
  };
}
