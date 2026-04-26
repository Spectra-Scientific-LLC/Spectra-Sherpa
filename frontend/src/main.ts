import * as Vue from "vue";
import { createApp } from "vue";
import * as VueRouter from "vue-router";
import * as Pinia from "pinia";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import Tooltip from "primevue/tooltip";

// Server-provided frontend modules import individual primevue
// components via `primevue/<name>` paths. Those paths resolve via
// `<script type="importmap">` in index.html to per-component shims
// under /vendor/primevue/, which read from window.__OSS_VENDOR__
// .primevue.<name> — populated below. Keep this list in sync with
// whatever paths the server-provided auth/admin modules import; if a
// server module imports a new primevue path, add it here AND add a
// corresponding shim file at frontend/public/vendor/primevue/.
import * as pvButton from "primevue/button";
import * as pvCard from "primevue/card";
import * as pvCheckbox from "primevue/checkbox";
import * as pvColumn from "primevue/column";
import * as pvDatatable from "primevue/datatable";
import * as pvDialog from "primevue/dialog";
import * as pvInputtext from "primevue/inputtext";
import * as pvMessage from "primevue/message";
import * as pvPassword from "primevue/password";
import * as pvProgressbar from "primevue/progressbar";
import * as pvTabpanel from "primevue/tabpanel";
import * as pvTabview from "primevue/tabview";
import * as pvTag from "primevue/tag";
import * as pvUsetoast from "primevue/usetoast";

import App from "./App.vue";
import router from "./router";
import { useWorkflowStore } from "./stores/workflow";
import { buildWsUrl } from "./utils/ws";

import "primevue/resources/themes/lara-light-blue/theme.css";
import "primevue/resources/primevue.min.css";
import "primeicons/primeicons.css";
import "./assets/main.css";

// Expose bundled Vue/Vue-Router/Pinia/primevue on globalThis so the
// thin shims in /vendor/*.js can re-export them for server-provided
// modules (/ui/auth.js, /ui/admin.js). MUST happen before any dynamic
// import("/ui/*.js") fires.
declare global {
  interface Window {
    __OSS_VENDOR__?: {
      vue?: typeof Vue;
      vueRouter?: typeof VueRouter;
      pinia?: typeof Pinia;
      primevue?: Record<string, unknown>;
    };
  }
}
window.__OSS_VENDOR__ = {
  vue: Vue,
  vueRouter: VueRouter,
  pinia: Pinia,
  primevue: {
    button: pvButton,
    card: pvCard,
    checkbox: pvCheckbox,
    column: pvColumn,
    datatable: pvDatatable,
    dialog: pvDialog,
    inputtext: pvInputtext,
    message: pvMessage,
    password: pvPassword,
    progressbar: pvProgressbar,
    tabpanel: pvTabpanel,
    tabview: pvTabview,
    tag: pvTag,
    usetoast: pvUsetoast,
  },
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

// Self-heal stale tabs after a deploy. Vite emits hash-named JS chunks
// under /assets/<file>-<hash>.js that the SPA lazy-loads via
// `() => import(...)`. After a frontend rebuild, the old chunk hashes
// no longer exist on the server; nginx falls back to /index.html
// (text/html) for the missing path; the browser receives HTML for what
// the running JS asked for as a JS module → router throws
// "Failed to fetch dynamically imported module".
//
// On that specific error class, reload the page once (guarded by
// sessionStorage so a genuine bug can't trap the user in a refresh
// loop). Reload pulls the current /index.html with current chunk
// hashes; the deploy mismatch is gone.
const CHUNK_RELOAD_FLAG = "__spectra_chunk_reload";
router.onError((err) => {
  const msg = err instanceof Error ? err.message : String(err);
  const isChunkError =
    /Failed to fetch dynamically imported module/i.test(msg) ||
    /Importing a module script failed/i.test(msg) ||
    /Loading chunk \S+ failed/i.test(msg);
  if (!isChunkError) return;
  if (sessionStorage.getItem(CHUNK_RELOAD_FLAG)) {
    // Already reloaded once this session and still failing — surface
    // the error rather than loop. Likely a genuine deployment problem.
    console.error("[Spectra] Chunk load error after reload; not retrying:", err);
    return;
  }
  sessionStorage.setItem(CHUNK_RELOAD_FLAG, "1");
  console.warn(
    "[Spectra] Detected stale chunk reference (likely after a deploy); reloading once.",
    err,
  );
  window.location.reload();
});

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

// Load server-provided frontend modules (auth, admin) BEFORE mount so
// the first navigation sees any routes they register. This is async
// but the await is bounded (one config fetch + one or two dynamic
// imports); failure is fail-closed (console error + reactive flag
// consumed by the fail-closed UI in Phase 1b commit 5).
import { bootServerModules } from "./boot/serverModules";

void (async () => {
  try {
    await bootServerModules(router);
  } catch (err) {
    console.error("[Spectra] server-module bootstrap threw:", err);
  }
  app.mount("#app");
})();

// Cleanup on HMR to prevent stacked intervals and leaked listeners
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (disposeWorkflowMetadataRefresh) {
      disposeWorkflowMetadataRefresh();
      disposeWorkflowMetadataRefresh = null;
    }
  });
}
