import { ref } from 'vue';
import api from '@/api/client';

const backendConnected = ref(true);
const checkingStatus = ref(false);
let healthCheckInterval: number | null = null;

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function probeHealth(): Promise<boolean> {
  try {
    await api.get("/health", { timeout: 3000 });
    return true;
  } catch {
    return false;
  }
}

export function useBackendStatus() {
  const checkBackendStatus = async () => {
    checkingStatus.value = true;
    try {
      if (await probeHealth()) {
        backendConnected.value = true;
        console.log("[BackendStatus] Backend connection established");
        return;
      }

      // First attempt failed — retry up to MAX_RETRIES times before reporting
      for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        await sleep(RETRY_DELAY_MS);
        if (await probeHealth()) {
          backendConnected.value = true;
          console.log(`[BackendStatus] Backend recovered on retry ${attempt}`);
          return;
        }
      }

      // All retries exhausted
      backendConnected.value = false;
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
    checkingStatus,
    checkBackendStatus,
    startHealthCheck,
    stopHealthCheck,
  };
}
