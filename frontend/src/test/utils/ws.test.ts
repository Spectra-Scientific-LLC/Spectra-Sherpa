import { beforeEach, describe, expect, it } from "vitest";
import { buildWsUrl, withCredentials, buildAuthMessage } from "@/utils/ws";

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

  it("includes api_key from localStorage", () => {
    localStorage.setItem("api_key", "key-456");
    const msg = JSON.parse(buildAuthMessage());
    expect(msg.token).toBeNull();
    expect(msg.api_key).toBe("key-456");
  });

  it("includes both when both present", () => {
    localStorage.setItem("token", "jwt-123");
    localStorage.setItem("api_key", "key-456");
    const msg = JSON.parse(buildAuthMessage());
    expect(msg.token).toBe("jwt-123");
    expect(msg.api_key).toBe("key-456");
  });
});
