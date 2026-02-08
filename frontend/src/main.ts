import { createApp } from "vue";
import { createPinia } from "pinia";
import PrimeVue from "primevue/config";
import ToastService from "primevue/toastservice";
import Tooltip from "primevue/tooltip";

import App from "./App.vue";
import router from "./router";
import { buildWsUrl } from "./utils/ws";
import { useWorkflowStore } from "./stores/workflow";

import "primevue/resources/themes/lara-light-blue/theme.css";
import "primevue/resources/primevue.min.css";
import "primeicons/primeicons.css";
import "./assets/main.css";

const app = createApp(App);

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

// Initialize workflow store and fetch node library metadata
// This provides validation schemas and parameter definitions from backend
const workflowStore = useWorkflowStore();
workflowStore.fetchNodeLibrary().catch((err) => {
  console.error("[main.ts] Failed to fetch node library:", err);
});

// Auto-refresh node library when page becomes visible (e.g., after backend restart)
// This prevents stale cache issues without requiring manual browser refresh
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    console.log("[main.ts] Page visible, checking for backend updates...");
    workflowStore.checkAndRefreshNodeLibrary().catch((err) => {
      console.debug("[main.ts] Background version check failed:", err);
    });
  }
});

// Also check periodically (every 30 seconds) while page is visible
let versionCheckInterval: number | undefined;
versionCheckInterval = window.setInterval(() => {
  if (!document.hidden) {
    workflowStore.checkAndRefreshNodeLibrary().catch((err) => {
      console.debug("[main.ts] Background version check failed:", err);
    });
  }
}, 30000);

app.mount("#app");
