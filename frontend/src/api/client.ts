import axios from "axios";
import { isDemoUpgradeError, getDemoUpgradeInfo } from "@/utils/errors";

// Use relative URL in production (nginx proxies to backend)
// Use absolute URL in development for Vite dev server
const defaultBaseUrl = import.meta.env.DEV
  ? "http://127.0.0.1:8000/api/v1"
  : "/api/v1";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultBaseUrl,
});

/**
 * Request interceptor to add authentication headers.
 *
 * Supports two auth mechanisms:
 * 1. JWT Bearer token (for user login in cloud/enterprise modes)
 * 2. X-API-Key (for machine-to-machine in hybrid mode)
 *
 * JWT takes precedence if both are present.
 */
api.interceptors.request.use((config) => {
  config.headers = config.headers || {};

  // Check for JWT token first (user login auth)
  const token = localStorage.getItem("token");
  if (token) {
    config.headers["Authorization"] = `Bearer ${token}`;
  }

  // Also add API key if present (for hybrid mode M2M auth)
  const apiKey = localStorage.getItem("api_key");
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }

  return config;
});

/**
 * Response interceptor to handle session expiry and demo upgrade prompts.
 *
 * - 403/429 with upgrade_url: demo mode capability block or rate limit.
 *   Triggers the upgrade modal via useDemoMode composable.
 * - 401: expired JWT — clear credentials and redirect to login.
 */
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Demo mode: 403 (capability blocked) or 429 (execution limit)
    if (isDemoUpgradeError(error)) {
      const info = getDemoUpgradeInfo(error);
      if (info) {
        // Lazy import to avoid circular dependency
        import("@/composables/useDemoMode").then(({ useDemoMode }) => {
          const { triggerUpgradeModal, updateFromRateLimit } = useDemoMode();
          triggerUpgradeModal({
            message: info.message,
            upgradeUrl: info.upgradeUrl,
            availablePlans: info.availablePlans,
            blockedCapability: info.blockedCapability,
          });
          // Update quota counter for 429 responses
          if (error.response?.status === 429) {
            const data = error.response?.data;
            updateFromRateLimit(data?.remaining ?? 0, data?.limit ?? 25);
          }
        });
      }
      return Promise.reject(error);
    }

    if (error.response?.status === 401) {
      const path = window.location.pathname;
      // Don't redirect if on login or register page (avoid loop / breaking registration UX)
      if (!path.startsWith("/login") && !path.startsWith("/register")) {
        localStorage.removeItem("token");
        localStorage.removeItem("api_key");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;
