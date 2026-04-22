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

// Must import after mocks are set up
import { useAuthStore } from "@/stores/auth";
import router from "@/router";

describe("Auth Store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("initializes unauthenticated", () => {
    const store = useAuthStore();
    expect(store.isAuthenticated).toBe(false);
    expect(store.user).toBeNull();
    expect(store.loginError).toBeNull();
  });

  describe("login", () => {
    it("stores token and fetches user on success", async () => {
      vi.mocked(api.post).mockResolvedValueOnce({
        data: { access_token: "jwt-token" },
      });
      vi.mocked(api.get).mockResolvedValueOnce({
        data: { id: 1, username: "alice", capabilities: { admin: false } },
      });
      const store = useAuthStore();

      await store.login("alice", "pass");

      expect(api.post).toHaveBeenCalledWith("/auth/login", expect.any(FormData));
      expect(store.token).toBe("jwt-token");
      expect(localStorage.getItem("token")).toBe("jwt-token");
      expect(store.user?.username).toBe("alice");
      expect(router.push).toHaveBeenCalledWith("/");
    });

    it("sets loginError on failure", async () => {
      vi.mocked(api.post).mockRejectedValueOnce({
        response: { data: { detail: "Incorrect username or password" } },
      });
      const store = useAuthStore();

      await store.login("alice", "wrong");

      expect(store.loginError).toBe("Incorrect username or password");
      expect(store.token).toBeNull();
    });
  });

  describe("register", () => {
    it("sets success message and navigates to login", async () => {
      vi.mocked(api.post).mockResolvedValueOnce({});
      const store = useAuthStore();

      await store.register("bob", "pass123", "enterprise-pw");

      expect(api.post).toHaveBeenCalledWith(
        "/auth/register",
        { username: "bob", password: "pass123" },
        { headers: { "X-Enterprise-Password": "enterprise-pw" } },
      );
      expect(store.registerSuccess).toContain("Account created");
      expect(router.push).toHaveBeenCalledWith("/login");
    });

    it("sets registerError on failure", async () => {
      vi.mocked(api.post).mockRejectedValueOnce({
        response: { data: { detail: "Username taken" } },
      });
      const store = useAuthStore();

      await store.register("bob", "pass", "pw");

      expect(store.registerError).toBe("Username taken");
    });
  });

  describe("logout", () => {
    it("clears state and navigates to /login", () => {
      const store = useAuthStore();
      store.token = "jwt";
      store.user = { id: 1, username: "a", capabilities: { admin: false } };
      localStorage.setItem("token", "jwt");

      store.logout();

      expect(store.token).toBeNull();
      expect(store.user).toBeNull();
      expect(localStorage.getItem("token")).toBeNull();
      expect(router.push).toHaveBeenCalledWith("/login");
    });
  });

  describe("clearCredentials", () => {
    it("removes token and api_key without navigation", () => {
      localStorage.setItem("api_key", "key");
      const store = useAuthStore();
      store.token = "jwt";
      localStorage.setItem("token", "jwt");

      store.clearCredentials();

      expect(store.token).toBeNull();
      expect(localStorage.getItem("token")).toBeNull();
      expect(localStorage.getItem("api_key")).toBeNull();
      expect(router.push).not.toHaveBeenCalled();
    });
  });

  describe("changePassword", () => {
    it("returns success on valid change", async () => {
      vi.mocked(api.put).mockResolvedValueOnce({});
      const store = useAuthStore();

      const result = await store.changePassword("old", "new");

      expect(result).toEqual({ success: true });
    });

    it("returns error message on failure", async () => {
      vi.mocked(api.put).mockRejectedValueOnce({
        response: { data: { detail: "Current password incorrect" } },
      });
      const store = useAuthStore();

      const result = await store.changePassword("wrong", "new");

      expect(result).toEqual({ success: false, error: "Current password incorrect" });
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
  });
});
