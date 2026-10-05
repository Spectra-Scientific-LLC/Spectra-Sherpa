import { describe, expect, it, vi } from "vitest";

import { jwtExpiryMilliseconds, sessionExpiryMinutesRemaining } from "@/utils/sessionExpiry";

const tokenWithExpiry = (seconds: number): string => {
  const payload = window
    .btoa(JSON.stringify({ sub: "scientist", exp: seconds }))
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `header.${payload}.signature`;
};

describe("session expiry warning support", () => {
  it("reads expiry only as a scheduling hint", () => {
    const token = tokenWithExpiry(1_800_000_300);
    expect(jwtExpiryMilliseconds(token)).toBe(1_800_000_300_000);
    expect(sessionExpiryMinutesRemaining(token, 1_800_000_000_000)).toBe(5);
  });

  it("fails quietly for malformed or non-expiring credentials", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(jwtExpiryMilliseconds("not-a-jwt")).toBeNull();
    expect(jwtExpiryMilliseconds(tokenWithExpiry(Number.NaN))).toBeNull();
    expect(sessionExpiryMinutesRemaining(null)).toBeNull();
  });
});
