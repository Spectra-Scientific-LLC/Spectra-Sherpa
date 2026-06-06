import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  _resetSingleFlightForTests,
  newIdempotencyKey,
  requestScopedSingleFlightKey,
  singleFlight,
} from "@/utils/idempotency";

describe("newIdempotencyKey", () => {
  it("produces RFC-4122 v4 shaped strings", () => {
    const key = newIdempotencyKey();
    expect(key).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("never repeats", () => {
    const keys = new Set(Array.from({ length: 200 }, () => newIdempotencyKey()));
    expect(keys.size).toBe(200);
  });
});

describe("singleFlight", () => {
  beforeEach(() => {
    _resetSingleFlightForTests();
  });

  it("coalesces concurrent calls under the same key into one promise", async () => {
    const fn = vi.fn().mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve("result"), 10)),
    );

    const [a, b, c] = await Promise.all([
      singleFlight("k1", fn),
      singleFlight("k1", fn),
      singleFlight("k1", fn),
    ]);

    expect(fn).toHaveBeenCalledTimes(1);
    expect(a).toBe("result");
    expect(b).toBe("result");
    expect(c).toBe("result");
  });

  it("releases the key after the promise settles so re-runs work", async () => {
    const fn = vi.fn().mockResolvedValue("ok");

    await singleFlight("k2", fn);
    await singleFlight("k2", fn);

    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("releases the key on rejection too", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce("recovered");

    await expect(singleFlight("k3", fn)).rejects.toThrow("boom");
    const result = await singleFlight("k3", fn);

    expect(fn).toHaveBeenCalledTimes(2);
    expect(result).toBe("recovered");
  });

  it("scopes by key — distinct keys do NOT coalesce", async () => {
    const fn = vi.fn().mockResolvedValue("x");

    await Promise.all([
      singleFlight("ka", fn),
      singleFlight("kb", fn),
      singleFlight("kc", fn),
    ]);

    expect(fn).toHaveBeenCalledTimes(3);
  });
});

describe("requestScopedSingleFlightKey", () => {
  it("is stable for object key order but differs by payload content", () => {
    const a = requestScopedSingleFlightKey("execute:1", {
      initial_data: { b: 2, a: 1 },
    });
    const b = requestScopedSingleFlightKey("execute:1", {
      initial_data: { a: 1, b: 2 },
    });
    const c = requestScopedSingleFlightKey("execute:1", {
      initial_data: { a: 1, b: 3 },
    });

    expect(a).toBe(b);
    expect(a).not.toBe(c);
  });
});
