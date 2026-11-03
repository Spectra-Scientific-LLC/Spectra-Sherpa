/**
 * Boot-time loader coverage.
 *
 * Exercises the paths the OSS shell depends on when resolving which
 * server-provided frontend modules to load:
 *
 *   1. features.authUI=true  → /ui/auth.js loaded eagerly (fail-closed)
 *   2. features absent       → neither module loads (local-mode default)
 *   3. admin capability      → /ui/admin.js lazy-loads after identity
 *   4. auth.js throws        → serverModuleLoadFailed is set (app bricked)
 *   5. admin.js throws       → non-critical failure list grows, shell
 *                              stays usable (no fail-closed)
 *   6. context authStore     → `user` is a real Vue ref — writes via
 *                              `ctx.authStore.user.value = …` flow back
 *                              into the OSS Pinia store
 *
 * The boot module exports an injectable `importModule` so tests can
 * avoid Vite's network-only dynamic import; each test wires its own
 * fake registrar through that seam.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { isRef, nextTick } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import { createPinia, setActivePinia } from "pinia";
import type { CurrentHostContext } from "@/extension-contract/v1";

const { mockLoadConfig, mockConfig } = vi.hoisted(() => ({
  mockLoadConfig: vi.fn<[], Promise<boolean>>(),
  mockConfig: { value: null as Record<string, unknown> | null },
}));

vi.mock("@/composables/useAppConfig", async () => {
  const { ref } = await import("vue");
  const config = ref<Record<string, unknown> | null>(null);
  Object.defineProperty(mockConfig, "value", {
    get: () => config.value, set: (value) => { config.value = value; }, configurable: true,
  });
  return { useAppConfig: () => ({ config, loadConfig: mockLoadConfig }) };
});

import {
  __resetServerModulesForTests,
  bootServerModules,
  nonCriticalModuleLoadFailures,
  serverModuleLoadFailed,
  serverModuleShells,
  type ImportModuleFn,
} from "@/boot/serverModules";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";
import { setActionContext, useContextualActions } from "@/composables/useContextualActions";
import { useTopbarMenu } from "@/composables/useTopbarMenu";
import { usePrimaryNavigation } from "@/composables/usePrimaryNavigation";
import { pendingConfirmation, settleConfirmation } from "@/composables/useConfirmAction";

const makeRouter = () =>
  createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: { template: "<div />" } }],
  });

/**
 * Flush the microtask queue enough times for the watcher + the
 * promise chain inside loadAndRegister to settle.
 */
async function flushAsync() {
  await nextTick();
  await Promise.resolve();
  await Promise.resolve();
  await nextTick();
}

describe("bootServerModules", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    __resetServerModulesForTests();
    vi.spyOn(useProjectStore(), "ensureProjectForBrowserTab").mockResolvedValue(null);
    const stylesheet = document.createElement("link");
    stylesheet.setAttribute("data-server-styles", "");
    document.head.appendChild(stylesheet);
    mockConfig.value = null;
    mockLoadConfig.mockReset();
    useTopbarMenu().clear();
    usePrimaryNavigation().clear();
  });

  function extensionConfig() {
    mockConfig.value = { mode: "enterprise", features: {},
      uiExtensions: [{ id: "mock", url: "/ui/mock.js", contractVersion: 1 }] };
    mockLoadConfig.mockResolvedValue(true);
    useAuthStore().user = { id: 1, username: "scientist", capabilities: { admin: false } };
  }

  it("registers the unavailable-project destination on a fresh boot and refresh", async () => {
    extensionConfig();
    const router = makeRouter();
    router.options.history.replace('/project-unavailable');
    await bootServerModules(router, { importModule: async () => ({ register() {} }) });
    expect(router.resolve('/project-unavailable').name).toBe('project-unavailable');
  });

  it.each(["project_id", "project"])("restores the linked %s before extension registration", async (key) => {
    extensionConfig();
    const router = makeRouter();
    router.options.history.replace(`/mock?${key}=2`);
    const project = useProjectStore();
    vi.spyOn(project, "fetchProject").mockImplementation(async (id) => {
      project.currentProjectId = id;
      return { id, name: "Linked project" } as any;
    });
    const register = vi.fn();
    await bootServerModules(router, { importModule: async () => ({ contextualActionsVersion: 1, register }) });
    expect(project.fetchProject).toHaveBeenCalledWith(2);
    expect(register.mock.calls[0][0].extensions.projectId).toBe(2);
    expect(project.ensureProjectForBrowserTab).not.toHaveBeenCalled();
  });

  it("restores the last project before registering an extension without a project link", async () => {
    extensionConfig();
    const project = useProjectStore();
    vi.mocked(project.ensureProjectForBrowserTab).mockImplementation(async () => {
      project.currentProjectId = 3;
      return { id: 3, name: "Last project" } as any;
    });
    const register = vi.fn();
    await bootServerModules(makeRouter(), { importModule: async () => ({ contextualActionsVersion: 1, register }) });
    expect(register.mock.calls[0][0].extensions.projectId).toBe(3);
  });

  it.each(["0", "bad", "2"])("refuses an invalid or inaccessible project link: %s", async (id) => {
    extensionConfig();
    const router = makeRouter();
    router.options.history.replace(`/mock?project_id=${id}`);
    vi.spyOn(useProjectStore(), "fetchProject").mockResolvedValue(null);
    const importModule = vi.fn(async () => ({ contextualActionsVersion: 1, register: vi.fn() }));
    await bootServerModules(router, { importModule });
    expect(importModule).toHaveBeenCalled();
    expect(serverModuleLoadFailed.value).toBeNull();
    expect(router.currentRoute.value.name).toBe("project-unavailable");
    expect(useProjectStore().currentProjectId).toBeNull();
    expect(useProjectStore().ensureProjectForBrowserTab).not.toHaveBeenCalled();
  });

  it("never requests optional modules in local OSS", async () => {
    extensionConfig();
    mockConfig.value!.mode = "local";
    const importModule = vi.fn();
    await bootServerModules(makeRouter(), { importModule });
    expect(importModule).not.toHaveBeenCalled();
  });

  it("loads an explicitly installed bootstrap transport in local mode and disposes it", async () => {
    extensionConfig();
    mockConfig.value!.mode = "local";
    mockConfig.value!.uiExtensions = [{ id: "mock", url: "/ui/mock.js", contractVersion: 1, bootstrap: true, required: true }];
    const { requireAdvisorTransport } = await import("@/lib/advisorTransport");
    const transport = { prepareContext: vi.fn(), loadConversation: vi.fn(), deleteConversation: vi.fn(), confirmProposal: vi.fn() };
    await bootServerModules(makeRouter(), { importModule: async () => ({ contextualActionsVersion: 1,
      register: (ctx) => ctx.installAdvisorTransport(transport) }) });
    expect(requireAdvisorTransport()).toBe(transport);
    mockConfig.value!.uiExtensions = [];
    await flushAsync();
    expect(() => requireAdvisorTransport()).toThrow();
  });

  it.each(["invalid-descriptor", "missing-bundle"])("refuses a required bootstrap module: %s", async (failure) => {
    extensionConfig();
    mockConfig.value!.mode = "local";
    mockConfig.value!.uiExtensions = [{ id: "mock", url: failure === "invalid-descriptor" ? "/outside.js" : "/ui/mock.js",
      contractVersion: 1, bootstrap: true, required: true }];
    await bootServerModules(makeRouter(), { importModule: async () => { throw new Error("Unavailable"); } });
    expect(serverModuleLoadFailed.value).not.toBeNull();
  });

  it.each([undefined, 2])("rejects incompatible module version %s", async (version) => {
    extensionConfig();
    const register = vi.fn();
    await bootServerModules(makeRouter(), { importModule: async () => ({ contextualActionsVersion: version, register }) });
    await flushAsync();
    expect(register).not.toHaveBeenCalled();
    expect(nonCriticalModuleLoadFailures.value).toHaveLength(1);
    expect(serverModuleLoadFailed.value).toBeNull();
  });

  it.each([undefined, 2])("fails closed for required module version %s before registration", async (version) => {
    extensionConfig();
    mockConfig.value!.uiExtensions = [
      { id: "mock", url: "/ui/mock.js", contractVersion: 1, required: true },
    ];
    const register = vi.fn();
    await bootServerModules(makeRouter(), {
      importModule: async () => ({ contextualActionsVersion: version, register }),
    });
    expect(register).not.toHaveBeenCalled();
    expect(serverModuleLoadFailed.value?.module).toBe("/ui/mock.js");
    expect(nonCriticalModuleLoadFailures.value).toEqual([]);
  });

  it("preserves the default-export registration form with the public context", async () => {
    extensionConfig();
    const register = vi.fn();
    await bootServerModules(makeRouter(), {
      importModule: async () => ({ contextualActionsVersion: 1, default: register }),
    });
    expect(register).toHaveBeenCalledOnce();
    const ctx = register.mock.calls[0][0];
    expect(ctx.appConfig).toBe(mockConfig.value);
    expect(isRef(ctx.authStore.user)).toBe(true);
    for (const capability of ["reloadConfig", "installAdvisorTransport", "confirmAction",
      "focusOptimization", "focusSection", "setAdvisorScope"]) {
      expect(ctx[capability]).toBeTypeOf("function");
    }
    expect(ctx.api.get).toBeTypeOf("function");
    expect(ctx.extensions.setProjectCollections).toBeTypeOf("function");
  });

  it.each(["https://outside.invalid/plugin.js", "/ui/../mock.js", "/ui/mock.js?version=1"])("rejects nonlocal descriptor %s", async (url) => {
    extensionConfig();
    mockConfig.value!.uiExtensions = [{ id: "mock", url, contractVersion: 1 }];
    const importModule = vi.fn();
    await bootServerModules(makeRouter(), { importModule });
    expect(importModule).not.toHaveBeenCalled();
    expect(nonCriticalModuleLoadFailures.value).toHaveLength(1);
  });

  it.each(["logout", "project", "capability", "configuration"])("disposes contributions on %s and rejects late registration", async (change) => {
    extensionConfig();
    const router = makeRouter();
    const contexts: Array<Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0]> = [];
    const cleanup = vi.fn();
    await bootServerModules(router, { importModule: async () => ({ contextualActionsVersion: 1, register(ctx) {
      contexts.push(ctx);
      ctx.addRoute({ name: "mock", path: "/mock", component: { template: "<div />" } });
      ctx.mountShell({ template: "<div />" });
      ctx.topbarMenu.addItems([{ label: "Mock" }]);
      ctx.primaryNavigation.addItems([
        { label: "Mock", to: "/mock", icon: "pi pi-circle" },
      ]);
      ctx.extensions.onDispose(cleanup);
      ctx.extensions.addActions([{ id: "inspect", label: "Inspect", available: () => true, execute: vi.fn() }]);
    } }) });
    await flushAsync();
    setActionContext({ surface: "run", projectId: 1, runId: 1 });
    expect(useContextualActions().actions.value).toHaveLength(1);
    const original = contexts[0];
    if (change === "logout") useAuthStore().user = null;
    else if (change === "project") useProjectStore().currentProjectId = 2;
    else if (change === "capability") useAuthStore().user!.capabilities = { admin: false, sherpaAdvisor: true } as any;
    else mockConfig.value!.uiExtensions = [];
    expect(original.extensions.signal.aborted).toBe(true);
    expect(cleanup).toHaveBeenCalledTimes(1);
    expect(useContextualActions().actions.value).toHaveLength(0);
    expect(router.hasRoute("mock")).toBe(false);
    expect(serverModuleShells.value).toHaveLength(0);
    expect(useTopbarMenu().items.value).toHaveLength(0);
    expect(usePrimaryNavigation().items.value).toHaveLength(0);
    original.addRoute({ name: "late", path: "/late", component: { template: "<div />" } });
    original.mountShell({ template: "<div />" });
    original.extensions.addActions([{ id: "late", label: "Late", available: () => true, execute: vi.fn() }]);
    expect(router.hasRoute("late")).toBe(false);
    expect(serverModuleShells.value).toHaveLength(0);
    await flushAsync();
    if (change === "project" || change === "capability") expect(contexts).toHaveLength(2);
  });

  it("does not register an import that finishes after logout", async () => {
    extensionConfig();
    let resolve!: (module: Awaited<ReturnType<ImportModuleFn>>) => void;
    const pending = new Promise<Awaited<ReturnType<ImportModuleFn>>>((done) => { resolve = done; });
    const register = vi.fn();
    const boot = bootServerModules(makeRouter(), { importModule: () => pending });
    await Promise.resolve();
    useAuthStore().user = null;
    resolve({ contextualActionsVersion: 1, register });
    await boot;
    await flushAsync();
    expect(register).not.toHaveBeenCalled();
  });

  it("lets a module confirm through the shell dialog, but never after its registration ended", async () => {
    extensionConfig();
    const register = vi.fn();
    await bootServerModules(makeRouter(), { importModule: async () => ({ contextualActionsVersion: 1, register }) });
    await flushAsync();
    const ctx = register.mock.calls[0][0];
    const options = { title: "Hide campaigns", message: "Hidden campaigns keep running.", acceptLabel: "Hide from list" };

    const accepted = ctx.confirmAction(options);
    expect(pendingConfirmation.value?.options).toEqual(options);
    settleConfirmation(true);
    await expect(accepted).resolves.toBe(true);

    // Ending the registration closes its open dialog as declined.
    const afterLogout = ctx.confirmAction(options);
    expect(pendingConfirmation.value?.options).toEqual(options);
    useAuthStore().user = null;
    await flushAsync();
    expect(pendingConfirmation.value).toBeNull();
    await expect(afterLogout).resolves.toBe(false);
    await expect(ctx.confirmAction(options)).resolves.toBe(false);
    expect(pendingConfirmation.value).toBeNull();
  });

  it("closes a module's dialog when the calling view's signal aborts", async () => {
    extensionConfig();
    const register = vi.fn();
    await bootServerModules(makeRouter(), { importModule: async () => ({ contextualActionsVersion: 1, register }) });
    await flushAsync();
    const ctx = register.mock.calls[0][0];
    const view = new AbortController();
    const answer = ctx.confirmAction({ title: "Hide", message: "Hide it?", acceptLabel: "Hide" }, view.signal);
    expect(pendingConfirmation.value).not.toBeNull();
    view.abort();
    expect(pendingConfirmation.value).toBeNull();
    await expect(answer).resolves.toBe(false);
  });

  it("rolls back partially registered failed modules", async () => {
    extensionConfig();
    const router = makeRouter();
    const cleanup = vi.fn();
    await bootServerModules(router, { importModule: async () => ({ contextualActionsVersion: 1, register(ctx) {
      ctx.addRoute({ name: "mock", path: "/mock", component: { template: "<div />" } });
      ctx.topbarMenu.addItems([{ label: "Mock" }]);
      ctx.extensions.onDispose(cleanup);
      throw new Error("broken bundle");
    } }) });
    await flushAsync();
    expect(router.hasRoute("mock")).toBe(false);
    expect(cleanup).toHaveBeenCalledOnce();
    expect(useTopbarMenu().items.value).toHaveLength(0);
    expect(serverModuleLoadFailed.value).toBeNull();
  });

  it("loads /ui/auth.js eagerly when features.authUI is true", async () => {
    mockConfig.value = {
      mode: "enterprise",
      features: { authUI: true },
    };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn<Parameters<ImportModuleFn>, ReturnType<ImportModuleFn>>(
      async () => ({
        register: vi.fn(),
      }),
    );

    await bootServerModules(makeRouter(), { importModule });

    expect(importModule).toHaveBeenCalledWith("/ui/auth.js");
    expect(serverModuleLoadFailed.value).toBeNull();
  });

  it("can skip current-route re-resolve when boot runs before router install", async () => {
    mockConfig.value = {
      mode: "enterprise",
      features: { authUI: true },
    };
    mockLoadConfig.mockResolvedValue(true);

    const router = makeRouter();
    const replaceSpy = vi.spyOn(router, "replace");
    const importModule = vi.fn(async () => ({ register: vi.fn() }));

    await bootServerModules(router, {
      importModule,
      reresolveCurrentRoute: false,
    });

    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it("finishes initial extension route registration before router installation", async () => {
    extensionConfig();
    const router = makeRouter();
    let finishImport!: () => void;
    const imported = new Promise<void>((resolve) => { finishImport = resolve; });
    const boot = bootServerModules(router, {
      reresolveCurrentRoute: false,
      importModule: async () => {
        await imported;
        return {
          contextualActionsVersion: 1,
          register(ctx) {
            ctx.addRoute({ name: "managed", path: "/managed", component: { template: "<div />" } });
          },
        };
      },
    });

    await Promise.resolve();
    expect(router.hasRoute("managed")).toBe(false);
    finishImport();
    await boot;

    expect(router.hasRoute("managed")).toBe(true);
  });

  async function postLoginRouter(firstImportOnly = false, reresolveCurrentRoute = false, required = false) {
    extensionConfig();
    if (required) {
      mockConfig.value = { ...mockConfig.value, uiExtensions: [
        { id: "mock", url: "/ui/mock.js", contractVersion: 1, required: true },
      ] };
    }
    useAuthStore().user = null;
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: "/", component: { template: "<div />" } },
      { path: "/login", meta: { public: true }, component: { template: "<div />" } },
      { path: "/:pathMatch(.*)*", name: "not-found", component: { template: "<div />" } },
    ] });
    const saved = "/campaigns?project_id=134&monitor=round44#retained";
    await router.push({ path: "/login", query: { return_to: saved } });
    let finish!: () => void;
    const imported = new Promise<void>((resolve) => { finish = resolve; });
    const register = vi.fn((ctx: CurrentHostContext) => {
      ctx.addRoute({ path: "/campaigns", name: "managed", component: { template: "<div />" },
        beforeEnter: () => ctx.extensions.isCurrent() && !!useAuthStore().user
          && ctx.extensions.projectId === 134 });
    });
    let imports = 0;
    await bootServerModules(router, { reresolveCurrentRoute, importModule: async () => {
      imports += 1;
      if (!firstImportOnly || imports === 1) await imported;
      return { contextualActionsVersion: 1, register };
    } });
    const project = useProjectStore();
    vi.spyOn(project, "fetchProject").mockImplementation(async (id) => {
      project.currentProjectId = id;
      project.currentProject = { id, name: "Linked" } as NonNullable<typeof project.currentProject>;
      return project.currentProject;
    });
    useAuthStore().token = "current-login";
    useAuthStore().user = { id: 1, username: "scientist" };
    return { router, saved, finish, register, project };
  }

  it("active managed route follows admitted cross-project destination", async () => {
    const { router, saved, finish, register, project } = await postLoginRouter();
    register.mockImplementation((ctx: CurrentHostContext) => {
      ctx.addRoute({ path: "/campaigns", name: "managed", component: { template: "<div />" },
        beforeEnter: () => ctx.extensions.isCurrent() && !!useAuthStore().user });
    });
    const first = router.push(saved);
    finish();
    await first;
    await flushAsync();
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(project.currentProjectId).toBe(134);
    vi.mocked(project.fetchProject).mockClear();
    const next = saved.replace("project_id=134", "project_id=135");
    await router.push(next);
    await flushAsync();
    await flushAsync();
    expect(project.currentProjectId).toBe(135);
    expect(router.currentRoute.value.fullPath).toBe(next);
    expect(router.currentRoute.value.name).toBe("managed");
    expect(register.mock.calls.at(-1)?.[0].extensions.projectId).toBe(135);
  });

  it("real store active managed route follows admitted cross-project destination", async () => {
    const { router, saved, finish, register, project } = await postLoginRouter();
    register.mockImplementation((ctx: CurrentHostContext) => {
      ctx.addRoute({ path: "/campaigns", name: "managed", component: { template: "<div />" },
        beforeEnter: () => ctx.extensions.isCurrent() && !!useAuthStore().user });
    });
    const first = router.push(saved);
    finish();
    await first;
    await flushAsync();
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(project.currentProjectId).toBe(134);
    vi.mocked(project.fetchProject).mockRestore();
    vi.spyOn(api, "get").mockResolvedValue({ data: { id: 135, name: "Target", created_at: "2026-11-02", updated_at: "2026-11-02" } });
    const replace = vi.spyOn(router, "replace");
    const next = saved.replace("project_id=134", "project_id=135");
    await router.push(next);
    await flushAsync();
    await flushAsync();
    expect(replace).not.toHaveBeenCalledWith("/");
    expect(project.currentProjectId).toBe(135);
    expect(router.currentRoute.value.fullPath).toBe(next);
    expect(router.currentRoute.value.name).toBe("managed");
    expect(register.mock.calls.at(-1)?.[0].extensions.projectId).toBe(135);
  });

  async function activeManagedRoute() {
    const state = await postLoginRouter();
    const addManaged = (ctx: CurrentHostContext, beforeEnter: () => boolean = () => true) => {
      ctx.addRoute({ path: "/campaigns", name: "managed", component: { template: "<div />" },
        beforeEnter: () => ctx.extensions.isCurrent() && !!useAuthStore().user && beforeEnter() });
    };
    state.register.mockImplementation(addManaged);
    const first = state.router.push(state.saved);
    state.finish();
    await first;
    const original = state.register.mock.calls.at(-1)![0];
    vi.mocked(state.project.fetchProject).mockRestore();
    vi.spyOn(api, "get").mockResolvedValue({ data: {
      id: 135, name: "Target", created_at: "2026-11-02", updated_at: "2026-11-02",
    } });
    const next = state.saved.replace("project_id=134", "project_id=135");
    return { ...state, original, next, addManaged };
  }

  function arrivedAt(router: ReturnType<typeof makeRouter>, path: string) {
    return new Promise<void>(resolve => {
      const remove = router.afterEach((to, _from, failure) => {
        if (!failure && to.path === path) { remove(); resolve(); }
      });
    });
  }

  it("keeps standalone project changes falling back to Dashboard and retires old actions", async () => {
    const { router, project, original } = await activeManagedRoute();
    const dashboard = arrivedAt(router, "/");
    await project.fetchProject(135);
    await dashboard;
    expect(router.currentRoute.value.path).toBe("/");
    expect(original.extensions.isCurrent()).toBe(false);
    expect(original.extensions.signal.aborted).toBe(true);
    original.addRoute({ path: "/stale-action", name: "stale-action", component: { template: "<div />" } });
    expect(router.hasRoute("stale-action")).toBe(false);
  });

  it("preserves a denied cross-project destination without a cleanup Dashboard redirect", async () => {
    const { router, next, project, original } = await activeManagedRoute();
    vi.spyOn(project, "fetchProject").mockResolvedValue(null);
    const replace = vi.spyOn(router, "replace");
    await router.push(next);
    expect(router.currentRoute.value.name).toBe("project-unavailable");
    expect(replace).not.toHaveBeenCalledWith("/");
    expect(original.extensions.isCurrent()).toBe(false);
    expect(original.extensions.signal.aborted).toBe(true);
  });

  it("does not let an old cancelled navigation redirect over a newer built-in destination", async () => {
    const { router, next, register, original, addManaged } = await activeManagedRoute();
    router.addRoute({ path: "/settings", component: { template: "<div />" } });
    let complete!: () => void;
    let started!: () => void;
    const startedRegistration = new Promise<void>(resolve => { started = resolve; });
    const gate = new Promise<void>(resolve => { complete = resolve; });
    register.mockImplementation(async ctx => {
      if (ctx.extensions.projectId === 135) { started(); await gate; }
      addManaged(ctx);
    });
    const navigation = router.push(next);
    await startedRegistration;
    expect(original.extensions.isCurrent()).toBe(false);
    expect(original.extensions.signal.aborted).toBe(true);
    const replace = vi.spyOn(router, "replace");
    await router.push("/settings");
    await navigation;
    complete();
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/settings");
    expect(replace).not.toHaveBeenCalledWith("/");
  });

  it.each(["cancel", "error"])("leaves a retired view safely if the admitted destination later ends with %s", async mode => {
    const { router, next, register, original, addManaged } = await activeManagedRoute();
    const dashboard = arrivedAt(router, "/");
    register.mockImplementation(ctx => addManaged(ctx, () => {
      if (mode === "error") throw new Error("synthetic route guard failure");
      return false;
    }));
    const outcome = await router.push(next).then(() => "settled", () => "error");
    expect(outcome).toBe(mode === "error" ? "error" : "settled");
    await dashboard;
    expect(router.currentRoute.value.path).toBe("/");
    expect(original.extensions.isCurrent()).toBe(false);
    expect(original.extensions.signal.aborted).toBe(true);
  });

  it("follows a benign same-owner feature generation while registration is pending", async () => {
    const { router, saved, finish } = await postLoginRouter();
    const revision = useAuthStore().sessionRevision;
    const navigation = router.push(saved);
    await flushAsync();
    mockConfig.value = { ...mockConfig.value, features: { harmlessRefresh: true } };
    expect(useAuthStore().sessionRevision).toBe(revision);
    finish();
    await navigation;
    await flushAsync();
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(router.currentRoute.value.name).toBe("managed");
  });

  it("does not wait for an obsolete import after the same-owner replacement is ready", async () => {
    const { router, saved, finish } = await postLoginRouter(true);
    const navigation = router.push(saved);
    await flushAsync();
    mockConfig.value = { ...mockConfig.value, features: { harmlessRefresh: true } };
    await navigation;
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(router.currentRoute.value.name).toBe("managed");
    // Only now settle the first generation; it cannot supersede the accepted one.
    finish();
    await flushAsync();
    expect(router.currentRoute.value.fullPath).toBe(saved);
  });

  it("also completes saved-route admission when current-route re-resolution is enabled", async () => {
    const { router, saved, finish } = await postLoginRouter(false, true);
    const navigation = router.push(saved);
    finish();
    await navigation;
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(router.currentRoute.value.name).toBe("managed");
  });

  it("restores linked project when registration settles before router.push", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    finish();
    await flushAsync();
    await flushAsync();
    expect(router.hasRoute("managed")).toBe(true);
    await router.push(saved);
    expect(project.fetchProject).toHaveBeenCalledWith(134, expect.objectContaining({ signal: expect.any(AbortSignal), onInvalidated: expect.any(Function) }));
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(router.currentRoute.value.name).toBe("managed");
  });

  it("cancelled navigation cannot later select its old project via the real store", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    vi.mocked(project.fetchProject).mockRestore();
    let complete!: (value: unknown) => void;
    let started!: () => void;
    const startedRead = new Promise<void>(resolve => { started = resolve; });
    vi.spyOn(api, "get").mockImplementation(() => { started(); return new Promise(resolve => { complete = resolve; }); });
    const navigation = router.push(saved);
    finish();
    await startedRead;
    await router.push("/");
    await navigation;
    complete({ data: { id: 134, name: "Old saved destination", created_at: "2026-11-02", updated_at: "2026-11-02" } });
    await flushAsync();
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/");
    expect(project.currentProjectId).not.toBe(134);
  });

  it("real project store protects a newer explicit project choice", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    vi.mocked(project.fetchProject).mockRestore();
    let complete!: (value: unknown) => void;
    let started!: () => void;
    const startedRead = new Promise<void>(resolve => { started = resolve; });
    vi.spyOn(api, "get").mockImplementation(() => { started(); return new Promise(resolve => { complete = resolve; }); });
    const navigation = router.push(saved);
    finish();
    await startedRead;
    project.currentProjectId = 135;
    project.currentProject = { id: 135, name: "New choice" } as NonNullable<typeof project.currentProject>;
    await router.push("/");
    await navigation;
    complete({ data: { id: 134, name: "Old destination", created_at: "2026-11-02", updated_at: "2026-11-02" } });
    await flushAsync();
    expect(project.currentProjectId).toBe(135);
  });

  it("cancels rather than clearing a newer canonical project read without requiring another navigation", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    vi.mocked(project.fetchProject).mockRestore();
    const complete: Array<(value: unknown) => void> = [];
    let started!: () => void;
    const startedRead = new Promise<void>(resolve => { started = resolve; });
    vi.spyOn(api, "get").mockImplementation(() => {
      started();
      return new Promise(resolve => { complete.push(resolve); });
    });
    const navigation = router.push(saved);
    finish();
    await startedRead;
    const newer = project.fetchProject(135);
    await navigation;
    complete[1]({ data: { id: 135, name: "New choice", created_at: "2026-11-02", updated_at: "2026-11-02" } });
    await newer;
    complete[0]({ data: { id: 134, name: "Abandoned", created_at: "2026-11-02", updated_at: "2026-11-02" } });
    await flushAsync();
    expect(project.currentProjectId).toBe(135);
    expect(router.currentRoute.value.path).toBe("/login");
  });

  it("keeps already-admitted same-project extension navigation free of repeated project reads", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    const navigation = router.push(saved);
    finish();
    await navigation;
    vi.mocked(project.fetchProject).mockClear();
    const next = saved.replace("round44", "round45");
    await router.push(next);
    expect(router.currentRoute.value.fullPath).toBe(next);
    expect(project.fetchProject).not.toHaveBeenCalled();
  });

  it("does not load linked projects for built-in routes or local-mode missing extensions", async () => {
    const { router, finish, project } = await postLoginRouter();
    finish();
    await router.push("/?project_id=134");
    expect(project.fetchProject).not.toHaveBeenCalled();
    mockConfig.value = { ...mockConfig.value, mode: "local", uiExtensions: [] };
    await flushAsync();
    await router.push("/campaigns?project_id=134");
    expect(router.currentRoute.value.name).toBe("not-found");
    expect(project.fetchProject).not.toHaveBeenCalled();
  });

  it.each([false, true])("bounds a stuck saved-link import and rejects its late registration (required=%s)", async required => {
    vi.useFakeTimers();
    try {
      const { router, saved, finish, register, project } = await postLoginRouter(false, false, required);
      let settled = false;
      const navigation = router.push(saved).then(() => { settled = true; });
      await flushAsync();
      await vi.advanceTimersByTimeAsync(29_999);
      expect(settled).toBe(false);
      expect(project.fetchProject).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(settled).toBe(true);
      await navigation;
      if (required) {
        expect(serverModuleLoadFailed.value?.module).toBe("/ui/mock.js");
        expect(nonCriticalModuleLoadFailures.value).toHaveLength(0);
      } else {
        expect(serverModuleLoadFailed.value).toBeNull();
        expect(nonCriticalModuleLoadFailures.value.map(item => item.module)).toEqual(["/ui/mock.js"]);
      }
      expect(project.fetchProject).not.toHaveBeenCalled();
      expect(router.currentRoute.value.name).toBe("not-found");
      finish();
      await flushAsync();
      expect(register).not.toHaveBeenCalled();
      expect(router.hasRoute("managed")).toBe(false);
      expect(router.currentRoute.value.name).toBe("not-found");
    } finally {
      __resetServerModulesForTests();
      vi.useRealTimers();
    }
  });

  it("times out async registration, revokes its partial route, and ignores late contributions", async () => {
    vi.useFakeTimers();
    try {
      const { router, saved, finish, register } = await postLoginRouter();
      let resume!: () => void;
      const registered = new Promise<void>(resolve => { resume = resolve; });
      let context!: CurrentHostContext;
      register.mockImplementation(async ctx => {
        context = ctx;
        ctx.addRoute({ name: "partial", path: "/campaigns", component: { template: "<div />" } });
        await registered;
        ctx.addRoute({ name: "late", path: "/late", component: { template: "<div />" } });
        ctx.extensions.addActions([{ id: "late", label: "Late", available: () => true, execute: vi.fn() }]);
      });
      let settled = false;
      const navigation = router.push(saved).then(() => { settled = true; });
      finish();
      await flushAsync();
      expect(router.hasRoute("partial")).toBe(true);
      await vi.advanceTimersByTimeAsync(30_000);
      expect(settled).toBe(true);
      await navigation;
      expect(router.hasRoute("partial")).toBe(false);
      expect(context.extensions.isCurrent()).toBe(false);
      expect(context.extensions.signal.aborted).toBe(true);
      resume();
      await flushAsync();
      expect(router.hasRoute("late")).toBe(false);
      expect(router.currentRoute.value.name).toBe("not-found");
      expect(nonCriticalModuleLoadFailures.value.map(item => item.module)).toEqual(["/ui/mock.js"]);
    } finally {
      __resetServerModulesForTests();
      vi.useRealTimers();
    }
  });

  it("does not let an abandoned registration deadline fail a refreshed owner", async () => {
    vi.useFakeTimers();
    try {
      const { router, saved, finish, register } = await postLoginRouter(true);
      const navigation = router.push(saved);
      await flushAsync();
      await vi.advanceTimersByTimeAsync(15_000);
      useAuthStore().user!.capabilities = { admin: false };
      await flushAsync();
      await navigation;
      expect(router.currentRoute.value.fullPath).toBe(saved);
      const calls = register.mock.calls.length;
      await vi.advanceTimersByTimeAsync(30_000);
      finish();
      await flushAsync();
      expect(register.mock.calls).toHaveLength(calls);
      expect(router.currentRoute.value.fullPath).toBe(saved);
      expect(serverModuleLoadFailed.value).toBeNull();
      expect(nonCriticalModuleLoadFailures.value).toEqual([]);
    } finally {
      __resetServerModulesForTests();
      vi.useRealTimers();
    }
  });

  it("waits for post-login registration and rematches the exact saved URL despite boot re-resolve=false", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    const visited: unknown[] = [];
    router.afterEach((to) => { visited.push(to.name); });
    const navigation = router.push(saved);
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/login");
    finish();
    await navigation;
    expect(router.currentRoute.value.fullPath).toBe(saved);
    expect(router.currentRoute.value.name).toBe("managed");
    expect(project.fetchProject).toHaveBeenCalledWith(134, expect.objectContaining({ signal: expect.any(AbortSignal), onInvalidated: expect.any(Function) }));
    expect(visited).not.toContain("not-found");
  });

  it("leaves genuinely unknown saved URLs at 404 without fetching their project", async () => {
    const { router, finish, project } = await postLoginRouter();
    const navigation = router.push("/not-a-real-extension?project_id=134");
    finish();
    await navigation;
    expect(router.currentRoute.value.name).toBe("not-found");
    expect(project.fetchProject).not.toHaveBeenCalled();
  });

  it("refuses an inaccessible saved project without entering the extension", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    vi.mocked(project.fetchProject).mockResolvedValue(null);
    const navigation = router.push(saved);
    finish();
    await navigation;
    expect(router.currentRoute.value.name).toBe("project-unavailable");
    expect(project.currentProjectId).toBeNull();
  });

  it("cancels saved-route navigation immediately on logout while the import is still pending", async () => {
    const { router, saved, finish, register } = await postLoginRouter();
    const navigation = router.push(saved);
    await flushAsync();
    useAuthStore().user = null;
    await navigation;
    expect(router.currentRoute.value.path).toBe("/login");
    finish();
    await flushAsync();
    expect(register).not.toHaveBeenCalled();
    expect(router.hasRoute("managed")).toBe(false);
  });

  it("does not let a delayed registration navigate over a newer public route", async () => {
    const { router, saved, finish } = await postLoginRouter();
    const navigation = router.push(saved);
    await flushAsync();
    await router.push("/");
    await navigation;
    finish();
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/");
  });

  it("rejects the old saved navigation even when the same account signs in again", async () => {
    const { router, saved, finish } = await postLoginRouter();
    const navigation = router.push(saved);
    await flushAsync();
    useAuthStore().user = null;
    useAuthStore().token = "new-login";
    useAuthStore().user = { id: 1, username: "scientist" };
    await navigation;
    finish();
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/login");
  });

  it.each(["", "0", "134&project=135", "bad", "134&project_id=135"])(
    "does not restore a malformed or conflicting saved project: %s", async (query) => {
      const { router, finish, project } = await postLoginRouter();
      const navigation = router.push(`/campaigns?project_id=${query}`);
      finish();
      await navigation;
      expect(router.currentRoute.value.name).toBe("project-unavailable");
      expect(project.fetchProject).not.toHaveBeenCalled();
    },
  );

  it("does not reinterpret a present null project query as a missing project", async () => {
    const { router, finish, project } = await postLoginRouter();
    const navigation = router.push("/campaigns?project_id");
    finish();
    await navigation;
    expect(router.currentRoute.value.name).toBe("project-unavailable");
    expect(project.fetchProject).not.toHaveBeenCalled();
  });

  it("does not enter a project whose read completes after logout", async () => {
    const { router, saved, finish, project } = await postLoginRouter();
    let complete!: (value: null) => void;
    let started!: () => void;
    const requestStarted = new Promise<void>((resolve) => { started = resolve; });
    vi.mocked(project.fetchProject).mockImplementation(() => {
      started();
      return new Promise<null>((resolve) => { complete = resolve; });
    });
    const navigation = router.push(saved);
    finish();
    await requestStarted;
    useAuthStore().user = null;
    await navigation;
    complete(null);
    await flushAsync();
    expect(router.currentRoute.value.path).toBe("/login");
    expect(router.hasRoute("managed")).toBe(false);
  });

  it("skips /ui/auth.js when features.authUI is falsy (local-mode default)", async () => {
    mockConfig.value = { mode: "local", features: {} };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => ({ register: vi.fn() }));

    await bootServerModules(makeRouter(), { importModule });

    const calledUrls = importModule.mock.calls.map((c) => c[0]);
    expect(calledUrls).not.toContain("/ui/auth.js");
  });

  it("does not load admin while user lacks capabilities.admin", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => ({ register: vi.fn() }));

    await bootServerModules(makeRouter(), { importModule });

    const calledUrls = importModule.mock.calls.map((c) => c[0]);
    expect(calledUrls).toContain("/ui/auth.js");
    expect(calledUrls).not.toContain("/ui/admin.js");
  });

  it("loads a generic extension only when the live deployment publishes it", async () => {
    mockConfig.value = {
      mode: "enterprise",
      features: {},
      uiExtensions: [{ id: "mock", url: "/ui/mock.js", contractVersion: 1 }],
    };
    mockLoadConfig.mockResolvedValue(true);
    useAuthStore().user = { id: 1, username: "scientist" };
    const importModule = vi.fn(async () => ({ contextualActionsVersion: 1, register: vi.fn() }));

    await bootServerModules(makeRouter(), { importModule });

    await flushAsync();
    expect(importModule.mock.calls.map((call) => call[0])).toContain("/ui/mock.js");
    expect(serverModuleLoadFailed.value).toBeNull();
  });

  it("records an optional bundle failure without bricking ordinary analysis", async () => {
    mockConfig.value = {
      mode: "enterprise",
      features: { authUI: true },
      uiExtensions: [{ id: "mock", url: "/ui/mock.js", contractVersion: 1 }],
    };
    mockLoadConfig.mockResolvedValue(true);
    useAuthStore().user = { id: 1, username: "scientist" };
    const importModule = vi.fn(async (url: string) => {
      if (url === "/ui/mock.js") throw new Error("optional bundle unavailable");
      return { register: vi.fn() };
    });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });
    await flushAsync();

    expect(serverModuleLoadFailed.value).toBeNull();
    expect(nonCriticalModuleLoadFailures.value.map((item) => item.module)).toContain(
      "/ui/mock.js",
    );
    errorSpy.mockRestore();
  });

  it("lazy-loads /ui/admin.js when host identity is set via the context ref", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    // Capture the ctx the auth module's register() would see so we can
    // drive identity through the SAME path the real server bundle uses
    // (ctx.authStore.user.value = …), not by mutating Pinia directly.
    let capturedCtx:
      | Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0]
      | null = null;
    const importModule = vi.fn(async (url: string) => {
      if (url === "/ui/auth.js") {
        return {
          register: (ctx) => {
            capturedCtx = ctx;
          },
        };
      }
      return { register: vi.fn() };
    });

    await bootServerModules(makeRouter(), { importModule });
    expect(capturedCtx).not.toBeNull();
    expect(isRef(capturedCtx!.authStore.user)).toBe(true);

    // Admin has not loaded yet.
    const urlsBeforeAdmin = importModule.mock.calls.map((c) => c[0]);
    expect(urlsBeforeAdmin).not.toContain("/ui/admin.js");

    // Drive identity via the ref the server module got.
    capturedCtx!.authStore.user.value = {
      id: 42,
      username: "admin",
      capabilities: { admin: true },
    };
    await flushAsync();

    const urlsAfterAdmin = importModule.mock.calls.map((c) => c[0]);
    expect(urlsAfterAdmin).toContain("/ui/admin.js");

    // The ref-write went through to the OSS Pinia store too —
    // isAuthenticated should flip true.
    const authStore = useAuthStore();
    expect(authStore.user?.username).toBe("admin");
    expect(authStore.isAuthenticated).toBe(true);
  });

  it("sets serverModuleLoadFailed when auth module import throws (fail-closed)", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => {
      throw new Error("network unreachable");
    });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });

    expect(serverModuleLoadFailed.value).not.toBeNull();
    expect(serverModuleLoadFailed.value?.module).toBe("/ui/auth.js");
    errorSpy.mockRestore();
  });

  it("sets serverModuleLoadFailed when the auth module lacks a register()", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => ({}));

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });

    expect(serverModuleLoadFailed.value).not.toBeNull();
    expect(serverModuleLoadFailed.value?.module).toBe("/ui/auth.js");
    errorSpy.mockRestore();
  });

  it("does not fail-closed when /ui/admin.js fails — auth stays healthy", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    let capturedCtx:
      | Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0]
      | null = null;
    const importModule = vi.fn(async (url: string) => {
      if (url === "/ui/auth.js") {
        return {
          register: (ctx) => {
            capturedCtx = ctx;
          },
        };
      }
      // /ui/admin.js — simulate a fetch / parse failure.
      throw new Error("admin bundle 502");
    });

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });
    // Flip admin identity so the lazy admin load fires.
    capturedCtx!.authStore.user.value = {
      id: 1,
      username: "admin",
      capabilities: { admin: true },
    };
    await flushAsync();

    // Fail-closed flag stays null — the app shell is NOT bricked.
    expect(serverModuleLoadFailed.value).toBeNull();
    // But the non-critical failure WAS recorded for diagnostics.
    expect(nonCriticalModuleLoadFailures.value).toHaveLength(1);
    expect(nonCriticalModuleLoadFailures.value[0].module).toBe("/ui/admin.js");

    errorSpy.mockRestore();
  });

  it("does nothing when loadConfig fails (no modules loaded)", async () => {
    mockLoadConfig.mockResolvedValue(false);
    mockConfig.value = null;

    const importModule = vi.fn(async () => ({ register: vi.fn() }));

    await bootServerModules(makeRouter(), { importModule });

    expect(importModule).not.toHaveBeenCalled();
    expect(serverModuleLoadFailed.value).toBeNull();
  });

  it("ctx.authStore exposes real refs — setHostUser-style writes flow back to OSS", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    let capturedCtx:
      | Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0]
      | null = null;
    const importModule = vi.fn(async () => ({
      register: (ctx) => {
        capturedCtx = ctx;
      },
    }));

    await bootServerModules(makeRouter(), { importModule });

    expect(capturedCtx).not.toBeNull();
    expect(isRef(capturedCtx!.authStore.user)).toBe(true);
    expect(isRef(capturedCtx!.authStore.token)).toBe(true);

    // Mirror what the server's auth module's setHostUser() helper does.
    capturedCtx!.authStore.user.value = {
      id: 7,
      username: "eva",
      capabilities: { admin: false },
    };

    const authStore = useAuthStore();
    expect(authStore.user?.id).toBe(7);
    expect(authStore.isAuthenticated).toBe(true);
  });

  it("invokes register() with a context exposing mountShell", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const stubComponent = { name: "FakeShell", template: "<div />" };
    const register = vi.fn((ctx) => {
      ctx.mountShell(stubComponent, ctx.contributorId);
    });

    const importModule = vi.fn(async () => ({ register }));

    await bootServerModules(makeRouter(), { importModule });

    expect(register).toHaveBeenCalledTimes(1);
    const ctx = register.mock.calls[0][0];
    expect(ctx.contributorId).toBe("server:auth");
    expect(typeof ctx.mountShell).toBe("function");
    expect(typeof ctx.unmountShells).toBe("function");
    expect(serverModuleShells.value).toHaveLength(1);
    expect(serverModuleShells.value[0].contributorId).toBe("server:auth");
  });
});
