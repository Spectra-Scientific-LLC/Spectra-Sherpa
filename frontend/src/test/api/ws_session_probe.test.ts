import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AxiosResponse } from "axios";
import api from "@/api/client";
import { resolveWsPolicyClose } from "@/utils/ws";

const originalAdapter = api.defaults.adapter;
const originalUrl = window.location.href;

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("token", "valid-session");
  window.history.replaceState(null, "", "/workflow?project=7");
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  localStorage.clear();
  window.history.replaceState(null, "", originalUrl);
});

describe("session probe through the real HTTP interceptors", () => {
  it("expires the current session for a confirmed 401", async () => {
    api.defaults.adapter = async (config) => {
      expect(config.validateStatus?.(401)).toBe(true);
      expect(config.headers.get("Authorization")).toBe("Bearer valid-session");
      return { data: {}, status: 401, statusText: "Unauthorized", headers: {}, config };
    };
    expect(await resolveWsPolicyClose()).toBe("session-rejected");
    expect(localStorage.getItem("token")).toBeNull();
    expect(window.location.href).toContain("/login?reason=session-expired");
  });

  it("keeps the replacement session when the old probe returns 401", async () => {
    api.defaults.adapter = async (config) => {
      localStorage.setItem("token", "replacement-session");
      return { data: {}, status: 401, statusText: "Unauthorized", headers: {}, config };
    };
    expect(await resolveWsPolicyClose()).toBe("session-unconfirmed");
    expect(localStorage.getItem("token")).toBe("replacement-session");
    expect(window.location.pathname).toBe("/workflow");
  });

  it("does not let a cancelled probe trigger the global 401 interceptor", async () => {
    let finish!: () => void;
    let started!: () => void;
    const ready = new Promise<void>((resolve) => { started = resolve; });
    api.defaults.adapter = (config) => new Promise<AxiosResponse>((resolve) => {
      finish = () => resolve({ data: {}, status: 401, statusText: "Unauthorized", headers: {}, config });
      started();
    });
    const controller = new AbortController();
    const pending = resolveWsPolicyClose(controller.signal);
    await ready;
    controller.abort();
    expect(await pending).toBe("cancelled");
    finish();
    // Let the actual Axios response/error interceptors process the late reply.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(localStorage.getItem("token")).toBe("valid-session");
    expect(window.location.pathname).toBe("/workflow");
  });

  it("preserves the existing logout behavior for ordinary HTTP 401s", async () => {
    await expect(api.get("/auth/me", {
      adapter: async (config) => Promise.reject({ response: { status: 401 }, config }),
    })).rejects.toBeDefined();
    expect(localStorage.getItem("token")).toBeNull();
    expect(window.location.href).toContain("/login?reason=session-expired");
  });
});
