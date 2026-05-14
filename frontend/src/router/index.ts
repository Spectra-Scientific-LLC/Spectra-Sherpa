import { createRouter, createWebHistory, type RouteLocation } from "vue-router";

import { useAppConfig } from "@/composables/useAppConfig";
import { useAuthStore } from "@/stores/auth";

// OSS owns the core routes. Managed-auth routes (/login, /register,
// /admin) are contributed dynamically at boot by the server-provided
// modules (`/ui/auth.js`, `/ui/admin.js`). In local mode and in
// hybrid-without-server, those routes are simply unregistered —
// navigating to them falls through to the SPA catchall / 404 view.

const routes = [
  { path: "/", redirect: "/project" },

  // --- 6 main pages (chemometrician workflow) ---
  {
    path: "/project",
    component: () => import("@/views/project/ProjectContent.vue"),
    meta: { nav: "project" },
  },
  {
    // R9 — Memory Map view.  Standalone (no nav highlight) because
    // the entry is the "Memory Map" button on Project Details, not a
    // top-level tab.  Local mode renders an empty/upgrade state because
    // ``LocalAdvisorMemoryAdapter.getMemoryMap`` returns null.
    path: "/project/memory-map",
    component: () => import("@/views/project/MemoryMapView.vue"),
    meta: { standalone: true },
  },
  {
    path: "/data",
    component: () => import("@/views/data/DataContent.vue"),
    meta: { nav: "data" },
  },
  {
    path: "/workflow",
    component: () => import("@/views/workflow-builder/WorkflowBuilderContent.vue"),
    meta: { nav: "workflow" },
  },
  {
    path: "/workflow/node/:nodeId",
    component: () => import("@/views/workflow-builder/NodeDetailView.vue"),
    meta: { standalone: true },
  },
  {
    path: "/experiments",
    component: () => import("@/views/experiments/ExperimentsContent.vue"),
    meta: { nav: "experiments" },
  },
  {
    path: "/deploy",
    component: () => import("@/views/deploy/DeployContent.vue"),
    meta: { nav: "deploy" },
  },
  {
    path: "/report",
    component: () => import("@/views/report/ReportContent.vue"),
    meta: { nav: "report" },
  },
  {
    path: "/audit",
    component: () => import("@/views/audit/AuditContent.vue"),
    meta: { nav: "audit" },
  },

  // --- System pages ---
  { path: "/settings", component: () => import("@/views/settings/SettingsContent.vue") },
  { path: "/documentation", component: () => import("@/views/DocumentationView.vue") },
  { path: "/logs", component: () => import("@/views/LogsView.vue") },
  {
    path: "/llm-chat",
    component: () => import("@/views/LlmChatView.vue"),
    meta: { standalone: true },
  },

  // --- Legacy redirects ---
  { path: "/workspace", redirect: "/project" },
  { path: "/workspace/node/:nodeId", redirect: (to: RouteLocation) => `/workflow/node/${to.params.nodeId}` },
  { path: "/operations/:rest(.*)", redirect: "/workflow" },
  { path: "/templates", redirect: "/project" },
  { path: "/workflows/:pathMatch(.*)*", redirect: "/workflow" },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore();
  const { config, loadConfig, appMode } = useAppConfig();

  // Ensure config is loaded (needed for mode check). Fail closed: if
  // config is unavailable we cannot tell what mode we're in, so treat
  // the user as unauthenticated.
  if (!config.value) {
    const loaded = await loadConfig();
    if (!loaded) {
      if (to.path === "/login") {
        return next();
      }
      return next("/login");
    }
  }

  // Local mode: bypass all authentication (single-user desktop).
  if (appMode.value === "local") {
    if (authStore.token || localStorage.getItem("token")) {
      authStore.clearCredentials();
    }
    return next();
  }

  // Hybrid mode: loopback clients get implicit local identity via
  // /auth/me. Remote clients fall through to the server-registered
  // login route if it exists.
  if (appMode.value === "hybrid") {
    if (!authStore.user && !authStore.isAuthenticated) {
      await authStore.initHybridUser();
    }
    if (authStore.user) {
      return next();
    }
  }

  // Public / auth routes are added dynamically by the server module.
  // If we got here and the path has the `public` meta flag, allow
  // through; if the user is not authenticated, redirect to /login
  // (either the server-registered route, or the SPA catchall when no
  // server module has registered it — fail-closed behavior).
  if (to.meta.public) {
    if (authStore.isAuthenticated && (to.path === "/login" || to.path === "/register")) {
      return next("/");
    }
    return next();
  }

  if (!authStore.isAuthenticated) {
    // If the user is already trying to reach /login (either because the
    // server auth module has registered that route, or because this is
    // the fail-closed state where no server module has registered),
    // don't redirect again — let the navigation complete. The server
    // module handles the rest; if it's absent, the SPA catchall shows
    // the fail-closed error view.
    if (to.path === "/login" || to.path === "/register") {
      return next();
    }
    return next("/login");
  }

  // Admin route guard (only fires when the server's admin module has
  // registered /admin): require capabilities.admin.
  if (to.meta.requiresAdmin && !authStore.user?.capabilities?.admin) {
    return next("/");
  }

  next();
});

export default router;
