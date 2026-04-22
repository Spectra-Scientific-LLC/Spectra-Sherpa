/**
 * Boot-time loader coverage.
 *
 * Exercises the four paths the OSS shell depends on when resolving
 * which server-provided frontend modules to load:
 *
 *   1. features.authUI=true  → /ui/auth.js loaded eagerly
 *   2. features absent       → neither module loads (local-mode default)
 *   3. admin capability      → /ui/admin.js lazy-loads after identity
 *   4. fetch/register throws → serverModuleLoadFailed is set
 *
 * The boot module exports an injectable `importModule` so tests can
 * avoid Vite's network-only dynamic import; each test wires its own
 * fake registrar through that seam.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
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

  it("lazy-loads /ui/admin.js when user gains capabilities.admin", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => ({ register: vi.fn() }));

    await bootServerModules(makeRouter(), { importModule });
    const urlsBeforeAdmin = importModule.mock.calls.map((c) => c[0]);
    expect(urlsBeforeAdmin).not.toContain("/ui/admin.js");

    const authStore = useAuthStore();
    authStore.user = {
      id: 42,
      username: "admin",
      capabilities: { admin: true },
    };
    await nextTick();
    // The dynamic import is scheduled by the watcher callback; give it
    // another tick for the promise chain inside loadAndRegister to flush.
    await Promise.resolve();
    await Promise.resolve();

    const urlsAfterAdmin = importModule.mock.calls.map((c) => c[0]);
    expect(urlsAfterAdmin).toContain("/ui/admin.js");
  });

  it("sets serverModuleLoadFailed when auth module import throws", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => {
      throw new Error("network unreachable");
    });

    // Suppress the expected console.error so test output stays clean.
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });

    expect(serverModuleLoadFailed.value).not.toBeNull();
    expect(serverModuleLoadFailed.value?.module).toBe("/ui/auth.js");
    errorSpy.mockRestore();
  });

  it("sets serverModuleLoadFailed when the module lacks a register()", async () => {
    mockConfig.value = { mode: "enterprise", features: { authUI: true } };
    mockLoadConfig.mockResolvedValue(true);

    const importModule = vi.fn(async () => ({}));

    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    await bootServerModules(makeRouter(), { importModule });

    expect(serverModuleLoadFailed.value).not.toBeNull();
    expect(serverModuleLoadFailed.value?.module).toBe("/ui/auth.js");
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
