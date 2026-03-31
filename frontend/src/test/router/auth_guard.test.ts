/**
 * Router auth guard tests
 *
 * Exercises the five main branches in the beforeEach guard defined in
 * src/router/index.ts:
 *
 *  1. Local mode — bypass all authentication
 *  2. Hybrid mode — loopback user resolved, remote falls through
 *  3. Enterprise / unauthenticated — redirect to /login
 *  4. Enterprise / authenticated — allow protected routes
 *  5. Admin route — require is_superuser
 *  6. Registration route — gated by registrationEnabled
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

const makeViewStub = (name: string) => ({
  default: {
    name,
    template: `<div>${name}</div>`,
  },
});

// ---------------------------------------------------------------------------
// Controllable mock refs — vi.hoisted() runs before mock factories so these
// values are available when the factory closure is created.
// ---------------------------------------------------------------------------
const { mockAppMode, mockRegistrationEnabled, mockLoadConfig } = vi.hoisted(
  () => ({
    mockAppMode: { value: "local" as string },
    mockRegistrationEnabled: { value: true as boolean },
    mockLoadConfig: vi.fn().mockResolvedValue(true),
  })
);

vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({
    config: { value: null },
    appMode: mockAppMode,
    loadConfig: mockLoadConfig,
    registrationEnabled: mockRegistrationEnabled,
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

vi.mock("@/views/LoginView.vue", () => makeViewStub("LoginView"));
vi.mock("@/views/RegisterView.vue", () => makeViewStub("RegisterView"));
vi.mock("@/views/project/ProjectContent.vue", () => makeViewStub("ProjectContent"));
vi.mock("@/views/data/DataContent.vue", () => makeViewStub("DataContent"));
vi.mock("@/views/workflow-builder/WorkflowBuilderContent.vue", () => makeViewStub("WorkflowBuilderContent"));
vi.mock("@/views/AdminView.vue", () => makeViewStub("AdminView"));

// ---------------------------------------------------------------------------
// Imports after mocks so the router picks up the mocked composable/api.
// ---------------------------------------------------------------------------
import api from "@/api/client";
import router from "@/router";
import { useAuthStore } from "@/stores/auth";

const HOME_PATH = "/project";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Navigate and return the resolved path. */
async function navigateTo(path: string): Promise<string> {
  await router.push(path);
  return router.currentRoute.value.path;
}

/** Seed a fully-authenticated user into a fresh auth store. */
function authenticateAs(opts: { is_superuser: boolean } = { is_superuser: false }) {
  const store = useAuthStore();
  store.token = "test-jwt-token";
  store.user = { id: 1, username: "testuser", is_superuser: opts.is_superuser };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Router auth guard", () => {
  beforeEach(async () => {
    // Prevent the auth store from calling fetchUser() on init.
    localStorage.clear();
    setActivePinia(createPinia());
    vi.clearAllMocks();

    // Default: local mode, registration enabled.
    mockAppMode.value = "local";
    mockRegistrationEnabled.value = true;

    // Reset router to a clean state.
    await router.push("/");
  });

  // -------------------------------------------------------------------------
  describe("local mode", () => {
    beforeEach(() => {
      mockAppMode.value = "local";
    });

    it("redirects /login → /", async () => {
      expect(await navigateTo("/login")).toBe(HOME_PATH);
    });

    it("redirects /register → /", async () => {
      expect(await navigateTo("/register")).toBe(HOME_PATH);
    });

    it("allows protected route without credentials", async () => {
      expect(await navigateTo("/workflow")).toBe("/workflow");
    });

    it("allows /data without credentials", async () => {
      expect(await navigateTo("/data")).toBe("/data");
    });
  });

  // -------------------------------------------------------------------------
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

    it("allows /login (public route)", async () => {
      expect(await navigateTo("/login")).toBe("/login");
    });

    it("allows /register when registrationEnabled is true", async () => {
      mockRegistrationEnabled.value = true;
      expect(await navigateTo("/register")).toBe("/register");
    });

    it("blocks /register → /login when registrationEnabled is false", async () => {
      mockRegistrationEnabled.value = false;
      expect(await navigateTo("/register")).toBe("/login");
    });

    it("fails closed when config load fails", async () => {
      mockLoadConfig.mockResolvedValueOnce(false);
      expect(await navigateTo("/workflow")).toBe("/login");
    });
  });

  // -------------------------------------------------------------------------
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

    it("redirects /login → / when already authenticated", async () => {
      expect(await navigateTo("/login")).toBe(HOME_PATH);
    });
  });

  // -------------------------------------------------------------------------
  describe("admin route (/admin)", () => {
    beforeEach(() => {
      mockAppMode.value = "enterprise";
    });

    it("redirects non-superuser → /", async () => {
      authenticateAs({ is_superuser: false });
      expect(await navigateTo("/admin")).toBe(HOME_PATH);
    });

    it("allows superuser to access /admin", async () => {
      authenticateAs({ is_superuser: true });
      expect(await navigateTo("/admin")).toBe("/admin");
    });

    it("redirects unauthenticated user → /login (not /)", async () => {
      // Unauthenticated always hits the login redirect before the admin check.
      expect(await navigateTo("/admin")).toBe("/login");
    });
  });

  // -------------------------------------------------------------------------
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
      vi.mocked(api.get).mockRejectedValueOnce(new Error("401 Unauthorized"));
      expect(await navigateTo("/workflow")).toBe("/login");
    });
  });
});
