import { afterEach, describe, expect, it } from "vitest";
import api from "@/api/client";
import { clearStoredApiKey, writeStoredApiKey } from "@/utils/authStorage";

afterEach(() => {
  localStorage.removeItem("token");
  clearStoredApiKey();
});

describe("HTTP credential authority", () => {
  it("sends only the bearer credential when both identities are available", async () => {
    localStorage.setItem("token", "alice-token");
    writeStoredApiKey("bob-key");
    await api.get("/auth/refresh", {
      headers: { "x-api-key": "explicit-bob-key" },
      adapter: async (config) => {
        expect(config.headers.get("Authorization")).toBe("Bearer alice-token");
        expect(config.headers.has("X-API-Key")).toBe(false);
        return { data: {}, status: 200, statusText: "OK", headers: {}, config };
      },
    });
  });
  it("retains API-key authentication when no bearer session exists", async () => {
    writeStoredApiKey("bob-key");
    await api.get("/auth/me", {
      adapter: async (config) => {
        expect(config.headers.get("X-API-Key")).toBe("bob-key");
        expect(config.headers.has("Authorization")).toBe(false);
        return { data: {}, status: 200, statusText: "OK", headers: {}, config };
      },
    });
  });
});
