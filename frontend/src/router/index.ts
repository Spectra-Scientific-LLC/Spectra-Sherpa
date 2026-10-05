import { createRouter, createWebHistory, type RouteLocation } from "vue-router";

import { useAppConfig } from "@/composables/useAppConfig";
import { useAuthStore } from "@/stores/auth";

// OSS owns the core routes. Managed-auth routes (/login, /register,
// /admin) are contributed dynamically at boot by the server-provided
// modules (`/ui/auth.js`, `/ui/admin.js`). An unregistered managed-auth
// URL is never public: the guard below redirects it to `/login` rather than
// allowing the unauthenticated application shell to render.

const routes = [
  { path: "/", redirect: "/dashboard" },

  // --- Main pages (chemometrician workflow) ---
  // The V2 designs were adopted as canonical. The /dashboard route serves
  // the former "Dashboard V2" (SimplifiedDashboard.vue); /project serves
  // the redesigned ProjectContent.vue. Legacy /dashboard-v2 and /project-v2
  // paths are kept as redirects so existing bookmarks / in-app links don't
  // break — they collapse to the canonical routes.
  {
    path: "/dashboard",
    component: () => import("@/views/dashboard/SimplifiedDashboard.vue"),
    meta: { nav: "dashboard" },
  },
  { path: "/dashboard-v2", redirect: "/dashboard" },
  {
    path: "/project",
    component: () => import("@/views/project/ProjectContent.vue"),
    meta: { nav: "project" },
  },
  { path: "/project-v2", redirect: "/project" },
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
    path: "/project/provenance",
    component: () => import("@/views/project/ProjectProvenanceView.vue"),
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
    path: "/runs",
    component: () => import("@/views/models/ModelsContent.vue"),
    meta: { nav: "runs" },
  },
  {
    path: "/runs/:runId",
    component: () => import("@/views/models/ModelsContent.vue"),
    meta: { nav: "runs" },
  },
  { path: "/models", redirect: (to: RouteLocation) => ({ path: "/runs", query: { ...to.query, tab: "models" } }) },
  {
    path: "/workflow/node/:nodeId",
    component: () => import("@/views/workflow-builder/NodeDetailView.vue"),
    meta: { standalone: true },
  },
  { path: "/experiments", redirect: "/runs" },
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
  { path: "/workspace", redirect: "/dashboard" },
  {
    path: "/workspace/node/:nodeId",
    redirect: (to: RouteLocation) => `/workflow/node/${to.params.nodeId}`,
  },
  { path: "/operations/:rest(.*)", redirect: "/workflow" },
  { path: "/templates", redirect: "/dashboard" },
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

  // Explicit product policy: loopback clients get implicit local identity via
  // /auth/me. Remote clients fall through to the server-registered
  // login route if it exists.
  if (config.value?.implicitIdentity === true) {
    if (!authStore.user && !authStore.isAuthenticated) {
      await authStore.initializeActor();
    }
    if (authStore.user) {
      return next();
    }
  }

  // Public / auth routes are added dynamically by the server module. Only a
  // route that actually carries the `public` meta authority is public.
  if (to.meta.public) {
    if (authStore.isAuthenticated && (to.path === "/login" || to.path === "/register")) {
      return next("/");
    }
    return next();
  }

  if (!authStore.isAuthenticated) {
    // `/login` may be the initial unmatched navigation while the managed auth
    // module registers it at boot. Allow it to avoid a redirect loop. In
    // contrast, `/register` must have been registered with `meta.public`; an
    // unregistered `/register` means the deployment closed registration and
    // must redirect to Login instead of rendering the app shell.
    if (to.path === "/login") {
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
