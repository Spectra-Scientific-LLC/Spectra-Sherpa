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
 * module-local `serverModuleLoadFailed` ref. The OSS shell reads that
 * ref to render a fail-closed overlay — server-backed deployments
 * must not fall through to a functional UI when the auth module is
 * missing, since that would expose protected routes without identity.
 *
 * Cross-bundle runtime: the server modules import `vue`, `vue-router`,
 * `pinia`, and `primevue/*` as Vite externals. They resolve via the
 * `<script type="importmap">` in index.html, which points at the
 * `/vendor/*.js` shims. Those shims read from `window.__OSS_VENDOR__`,
 * populated in main.ts BEFORE this bootstrap runs.
 */
import { markRaw, ref, watch } from "vue";
import type { Component } from "vue";
import type { Router, RouteRecordRaw } from "vue-router";

import { useAppConfig } from "@/composables/useAppConfig";
import {
  useTopbarMenu,
  type TopbarMenuItem,
} from "@/composables/useTopbarMenu";
import { useAuthStore } from "@/stores/auth";

export interface ServerModuleShell {
  component: Component;
  contributorId: string;
}

/**
 * Reactive list of shell components contributed by server modules.
 * The OSS App shell renders each entry via `<component :is="..."/>`
 * so modules can own persistent UI (e.g. AuthShell owns
 * ChangePasswordDialog + UserProfileDialog).
 */
export const serverModuleShells = ref<ServerModuleShell[]>([]);

/**
 * Set when any server module fetch/register throws. The OSS App shell
 * consumes this to render a fail-closed overlay — required because a
 * silent failure in a server-backed deployment would otherwise expose
 * a partially-functional UI without identity.
 */
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
  mountShell(component: Component, contributorId?: string): void;
  unmountShells(contributorId: string): void;
}

interface ServerModule {
  register?: (ctx: HostContext) => void | Promise<void>;
  default?: (ctx: HostContext) => void | Promise<void>;
}

export type ImportModuleFn = (url: string) => Promise<ServerModule>;

const defaultImportModule: ImportModuleFn = (url) =>
  // Vite's dev server resolves dynamic imports through its module
  // graph; at production/runtime the browser fetches the URL directly
  // and resolves bare imports via the importmap in index.html.
  // `/* @vite-ignore */` keeps Vite from pre-analyzing the dynamic URL.
  import(/* @vite-ignore */ url) as Promise<ServerModule>;

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
    mountShell: (component, id) => {
      serverModuleShells.value.push({
        // markRaw: Vue components are already immutable; wrapping
        // them in reactivity is wasteful and triggers a devtools warning.
        component: markRaw(component),
        contributorId: id ?? contributorId,
      });
    },
    unmountShells: (id) => {
      serverModuleShells.value = serverModuleShells.value.filter(
        (entry) => entry.contributorId !== id,
      );
    },
  };
}

async function loadAndRegister(
  url: string,
  contributorId: string,
  router: Router,
  appConfig: Record<string, unknown>,
  importModule: ImportModuleFn,
): Promise<boolean> {
  try {
    const mod = await importModule(url);
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

export interface BootServerModulesOptions {
  /**
   * Override the module loader. Tests inject a stub that returns a
   * fake `register()` instead of fetching over the network.
   */
  importModule?: ImportModuleFn;
}

/**
 * Reset module-local state. Exposed only so tests can run
 * `bootServerModules` repeatedly without cross-test contamination; OSS
 * runtime never calls this.
 */
export function __resetServerModulesForTests(): void {
  adminLoaded = false;
  serverModuleShells.value = [];
  serverModuleLoadFailed.value = null;
}

/**
 * Orchestrate server-module loading. Called once from main.ts after
 * the Vue app is created but BEFORE app.mount() — so the first
 * navigation sees any routes the modules register.
 */
export async function bootServerModules(
  router: Router,
  options: BootServerModulesOptions = {},
): Promise<void> {
  const importModule = options.importModule ?? defaultImportModule;
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
    await loadAndRegister(
      "/ui/auth.js",
      "server:auth",
      router,
      cfg,
      importModule,
    );
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
          importModule,
        );
        if (ok) adminLoaded = true;
      }
    },
    { immediate: true },
  );
}
