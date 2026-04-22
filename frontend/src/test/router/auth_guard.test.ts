/**
 * Router auth guard tests (OSS-registered routes only).
 *
 * Post-v0.4.1 Phase 1b, /login /register /admin are registered by the
 * server-provided auth+admin modules at boot — not by OSS. These
 * tests cover only the OSS-owned guard behavior:
 *
 *  1. Local mode — bypass all authentication
 *  2. Hybrid mode — loopback user resolved via /auth/me, remote falls
 *     through to the (server-registered or absent) /login
 *  3. Enterprise / unauthenticated — redirect to /login
 *  4. Enterprise / authenticated — allow protected routes
 *  5. Config load failure — fail closed (redirect to /login)
 *
 * /login /register /admin behavior in the presence of the server
 * module is tested in server-frontend's own suite (commit 5).
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const makeViewStub = (name: string) => ({
  default: {
    name,
    template: `<div>${name}</div>`,
  },
});

const { mockAppMode, mockLoadConfig } = vi.hoisted(() => ({
  mockAppMode: { value: "local" as string },
  mockLoadConfig: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    config: { value: null },
    appMode: mockAppMode,
    loadConfig: mockLoadConfig,
  }),
}));

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/views/project/ProjectContent.vue", () => makeViewStub("ProjectContent"));
vi.mock("@/views/data/DataContent.vue", () => makeViewStub("DataContent"));
vi.mock("@/views/workflow-builder/WorkflowBuilderContent.vue", () => makeViewStub("WorkflowBuilderContent"));

import api from "@/api/client";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";

const HOME_PATH = "/project";

async function navigateTo(path: string): Promise<string> {
  await router.push(path);
  return router.currentRoute.value.path;
}

function authenticateAs(opts: { admin: boolean } = { admin: false }) {
  const store = useAuthStore();
  store.token = "test-jwt-token";
  store.user = {
    id: 1,
    username: "testuser",
    capabilities: { admin: opts.admin },
  };
}

describe("Router auth guard (OSS routes)", () => {
  beforeEach(async () => {
    localStorage.clear();
    setActivePinia(createPinia());
    vi.clearAllMocks();
    mockAppMode.value = "local";
    await router.push("/");
  });

  describe("local mode", () => {
    beforeEach(() => {
      mockAppMode.value = "local";
    });

    it("allows protected routes without credentials", async () => {
      expect(await navigateTo("/workflow")).toBe("/workflow");
    });

    it("allows /data without credentials", async () => {
      expect(await navigateTo("/data")).toBe("/data");
    });
  });

  describe("enterprise mode — unauthenticated", () => {
    beforeEach(() => {
      mockAppMode.value = "enterprise";
    });

    it("redirects /workflow → /login", async () => {
      expect(await navigateTo("/workflow")).toBe("/login");
    });

    it("redirects /data → /login", async () => {
      expect(await navigateTo("/data")).toBe("/login");
    });

    it("fails closed when config load fails", async () => {
      mockLoadConfig.mockResolvedValueOnce(false);
      expect(await navigateTo("/workflow")).toBe("/login");
    });
  });

  describe("enterprise mode — authenticated", () => {
    beforeEach(() => {
      mockAppMode.value = "enterprise";
      authenticateAs();
    });

    it("allows /workflow when authenticated", async () => {
      expect(await navigateTo("/workflow")).toBe("/workflow");
    });

    it("allows /data when authenticated", async () => {
      expect(await navigateTo("/data")).toBe("/data");
    });
  });

  describe("hybrid mode", () => {
    beforeEach(() => {
      mockAppMode.value = "hybrid";
    });

    it("loopback client: allows navigation when /auth/me resolves", async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 1, username: "implicit-user", is_active: true },
      });
      expect(await navigateTo("/workflow")).toBe("/workflow");
    });

    it("remote client: falls through to /login when /auth/me rejects", async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("401"));
      expect(await navigateTo("/workflow")).toBe("/login");
    });
  });
});
