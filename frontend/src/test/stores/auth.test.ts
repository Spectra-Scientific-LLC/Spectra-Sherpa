import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { clearStoredApiKey, readStoredApiKey, writeStoredApiKey } from "@/utils/authStorage";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/router", () => ({
  default: { push: vi.fn() },
}));

import { useAuthStore } from "@/stores/auth";

describe("OSS auth store (identity-only, post-v0.4.1)", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
    clearStoredApiKey();
  });

  it("initializes unauthenticated", () => {
    const store = useAuthStore();
    expect(store.isAuthenticated).toBe(false);
    expect(store.user).toBeNull();
    expect(store.token).toBeNull();
  });

  describe("clearCredentials", () => {
    it("removes token and api_key and drops user without navigation", async () => {
      writeStoredApiKey("key");
      const store = useAuthStore();
      store.token = "jwt";
      localStorage.setItem("token", "jwt");
      store.user = { id: 1, username: "a", capabilities: { admin: false } };

      await store.clearCredentials();

      expect(store.token).toBeNull();
      expect(store.user).toBeNull();
      expect(localStorage.getItem("token")).toBeNull();
      expect(localStorage.getItem("api_key")).toBeNull();
    });
  });

  describe("initializeActor", () => {
    it("accepts minimal actor payload from OSS /auth/me", async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 7, username: "implicit-user", is_active: true },
      });
      const store = useAuthStore();

      await store.initializeActor();

      expect(api.get).toHaveBeenCalledWith("/auth/me", { signal: expect.any(AbortSignal) });
      expect(store.user).toEqual({ id: 7, username: "implicit-user", is_active: true });
      expect(store.isAuthenticated).toBe(true);
    });

    it("preserves credentials for server validation when resolving a product actor", async () => {
      localStorage.setItem("token", "stale-jwt");
      writeStoredApiKey("stale-key");
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 7, username: "implicit-user", is_active: true },
      });
      const store = useAuthStore();

      await store.initializeActor();

      expect(localStorage.getItem("token")).toBe("stale-jwt");
      expect(readStoredApiKey()).toBe("stale-key");
    });

    it("tolerates /auth/me failure (warns, leaves user null)", async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("remote, no loopback"));
      const store = useAuthStore();

      await store.initializeActor();

      expect(store.user).toBeNull();
    });
  });

  describe("session identity versus renewable credentials", () => {
    function signedIn() {
      const auth = useAuthStore();
      auth.token = "original";
      localStorage.setItem("token", "original");
      auth.user = { id: 7, username: "first" };
      return auth;
    }
    it("only an acknowledged renewal preserves the session revision", async () => {
      const auth = signedIn();
      const captured = auth.captureSession();
      expect(await auth.acceptRenewal(captured, "renewed")).toBe(true);
      expect(auth.sessionRevision).toBe(captured.revision);
      expect(auth.token).toBe("renewed");
      auth.token = "another-login-same-account";
      expect(auth.sessionRevision).toBeGreaterThan(captured.revision);
    });
    it.each(["logout", "actor", "token", "aba", "storage"])("rejects a late refresh after %s changes", async kind => {
      const auth = signedIn();
      const captured = auth.captureSession();
      if (kind === "logout") await auth.clearCredentials();
      if (kind === "actor") auth.user = { id: 8, username: "second" };
      if (kind === "token") auth.token = "replacement";
      if (kind === "aba") { auth.token = "other"; auth.token = "original"; }
      if (kind === "storage") localStorage.setItem("token", "another-tab");
      const before = localStorage.getItem("token");
      expect(await auth.acceptRenewal(captured, "late")).toBe(false);
      expect(localStorage.getItem("token")).toBe(before);
    });
    it("leaves the current credential and identity intact when persistence fails", async () => {
      const auth = signedIn();
      const captured = auth.captureSession();
      const write = vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => { throw new Error("full"); });
      await expect(auth.acceptRenewal(captured, "renewed")).rejects.toThrow("full");
      expect(auth.token).toBe("original");
      expect(auth.sessionRevision).toBe(captured.revision);
      write.mockRestore();
    });
    it("invalidates a different tab's replacement or logout before it can reuse the actor", () => {
      const auth = signedIn();
      const revision = auth.sessionRevision;
      localStorage.setItem("token", "another-account");
      window.dispatchEvent(new StorageEvent("storage", { key: "token", newValue: "another-account" }));
      expect(auth.token).toBe("another-account");
      expect(auth.user).toBeNull();
      expect(auth.sessionRevision).toBeGreaterThan(revision);
    });
  });
});
