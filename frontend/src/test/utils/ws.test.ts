import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expireBrowserSession } from "@/api/client";
import { WS_SESSION_PROBE_TIMEOUT_MS } from "@/utils/ws";
import { clearStoredApiKey, writeStoredApiKey } from "@/utils/authStorage";
import { buildWsUrl, withCredentials, buildAuthMessage, resolveWsPolicyClose } from "@/utils/ws";

const { apiGet } = vi.hoisted(() => ({
  apiGet: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  expireBrowserSession: vi.fn(),
  default: { get: apiGet },
}));

describe("buildWsUrl", () => {
  it("derives ws:// URL from window.location in production", () => {
    // happy-dom provides window.location as http://localhost:3000
    const url = buildWsUrl();
    expect(url).toMatch(/^wss?:\/\//);
    expect(url).toContain("/ws");
  });

  it("returns URL ending with /ws", () => {
    const url = buildWsUrl();
    expect(new URL(url).pathname).toBe("/ws");
  });
});

describe("withCredentials", () => {
  it("returns the URL unchanged (credentials sent via first message)", () => {
    const url = "ws://localhost:8000/ws";
    expect(withCredentials(url)).toBe(url);
  });
});

describe("buildAuthMessage", () => {
  beforeEach(() => {
    localStorage.clear();
    clearStoredApiKey();
  });

  it("returns JSON with null token and api_key when nothing stored", () => {
    const msg = JSON.parse(buildAuthMessage());
    expect(msg).toEqual({
      type: "authenticate",
      token: null,
      api_key: null,
    });
  });

  it("includes token from localStorage", () => {
    localStorage.setItem("token", "jwt-123");
    const msg = JSON.parse(buildAuthMessage());
    expect(msg.type).toBe("authenticate");
    expect(msg.token).toBe("jwt-123");
    expect(msg.api_key).toBeNull();
  });

  it("includes api_key from runtime auth storage", () => {
    writeStoredApiKey("key-456");
    const msg = JSON.parse(buildAuthMessage());
    expect(msg.token).toBeNull();
    expect(msg.api_key).toBe("key-456");
  });

  it("uses only the explicit API key when a browser token is also stored", () => {
    localStorage.setItem("token", "jwt-123");
    writeStoredApiKey("key-456");
    const msg = JSON.parse(buildAuthMessage());
    expect(msg.token).toBeNull();
    expect(msg.api_key).toBe("key-456");
  });
});

describe("resolveWsPolicyClose", () => {

  beforeEach(() => {
    localStorage.clear();
    clearStoredApiKey();
    apiGet.mockReset();
    vi.mocked(expireBrowserSession).mockClear();
    vi.useFakeTimers();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("keeps a valid JWT when the policy close was not an auth rejection", async () => {
    localStorage.setItem("token", "jwt-still-valid");
    apiGet.mockResolvedValue({ data: { id: 1 } });

    const resolution = await resolveWsPolicyClose();

    expect(resolution).toBe("session-confirmed");
    expect(localStorage.getItem("token")).toBe("jwt-still-valid");
    expect(apiGet).toHaveBeenCalledWith("/auth/me", expect.objectContaining({
      signal: expect.any(AbortSignal), timeout: WS_SESSION_PROBE_TIMEOUT_MS,
    }));
  });

  it("keeps the JWT when the session probe itself is unreachable", async () => {
    localStorage.setItem("token", "jwt-still-valid");
    apiGet.mockRejectedValue(new Error("Network Error"));

    const resolution = await resolveWsPolicyClose();

    expect(resolution).toBe("session-unconfirmed");
    expect(localStorage.getItem("token")).toBe("jwt-still-valid");
  });

  it("reports a rejected session only on an HTTP 401", async () => {
    localStorage.setItem("token", "jwt-expired");
    apiGet.mockResolvedValue({ status: 401, data: {} });

    const resolution = await resolveWsPolicyClose();

    expect(expireBrowserSession).toHaveBeenCalledOnce();
    expect(apiGet.mock.calls[0][1].validateStatus(401)).toBe(true);
    expect(resolution).toBe("session-rejected");
  });

  it("drops a stale JWT only when an explicit API key can take over", async () => {
    localStorage.setItem("token", "jwt-stale");
    writeStoredApiKey("key-456");

    const resolution = await resolveWsPolicyClose();

    expect(resolution).toBe("retry-with-api-key");
    expect(localStorage.getItem("token")).toBeNull();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("is terminal when no credentials are stored", async () => {
    const resolution = await resolveWsPolicyClose();

    expect(resolution).toBe("no-credentials");
    expect(apiGet).not.toHaveBeenCalled();
  });
  it("bounds a stalled probe, aborts HTTP, and preserves the token", async () => {
    localStorage.setItem("token", "valid");
    apiGet.mockImplementation(() => new Promise(() => {}));
    const result = resolveWsPolicyClose();
    await vi.advanceTimersByTimeAsync(WS_SESSION_PROBE_TIMEOUT_MS);
    expect(await result).toBe("session-unconfirmed");
    expect(apiGet.mock.calls[0][1].signal.aborted).toBe(true);
    expect(localStorage.getItem("token")).toBe("valid");
    expect(expireBrowserSession).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels promptly and ignores a late 401", async () => {
    localStorage.setItem("token", "valid");
    let finish!: (response: unknown) => void;
    apiGet.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const controller = new AbortController();
    const result = resolveWsPolicyClose(controller.signal);
    controller.abort();
    expect(await result).toBe("cancelled");
    finish({ status: 401 });
    await vi.advanceTimersByTimeAsync(0);
    expect(expireBrowserSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("token")).toBe("valid");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cannot expire a replacement credential", async () => {
    localStorage.setItem("token", "old");
    let finish!: (response: unknown) => void;
    apiGet.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const result = resolveWsPolicyClose();
    localStorage.setItem("token", "new");
    finish({ status: 401 });
    expect(await result).toBe("session-unconfirmed");
    expect(expireBrowserSession).not.toHaveBeenCalled();
    expect(localStorage.getItem("token")).toBe("new");
  });

});
