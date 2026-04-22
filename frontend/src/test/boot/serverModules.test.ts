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

const { mockLoadConfig, mockConfig } = vi.hoisted(() => ({
  mockLoadConfig: vi.fn<[], Promise<boolean>>(),
  mockConfig: { value: null as Record<string, unknown> | null },
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    config: mockConfig,
    loadConfig: mockLoadConfig,
  }),
}));

import {
  __resetServerModulesForTests,
  bootServerModules,
  nonCriticalModuleLoadFailures,
  serverModuleLoadFailed,
  serverModuleShells,
  type ImportModuleFn,
} from "@/boot/serverModules";
import { useAuthStore } from "@/stores/auth";

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
    mockConfig.value = null;
    mockLoadConfig.mockReset();
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

  it("lazy-loads /ui/admin.js when host identity is set via the context ref", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    // Capture the ctx the auth module's register() would see so we can
    // drive identity through the SAME path the real server bundle uses
    // (ctx.authStore.user.value = …), not by mutating Pinia directly.
    let capturedCtx: Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0] | null = null;
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

    let capturedCtx: Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0] | null = null;
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

    let capturedCtx: Parameters<NonNullable<Awaited<ReturnType<ImportModuleFn>>["register"]>>[0] | null = null;
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
