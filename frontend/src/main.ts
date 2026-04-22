import * as Vue from "vue";
import { createApp } from "vue";
import * as VueRouter from "vue-router";
import * as Pinia from "pinia";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import Tooltip from "primevue/tooltip";

import App from "./App.vue";
import router from "./router";
import { useWorkflowStore } from "./stores/workflow";
import { buildWsUrl } from "./utils/ws";

import "primevue/resources/themes/lara-light-blue/theme.css";
import "primevue/resources/primevue.min.css";
import "primeicons/primeicons.css";
import "./assets/main.css";

// Expose bundled Vue/Vue-Router/Pinia on globalThis so the thin shims
// in /vendor/*.js can re-export them for server-provided modules
// (/ui/auth.js, /ui/admin.js). MUST happen before any dynamic
// import("/ui/*.js") fires.
//
// PrimeVue components are registered lazily from the bundle the
// server module itself provides, so no primevue shim is populated
// here — the module handles its own component imports against the
// /vendor/primevue/* import-map prefix.
declare global {
  interface Window {
    __OSS_VENDOR__?: {
      vue?: typeof Vue;
      vueRouter?: typeof VueRouter;
      pinia?: typeof Pinia;
    };
  }
}
window.__OSS_VENDOR__ = {
  vue: Vue,
  vueRouter: VueRouter,
  pinia: Pinia,
};

const app = createApp(App);

// Global error boundary — catches unhandled errors in component lifecycle hooks,
// watchers, and render functions.  Without this, async errors silently swallow
// stack traces in production and leave the UI in an unknown state.
app.config.errorHandler = (err, _instance, info) => {
  console.error("[Spectra] Unhandled Vue error —", info, err);
  // In development, re-throw so Vue DevTools shows the overlay.
  if (import.meta.env.DEV) {
    throw err;
  }
};

if (import.meta.env.DEV) {
  const apiBase =
    import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api/v1";
  const defaultApiKey = import.meta.env.VITE_DEFAULT_API_KEY as
    | string
    | undefined;
  if (defaultApiKey && localStorage.getItem("api_key") !== defaultApiKey) {
    localStorage.setItem("api_key", defaultApiKey);
  }
  console.info("[Spectra] Frontend origin:", window.location.origin);
  console.info("[Spectra] API base:", apiBase);
  console.info("[Spectra] WS base:", buildWsUrl());
  console.info(
    "[Spectra] API key set:",
    localStorage.getItem("api_key") ? "yes" : "no"
  );
}

const pinia = createPinia();
app.use(pinia);
app.use(router);
app.use(PrimeVue);
app.use(ToastService);
app.directive("tooltip", Tooltip);

let disposeWorkflowMetadataRefresh: (() => void) | null = null;

const initWorkflowMetadataRefresh = async () => {
  const workflowStore = useWorkflowStore();

  // Skip initial fetch when not authenticated (enterprise/hybrid mode).
  // The node library will be fetched once the user logs in and views load.
  const token = localStorage.getItem("token");
  const apiKey = localStorage.getItem("api_key");
  if (!token && !apiKey) {
    // No credentials — defer until after login to avoid 401 spam.
    return;
  }

  // Initialize workflow store and fetch node library metadata.
  // This provides validation schemas and parameter definitions from backend.
  await workflowStore.fetchNodeLibrary().catch((err) => {
    console.error("[main.ts] Failed to fetch node library:", err);
  });

  // Auto-refresh node library when page becomes visible (e.g., after backend restart).
  // This prevents stale cache issues without requiring manual browser refresh.
  const onVisibilityChange = () => {
    if (!document.hidden) {
      workflowStore.checkAndRefreshNodeLibrary().catch((err) => {
        console.debug("[main.ts] Background version check failed:", err);
      });
    }
  };
  document.addEventListener("visibilitychange", onVisibilityChange);

  // Also check periodically (every 30 seconds) while page is visible.
  const versionCheckInterval = window.setInterval(() => {
    if (!document.hidden) {
      workflowStore.checkAndRefreshNodeLibrary().catch((err) => {
        console.debug("[main.ts] Background version check failed:", err);
      });
    }
  }, 30000);

  disposeWorkflowMetadataRefresh = () => {
    clearInterval(versionCheckInterval);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
};

void initWorkflowMetadataRefresh();

app.mount("#app");

// Cleanup on HMR to prevent stacked intervals and leaked listeners
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (disposeWorkflowMetadataRefresh) {
      disposeWorkflowMetadataRefresh();
      disposeWorkflowMetadataRefresh = null;
    }
  });
}
