import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";

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
  });

  it("initializes unauthenticated", () => {
    const store = useAuthStore();
    expect(store.isAuthenticated).toBe(false);
    expect(store.user).toBeNull();
    expect(store.token).toBeNull();
  });

  describe("clearCredentials", () => {
    it("removes token and api_key and drops user without navigation", () => {
      localStorage.setItem("api_key", "key");
      const store = useAuthStore();
      store.token = "jwt";
      localStorage.setItem("token", "jwt");
      store.user = { id: 1, username: "a", capabilities: { admin: false } };

      store.clearCredentials();

      expect(store.token).toBeNull();
      expect(store.user).toBeNull();
      expect(localStorage.getItem("token")).toBeNull();
      expect(localStorage.getItem("api_key")).toBeNull();
    });
  });

  describe("initHybridUser", () => {
    it("accepts minimal actor payload from OSS /auth/me", async () => {
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 7, username: "implicit-user", is_active: true },
      });
      const store = useAuthStore();

      await store.initHybridUser();

      expect(api.get).toHaveBeenCalledWith("/auth/me");
      expect(store.user).toEqual({ id: 7, username: "implicit-user", is_active: true });
      expect(store.isAuthenticated).toBe(true);
    });

    it("clears stale tokens before calling /auth/me", async () => {
      localStorage.setItem("token", "stale-jwt");
      localStorage.setItem("api_key", "stale-key");
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 7, username: "implicit-user", is_active: true },
      });
      const store = useAuthStore();

      await store.initHybridUser();

      expect(localStorage.getItem("token")).toBeNull();
      expect(localStorage.getItem("api_key")).toBeNull();
    });

    it("tolerates /auth/me failure (warns, leaves user null)", async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("remote, no loopback"));
      const store = useAuthStore();

      await store.initHybridUser();

      expect(store.user).toBeNull();
    });
  });
});
