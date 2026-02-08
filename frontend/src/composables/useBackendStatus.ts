import { ref, onMounted, onBeforeUnmount } from 'vue';
import api from '@/api/client';

const backendConnected = ref(true);
const checkingStatus = ref(false);
let healthCheckInterval: number | null = null;

export function useBackendStatus() {
  const checkBackendStatus = async () => {
    checkingStatus.value = true;
    try {
      await api.get("/health", { timeout: 3000 });
      backendConnected.value = true;
      console.log("[BackendStatus] Backend connection established");
    } catch (error) {
      backendConnected.value = false;
      console.error("[BackendStatus] Backend unreachable:", error);
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
