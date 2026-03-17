import { createRouter, createWebHistory, type RouteLocation } from "vue-router";

import { useAuthStore } from "@/stores/auth";
import { useAppConfig } from "@/composables/useAppConfig";

const routes = [
  { path: "/login", component: () => import("@/views/LoginView.vue"), meta: { public: true } },
  { path: "/register", component: () => import("@/views/RegisterView.vue"), meta: { public: true } },
  { path: "/", redirect: "/project" },

  // --- 6 main pages (chemometrician workflow) ---
  {
    path: "/project",
    component: () => import("@/views/project/ProjectContent.vue"),
    meta: { nav: "project" }
  },
  {
    path: "/data",
    component: () => import("@/views/data/DataContent.vue"),
    meta: { nav: "data" }
  },
  {
    path: "/workflow",
    component: () => import("@/views/workflow-builder/WorkflowBuilderContent.vue"),
    meta: { nav: "workflow" }
  },
  {
    path: "/workflow/node/:nodeId",
    component: () => import("@/views/workflow-builder/NodeDetailView.vue"),
    meta: { standalone: true }
  },
  {
    path: "/experiments",
    component: () => import("@/views/experiments/ExperimentsContent.vue"),
    meta: { nav: "experiments" }
  },
  {
    path: "/deploy",
    component: () => import("@/views/deploy/DeployContent.vue"),
    meta: { nav: "deploy" }
  },
  {
    path: "/report",
    component: () => import("@/views/report/ReportContent.vue"),
    meta: { nav: "report" }
  },

  // --- System pages ---
  { path: "/settings", component: () => import("@/views/settings/SettingsContent.vue") },
  { path: "/logs", component: () => import("@/views/LogsView.vue") },
  {
    path: "/llm-chat",
    component: () => import("@/views/LlmChatView.vue"),
    meta: { standalone: true }
  },
  {
    path: "/admin",
    component: () => import("@/views/AdminView.vue"),
    meta: { requiresAdmin: true }
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
  routes
});

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const { config, loadConfig, appMode, registrationEnabled } = useAppConfig()

  // Ensure config is loaded (needed for mode check)
  if (!config.value) {
    const loaded = await loadConfig()
    if (!loaded) {
      if (to.meta.public) {
        return next()
      }
      return next('/login')
    }
  }

  // Block registration route whenever backend doesn't support it.
  if (to.path === '/register' && !registrationEnabled.value) {
    return next((appMode.value === 'local' || authStore.isAuthenticated) ? '/' : '/login')
  }

  // Local mode: bypass all authentication (single-user, no login needed)
  if (appMode.value === 'local') {
    // Clear stale credentials from prior enterprise/hybrid usage
    if (authStore.token || localStorage.getItem('token')) {
      authStore.clearCredentials()
    }
    if (to.path === '/login' || to.path === '/register') {
      return next('/')
    }
    return next()
  }

  // Hybrid mode: loopback clients skip login, remote clients need JWT.
  // initHybridUser() calls /auth/me without a token — succeeds for
  // loopback (middleware exempts 127.0.0.1) but 401s for remote clients.
  if (appMode.value === 'hybrid') {
    if (!authStore.user && !authStore.isAuthenticated) {
      await authStore.initHybridUser()
    }
    if (authStore.user) {
      // Loopback or already authenticated — no login needed
      if (to.path === '/login') {
        return next('/')
      }
      return next()
    }
    // Remote client: fall through to normal auth check below
  }

  // Public pages (non-local modes)
  if (to.meta.public) {
    if (authStore.isAuthenticated && (to.path === '/login' || to.path === '/register')) {
      return next('/')
    }
    return next()
  }

  // Protected pages (non-local modes)
  if (!authStore.isAuthenticated) {
    return next('/login')
  }

  // Admin pages (requires superuser in enterprise mode)
  if (to.meta.requiresAdmin) {
    if (!authStore.user?.is_superuser) {
      return next('/')
    }
  }

  next()
})

export default router;
