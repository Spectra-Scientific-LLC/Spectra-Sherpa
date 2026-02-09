import { createRouter, createWebHistory } from "vue-router";

import MainContentView from "@/views/MainContentView.vue";
import LogsView from "@/views/LogsView.vue";
import NodeDetailView from "@/views/workflow-builder/NodeDetailView.vue";
import LlmChatView from "@/views/LlmChatView.vue";
import LoginView from "@/views/LoginView.vue";
import { useAuthStore } from "@/stores/auth";
import { useAppConfig } from "@/composables/useAppConfig";

const routes = [
  // Workspace is the main hub
  { path: "/login", component: LoginView, meta: { public: true } },
  { path: "/", redirect: "/workspace" },

  // Workspace (unified workflow canvas - the hub)
  {
    path: "/workspace",
    component: MainContentView,
    meta: { mainTab: "workspace", subTab: "workspace" }
  },

  // Node detail view (opens in new tab for full inspection)
  {
    path: "/workspace/node/:nodeId",
    component: NodeDetailView,
    meta: { standalone: true }
  },

  // Operations section
  {
    path: "/operations",
    redirect: "/operations/calibration"
  },
  {
    path: "/operations/:subTab(calibration|process|analysis)",
    component: MainContentView,
    meta: { mainTab: "operations" }
  },

  // Templates
  {
    path: "/templates",
    component: MainContentView,
    meta: { mainTab: "templates", subTab: "templates" }
  },

  // Settings is separate (accessed via icon/menu)
  { path: "/settings", component: () => import("../views/settings/SettingsContent.vue") },
  { path: "/logs", component: LogsView },

  // Full-screen LLM Chat view
  {
    path: "/llm-chat",
    component: LlmChatView,
    meta: { standalone: true }
  },

  // Admin Dashboard
  {
    path: "/admin",
    component: () => import("@/views/AdminView.vue"),
    meta: { requiresAdmin: true }
  },

  // Legacy redirects for bookmarks/old links
  { path: "/data/:pathMatch(.*)*", redirect: "/workspace" },
  { path: "/workflows/:pathMatch(.*)*", redirect: "/workspace" }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const { config, loadConfig, appMode } = useAppConfig()

  // Ensure config is loaded (needed for mode check)
  if (!config.value) {
    await loadConfig()
  }

  // Local mode: bypass all authentication (single-user, no login needed)
  if (appMode.value === 'local') {
    // Clear stale credentials from prior demo/hybrid usage
    if (authStore.token || localStorage.getItem('token')) {
      authStore.clearCredentials()
    }
    if (to.path === '/login') {
      return next('/')
    }
    return next()
  }

  // Hybrid mode: no login needed, but fetch user profile for admin/identity
  if (appMode.value === 'hybrid') {
    if (!authStore.user) {
      await authStore.initHybridUser()
    }
    if (to.path === '/login') {
      return next('/')
    }
    return next()
  }

  // Public pages (non-local modes)
  if (to.meta.public) {
    if (authStore.isAuthenticated && to.path === '/login') {
      return next('/')
    }
    return next()
  }

  // Protected pages (non-local modes)
  if (!authStore.isAuthenticated) {
    return next('/login')
  }

  // Admin pages (requires superuser in demo mode)
  if (to.meta.requiresAdmin) {
    if (!authStore.user?.is_superuser) {
      return next('/')
    }
  }

  next()
})

export default router;
