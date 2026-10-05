import { toRaw } from "vue";

export function resolveNodeDetailPayload(
  inMemory: unknown,
  serializedFallback: string | null,
): Record<string, unknown> | null {
  const source = inMemory ?? serializedFallback;
  if (source == null) return null;
  const payload = typeof source === "string" ? JSON.parse(source) : source;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new TypeError("node detail payload must be an object");
  }
  return payload as Record<string, unknown>;
}

/**
 * Copy the closed, JSON-shaped parameter object without asking the browser to
 * clone a Vue proxy. `structuredClone(reactive(...))` raises DataCloneError in
 * current browsers even when every underlying parameter is serializable.
 */
export function cloneNodeDetailParams<T extends Record<string, unknown>>(params: T): T {
  // Object spreads unwrap only the outer container: nested arrays/objects
  // can still be proxies. Copy every level of the closed parameter grammar.
  const seen = new WeakMap<object, object>();
  const copy = (value: unknown): unknown => {
    if (value === null || typeof value !== "object") return value;
    const raw = toRaw(value);
    const existing = seen.get(raw);
    if (existing) return existing;
    const result: Record<string, unknown> | unknown[] = Array.isArray(raw)
      ? new Array(raw.length)
      : {};
    seen.set(raw, result);
    for (const [key, child] of Object.entries(raw)) {
      Object.defineProperty(result, key, {
        value: copy(child),
        enumerable: true,
        writable: true,
        configurable: true,
      });
    }
    return result;
  };
  return copy(params) as T;
}
