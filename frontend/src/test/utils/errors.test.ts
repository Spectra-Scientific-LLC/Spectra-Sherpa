import { describe, expect, it } from "vitest";
import axios, { AxiosError, type AxiosResponse } from "axios";
import { getErrorMessage, isDemoUpgradeError, getDemoUpgradeInfo } from "@/utils/errors";

function makeAxiosError(
  status: number,
  data: unknown,
  message = "Request failed",
): AxiosError {
  const error = new AxiosError(message);
  error.response = {
    status,
    statusText: "Error",
    headers: {},
    config: {} as any,
    data,
  } as AxiosResponse;
  return error;
}

describe("getErrorMessage", () => {
  it("extracts detail string from axios error", () => {
    const err = makeAxiosError(400, { detail: "Invalid input" });
    expect(getErrorMessage(err)).toBe("Invalid input");
  });

  it("extracts message field when detail is missing", () => {
    const err = makeAxiosError(500, { message: "Server error" });
    expect(getErrorMessage(err)).toBe("Server error");
  });

  it("extracts error field as fallback", () => {
    const err = makeAxiosError(500, { error: "Something broke" });
    expect(getErrorMessage(err)).toBe("Something broke");
  });

  it("falls back to axios message", () => {
    const err = makeAxiosError(500, {}, "Network Error");
    expect(getErrorMessage(err)).toBe("Network Error");
  });

  it("returns fallback for empty axios error", () => {
    const err = new AxiosError();
    expect(getErrorMessage(err)).toBe("An unexpected error occurred");
  });

  it("returns custom fallback", () => {
    expect(getErrorMessage(null, "Custom fallback")).toBe("Custom fallback");
  });

  it("handles Error instances", () => {
    expect(getErrorMessage(new Error("plain error"))).toBe("plain error");
  });

  it("handles string errors", () => {
    expect(getErrorMessage("string error")).toBe("string error");
  });

  it("handles object detail (demo 403)", () => {
    const err = makeAxiosError(403, {
      detail: { message: "Upgrade required", upgrade_url: "https://example.com" },
    });
    expect(getErrorMessage(err)).toBe("Upgrade required");
  });

  it("returns fallback for non-error values", () => {
    expect(getErrorMessage(42)).toBe("An unexpected error occurred");
    expect(getErrorMessage(undefined)).toBe("An unexpected error occurred");
  });
});

describe("isDemoUpgradeError", () => {
  it("returns true for 403 with upgrade_url in detail", () => {
    const err = makeAxiosError(403, {
      detail: { upgrade_url: "https://pricing", message: "Upgrade" },
    });
    expect(isDemoUpgradeError(err)).toBe(true);
  });

  it("returns true for 429 with upgrade_url at top level", () => {
    const err = makeAxiosError(429, {
      upgrade_url: "https://pricing",
      message: "Rate limited",
    });
    expect(isDemoUpgradeError(err)).toBe(true);
  });

  it("returns false for non-axios errors", () => {
    expect(isDemoUpgradeError(new Error("nope"))).toBe(false);
  });

  it("returns false for 403 without upgrade_url", () => {
    const err = makeAxiosError(403, { detail: "Forbidden" });
    expect(isDemoUpgradeError(err)).toBe(false);
  });

  it("returns false for non-403/429 status", () => {
    const err = makeAxiosError(500, { upgrade_url: "https://pricing" });
    expect(isDemoUpgradeError(err)).toBe(false);
  });
});

describe("getDemoUpgradeInfo", () => {
  it("extracts info from 403 detail object", () => {
    const err = makeAxiosError(403, {
      detail: {
        message: "Feature locked",
        upgrade_url: "https://pricing",
        available_plans: ["pro", "team"],
        blocked_capability: "sherpa_chat",
      },
    });
    const info = getDemoUpgradeInfo(err);
    expect(info).toEqual({
      message: "Feature locked",
      upgradeUrl: "https://pricing",
      availablePlans: ["pro", "team"],
      blockedCapability: "sherpa_chat",
    });
  });

  it("extracts info from 429 top-level fields", () => {
    const err = makeAxiosError(429, {
      message: "Rate limited",
      upgrade_url: "https://pricing",
      available_plans: ["pro"],
    });
    const info = getDemoUpgradeInfo(err);
    expect(info).toEqual({
      message: "Rate limited",
      upgradeUrl: "https://pricing",
      availablePlans: ["pro"],
    });
  });

  it("returns null for non-upgrade errors", () => {
    expect(getDemoUpgradeInfo(new Error("nope"))).toBeNull();
    expect(getDemoUpgradeInfo(makeAxiosError(400, { detail: "Bad" }))).toBeNull();
  });
});
