/**
 * Idempotency-Key helpers for POST /workflows/{id}/execute.
 *
 * Two layers of protection against duplicate workflow runs:
 *
 *  1. Per-call `Idempotency-Key` header (server side, REM-2 + #161). A
 *     network blip that drops the response on the wire is replayed
 *     server-side instead of creating a second ExecutionRun.
 *
 *  2. Single-flight dedup keyed by workflow id + request payload
 *     (client side, REM-4).
 *     A second click while the first call is still in flight returns
 *     the SAME promise instead of making a second request. The Map
 *     entry is cleared the moment the promise settles, so a deliberate
 *     re-run after completion just works.
 *
 * Together: rapid double-clicks NEVER trigger two real executions, AND
 * a network retry of the single execution that did go out is safe.
 */

/**
 * Fresh RFC-4122 v4 UUID, served as the Idempotency-Key for a single
 * logical "execute" intent. ``crypto.randomUUID`` is available in every
 * supported browser (Chrome 92+, Firefox 95+, Safari 15.4+); the
 * fallback covers test environments where ``crypto`` may not be
 * defined (e.g. older jsdom).
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // RFC-4122 v4 fallback — math/random-based, fine for client-side
  // dedup tokens that aren't cryptographic identifiers.
  const r = (max: number) => Math.floor(Math.random() * max);
  const hex = (n: number, len: number) => n.toString(16).padStart(len, "0");
  const s4 = () => hex(r(0x10000), 4);
  return `${s4()}${s4()}-${s4()}-4${hex(r(0x1000), 3)}-${
    8 + r(4)
  }${hex(r(0x1000), 3)}-${s4()}${s4()}${s4()}`;
}

const inFlight = new Map<string, Promise<unknown>>();

/**
 * Coalesce concurrent calls under the same ``key`` into one shared
 * promise. The second caller during an in-flight call returns the
 * SAME promise — they observe the same resolution and the same
 * thrown error.
 *
 * The Map entry is cleared in a ``finally`` so a follow-up call after
 * the first settles starts fresh.
 */
export function singleFlight<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const promise = fn().finally(() => {
    if (inFlight.get(key) === promise) inFlight.delete(key);
  });
  inFlight.set(key, promise);
  return promise;
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export function requestScopedSingleFlightKey(prefix: string, payload: unknown): string {
  return `${prefix}:${stableStringify(payload)}`;
}

/** Test-only — drop every in-flight entry. */
export function _resetSingleFlightForTests(): void {
  inFlight.clear();
}
