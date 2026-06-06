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

// Exact ``/projects/{id}`` (no trailing path) — these requests target the
// project resource itself, so a 404 means the project the SPA still
// considers "active" no longer exists server-side (deleted in another tab,
// demo-mode GC, etc.). A 404 on a NESTED route (``/projects/{id}/foo``)
// means the parent exists but the child doesn't — that's a different
// failure mode and we leave it to the calling view.
const PROJECT_RESOURCE_PATH = /^\/projects\/(\d+)\/?$/;

function activeProjectIdFromPath(path: string): number | null {
  const match = PROJECT_RESOURCE_PATH.exec(path);
  if (!match) return null;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

async function handleActiveProjectGone(projectId: number): Promise<void> {
  // Lazy-load the project store so this module stays import-cycle-free
  // (the project store, in turn, never imports api/client at module
  // load time, but the indirection keeps that invariant explicit).
  const { useProjectStore } = await import("@/stores/project");
  const projectStore = useProjectStore();
  if (projectStore.currentProjectId !== projectId) {
    return; // Stale 404 for a project the user already moved away from.
  }
  projectStore.currentProjectId = null;
  projectStore.currentProject = null;
  // Best-effort UX recovery: pull the user to the dashboard so the
  // sidebar stops pointing at a phantom project. The dashboard route
  // re-runs project list fetching on mount.
  if (typeof window !== "undefined") {
    const path = window.location.pathname;
    if (path !== "/dashboard" && path !== "/login") {
      window.location.href = "/dashboard";
    }
  }
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
    // Demo mode: 429 (execution / sherpa rate limit) — refresh banner
    // limit refs from the structured detail (limit_type, limit_per_hour,
    // limit_per_day, remaining). Old payloads with just `{remaining,
    // limit}` are tolerated — they just don't update anything because
    // the new function only reacts to limit_per_hour / limit_per_day.
    if (isDemoUpgradeError(error) && error.response?.status === 429) {
      const data = error.response?.data ?? {};
      const detail = typeof data.detail === "object" && data.detail !== null ? data.detail : data;
      updateDemoQuotaFromRateLimit(detail);
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

    // Active-project gone (404 on the project resource itself). Demo droplets
    // GC stale projects, and another browser tab can delete the active
    // project out from under us. Without this, the SPA keeps a phantom
    // currentProjectId, and every subsequent call into that project 404s
    // silently until the user reloads.
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      const id = activeProjectIdFromPath(normalizeUrlPath(error.config?.url));
      if (id !== null) {
        // Fire and forget — we don't want to block the rejection chain on
        // the dynamic import or the navigation.
        void handleActiveProjectGone(id);
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
