import { getCurrentScope, onScopeDispose, watch } from "vue";

/** Pure Vue lifecycle contract shared by the host and separately built extensions. */
export const REQUEST_SCOPE_CONTRACT_VERSION = 1;

export type ScopeIdentity = string | number | boolean | null | undefined;

export interface ScopedRequestTicket {
  signal: AbortSignal;
  isCurrent(): boolean;
}

export interface ScopedRequestOptions {
  /** Accepted writes keep running when their view loses ownership. */
  abortOnInvalidate?: boolean;
}

/**
 * One request lane owned by a user/project/object identity.
 *
 * Cancellation is an optimization, not the correctness check: guard success,
 * error and finally effects with isCurrent(), even if the client ignores abort.
 * Synchronous invalidation also rejects A → B → A completions.
 */
export function useScopedRequest(
  identity: () => readonly ScopeIdentity[],
  onInvalidate?: () => void,
  options: ScopedRequestOptions = {},
) {
  let revision = 0;
  let disposed = false;
  let controller: AbortController | null = null;
  let latestTicket: ScopedRequestTicket | undefined;

  function invalidate(): void {
    revision += 1;
    if (options.abortOnInvalidate !== false) controller?.abort();
    controller = null;
    onInvalidate?.();
  }

  const stop = watch(
    () => [...identity()],
    (current, previous) => {
      // Replacing a route/object can retrigger the getter without changing its
      // selected identity fields. Do not invalidate an unrelated view change.
      if (
        current.length !== previous.length ||
        current.some((value, index) => !Object.is(value, previous[index]))
      )
        invalidate();
    },
    { flush: "sync" },
  );

  function begin(): ScopedRequestTicket {
    if (disposed) throw new DOMException("Request scope is disposed.", "AbortError");
    if (options.abortOnInvalidate !== false) controller?.abort();
    const active = new AbortController();
    controller = active;
    const generation = ++revision;
    const captured = [...identity()];
    latestTicket = {
      signal: active.signal,
      isCurrent() {
        if (disposed || active.signal.aborted || generation !== revision) return false;
        const current = identity();
        return (
          current.length === captured.length &&
          current.every((value, index) => Object.is(value, captured[index]))
        );
      },
    };
    return latestTicket;
  }

  /** Concurrent mutations share ownership, not cancellation of one another. */
  function capture(): ScopedRequestTicket {
    return latestTicket?.isCurrent() ? latestTicket : begin();
  }

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    stop();
    invalidate();
  }

  if (getCurrentScope()) onScopeDispose(dispose);
  return { begin, capture, invalidate, dispose };
}
