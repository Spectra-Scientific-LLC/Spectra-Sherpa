/**
 * Boot-time loader for server-provided frontend modules.
 *
 * The monorepo's commercial server ships two ES modules at runtime:
 *
 *   /ui/auth.js   — LoginView, RegisterView, server-backed auth
 *                   methods, /login + /register route registration,
 *                   user-menu contributions. Loaded eagerly when
 *                   `features.authUI` is true (server-backed modes).
 *   /ui/admin.js  — AdminView, /admin route registration. Loaded
 *                   lazily once user identity resolves and
 *                   `user.capabilities.admin === true`.
 *
 * Each module exports a single `register(ctx)` function. This loader
 * calls it with a live host context built from the OSS router, auth
 * store, menu-extension composable, and resolved AppConfig.
 *
 * Fail-closed: any fetch/register error is logged and surfaced on a
 * module-local `serverModuleLoadFailed` ref so the SPA shell can render
 * a fail-closed view. (The visible error UI lands in Phase 1b commit 5.)
 *
 * Cross-bundle runtime: the server modules import `vue`, `vue-router`,
 * `pinia`, and `primevue/*` as Vite externals. They resolve via the
 * `<script type="importmap">` in index.html, which points at the
 * `/vendor/*.js` shims. Those shims read from `window.__OSS_VENDOR__`,
 * populated in main.ts BEFORE this bootstrap runs.
 */
import { ref, watch } from "vue";
import type { Router, RouteRecordRaw } from "vue-router";

import { useAppConfig } from "@/composables/useAppConfig";
import {
  useTopbarMenu,
  type TopbarMenuItem,
} from "@/composables/useTopbarMenu";
import { useAuthStore } from "@/stores/auth";

export const serverModuleLoadFailed = ref<null | {
  module: string;
  error: unknown;
}>(null);

/**
 * Re-export the shape that server modules expect — keep this in sync
 * with `packages/spectra-server/frontend/src/types/context.ts`.
 */
interface HostContext {
  router: Router;
  authStore: ReturnType<typeof useAuthStore>;
  topbarMenu: {
    addItems(items: TopbarMenuItem[], contributorId?: string): void;
    removeItems(contributorId: string): void;
  };
  appConfig: Record<string, unknown>;
  contributorId: string;
  addRoute(route: RouteRecordRaw): void;
}

interface ServerModule {
  register?: (ctx: HostContext) => void | Promise<void>;
  default?: (ctx: HostContext) => void | Promise<void>;
}

function buildContext(
  contributorId: string,
  router: Router,
  appConfig: Record<string, unknown>,
): HostContext {
  return {
    router,
    authStore: useAuthStore(),
    topbarMenu: useTopbarMenu(),
    appConfig,
    contributorId,
    addRoute: (route) => router.addRoute(route),
  };
}

async function loadAndRegister(
  url: string,
  contributorId: string,
  router: Router,
  appConfig: Record<string, unknown>,
): Promise<boolean> {
  try {
    // Vite's dev server resolves dynamic imports through its module
    // graph; at production/runtime the browser fetches the URL
    // directly and resolves bare imports via the importmap in
    // index.html. `/* @vite-ignore */` keeps Vite from trying to
    // pre-analyze this dynamic URL at build time.
    const mod: ServerModule = await import(/* @vite-ignore */ url);
    const register = mod.register ?? mod.default;
    if (typeof register !== "function") {
      throw new Error(
        `Server module ${url} did not export a register() function`,
      );
    }
    await register(buildContext(contributorId, router, appConfig));
    // eslint-disable-next-line no-console
    console.info(`[boot] loaded server module ${url}`);
    return true;
  } catch (error) {
    // eslint-disable-next-line no-console
    console.error(`[boot] failed to load server module ${url}:`, error);
    serverModuleLoadFailed.value = { module: url, error };
    return false;
  }
}

let adminLoaded = false;

/**
 * Orchestrate server-module loading. Called once from main.ts after
 * the Vue app is created but BEFORE app.mount() — so the first
 * navigation sees any routes the modules register.
 */
export async function bootServerModules(router: Router): Promise<void> {
  const { config, loadConfig } = useAppConfig();

  // Config must be loaded before we can decide what to fetch.
  const ok = await loadConfig();
  if (!ok || !config.value) {
    // Config unavailable — can't tell mode or features. Router guard
    // fails closed in that case; server modules cannot load either.
    return;
  }

  const cfg = config.value as Record<string, unknown>;
  const features = (cfg.features ?? {}) as Record<string, unknown>;

  // Deployment-level: auth UI module. Eagerly loaded when the
  // feature flag is set (server-backed modes only).
  if (features.authUI) {
    await loadAndRegister("/ui/auth.js", "server:auth", router, cfg);
  }

  // User-level: admin UI module. Lazily loaded when the host user
  // resolves with capabilities.admin. Watched rather than eagerly
  // loaded because identity may not be known at boot time (e.g.
  // hybrid mode calls /auth/me asynchronously).
  const authStore = useAuthStore();
  watch(
    () => authStore.user?.capabilities?.admin,
    async (isAdmin) => {
      if (isAdmin && !adminLoaded) {
        const ok = await loadAndRegister(
          "/ui/admin.js",
          "server:admin",
          router,
          cfg,
        );
        if (ok) adminLoaded = true;
      }
    },
    { immediate: true },
  );
}
