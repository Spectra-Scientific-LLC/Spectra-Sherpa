import axios, { type AxiosError } from "axios";
import { updateDemoQuotaFromRateLimit } from "@/composables/demoModeState";
import { useNotifier } from "@/composables/useNotifier";
import { isDemoUpgradeError } from "@/utils/errors";

// Use relative URL in production (nginx proxies to backend)
// Use absolute URL in development for Vite dev server
const defaultBaseUrl = import.meta.env.DEV
  ? "http://127.0.0.1:8000/api/v1"
  : "/api/v1";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultBaseUrl,
});

// Async endpoints polled or updated in the background.
const ASYNC_ERROR_PATH_HINTS = [
  "/jobs",
  "/deploy/runs",
  "/deploy/workflows",
  "/experiments",
  "/execute",
  "/models",
  "/predict",
  "/llm",
];
const ASYNC_ERROR_DEDUPE_WINDOW_MS = 15000;
const asyncErrorDedup = new Map<string, number>();

function normalizeUrlPath(rawUrl: string | undefined): string {
  if (!rawUrl) return "";
  try {
    if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) {
      return new URL(rawUrl).pathname;
    }
  } catch {
    return rawUrl;
  }
  return rawUrl;
}

function isAsyncErrorCandidate(error: AxiosError): boolean {
  const path = normalizeUrlPath(error.config?.url);
  if (!path) return false;
  return ASYNC_ERROR_PATH_HINTS.some((prefix) => path.startsWith(prefix));
}

function formatAsyncErrorMessage(error: AxiosError): string {
  const path = normalizeUrlPath(error.config?.url);
  if (!error.response) {
    return `Network error while syncing ${path || "background API"}.`;
  }
  return `Background request failed (${error.response.status}) on ${path || "API"}.`;
}

function dedupeAsyncError(path: string, status: number): boolean {
  const now = Date.now();
  const key = `${path}::${status}`;
  const last = asyncErrorDedup.get(key);
  if (last && now - last < ASYNC_ERROR_DEDUPE_WINDOW_MS) {
    return true;
  }
  asyncErrorDedup.set(key, now);
  return false;
}

function emitAsyncApiErrorNotification(error: AxiosError): void {
  const path = normalizeUrlPath(error.config?.url) || "background API";
  const status = error.response?.status ?? 0;

  if (dedupeAsyncError(path, status)) {
    return;
  }

  // Build extended detail from response body
  let extendedDetail: string | undefined;
  if (error.response?.data) {
    try {
      extendedDetail =
        typeof error.response.data === "string"
          ? error.response.data
          : JSON.stringify(error.response.data, null, 2);
    } catch {
      extendedDetail = undefined;
    }
  }

  const { notifyDeployOutcome, notifySystemEvent } = useNotifier();
  const message = formatAsyncErrorMessage(error);
  if (path.startsWith("/deploy/")) {
    notifyDeployOutcome({ success: false, message });
    return;
  }
  notifySystemEvent({
    severity: "error",
    title: "Background Sync Error",
    message,
    detail: extendedDetail,
  });
}

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
 * - Async background API failures (/jobs, /deploy/runs, /deploy/workflows):
 *   emit notification center events (toasts remain unchanged in calling views).
 * - 401: expired JWT — clear credentials and redirect to login.
 */
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Demo mode: 429 (execution limit) — update banner quota counter.
    // Demo mode: rate-limit response — update quota counter for DemoUpgradeModal.
    if (isDemoUpgradeError(error) && error.response?.status === 429) {
      const data = error.response?.data;
      updateDemoQuotaFromRateLimit(data?.remaining ?? 0, data?.limit ?? 25);
      return Promise.reject(error);
    }

    if (axios.isAxiosError(error) && isAsyncErrorCandidate(error)) {
      const status = error.response?.status ?? 0;
      const shouldNotify =
        status === 0 || status >= 500 || (status === 404 && normalizeUrlPath(error.config?.url).startsWith("/jobs"));
      if (shouldNotify) {
        emitAsyncApiErrorNotification(error);
      }
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
