import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/api/client", () => ({
  default: {
    get: apiGet,
  },
}));

describe("useBackendStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-02T12:00:00Z"));
    apiGet.mockReset();
    vi.resetModules();
  });

  async function flushHealthCheck(promise: Promise<void>) {
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1000);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1000);
    await promise;
  }

  it("keeps backend connected during short health probe failures", async () => {
    apiGet.mockRejectedValue(new Error("busy"));
    const { useBackendStatus } = await import("@/composables/useBackendStatus");
    const { backendConnected, checkBackendStatus } = useBackendStatus();

    await flushHealthCheck(checkBackendStatus());

    expect(backendConnected.value).toBe(true);
  });

  it("marks backend disconnected only after the grace window expires", async () => {
    apiGet.mockRejectedValue(new Error("busy"));
    const { useBackendStatus } = await import("@/composables/useBackendStatus");
    const { backendConnected, checkBackendStatus } = useBackendStatus();

    await flushHealthCheck(checkBackendStatus());
    expect(backendConnected.value).toBe(true);

    vi.setSystemTime(new Date("2026-06-02T12:01:01Z"));
    await flushHealthCheck(checkBackendStatus());

    expect(backendConnected.value).toBe(false);
  });
});
