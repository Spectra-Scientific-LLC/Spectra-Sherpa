import { getCurrentInstance, onDeactivated, onScopeDispose, readonly, shallowRef } from "vue";

export interface ConfirmActionOptions {
  /** Dialog title, e.g. "Delete API key". */
  title: string;
  /** One or two sentences: what will happen, and what is kept. */
  message: string;
  /** Names the action, e.g. "Delete". Never a bare "OK". */
  acceptLabel: string;
  /** Styles the accept button as destructive. */
  destructive?: boolean;
}

interface PendingConfirmation {
  options: ConfirmActionOptions;
  resolve: (accepted: boolean) => void;
}

const pending = shallowRef<PendingConfirmation | null>(null);

/**
 * Ask the user to confirm an action in the app's own dialog.
 *
 * Resolves true only when the accept button is chosen; Cancel, Escape and the
 * close button all resolve false. While one confirmation is open, another is
 * refused (resolves false) rather than queued, so a second click can never
 * accept an action the user has not read. Aborting `signal` closes the dialog
 * and resolves false: the request never outlives the context that made it.
 *
 * Components use `useConfirmAction()`, which ties the signal to their
 * lifetime. Callers capture their target before awaiting and re-check that it
 * still exists afterwards.
 */
export function confirmAction(
  options: ConfirmActionOptions,
  context: { signal?: AbortSignal } = {},
): Promise<boolean> {
  const { signal } = context;
  if (pending.value || signal?.aborted) return Promise.resolve(false);
  return new Promise((resolve) => {
    const request: PendingConfirmation = { options, resolve };
    pending.value = request;
    signal?.addEventListener(
      "abort",
      () => {
        if (pending.value === request) settleConfirmation(false);
      },
      { once: true },
    );
  });
}

/** Settle the open confirmation, once. Used by ConfirmActionDialog. */
export function settleConfirmation(accepted: boolean): void {
  const current = pending.value;
  if (!current) return;
  pending.value = null;
  current.resolve(accepted);
}

/** Close any open confirmation as declined, e.g. when the signed-in user changes. */
export function cancelPendingConfirmation(): void {
  settleConfirmation(false);
}

export const pendingConfirmation = readonly(pending);

/**
 * `confirmAction` owned by the calling component (or effect scope).
 *
 * Unmounting or deactivating the owner closes its open confirmation as
 * declined, so a destructive action can never be accepted after the page that
 * asked for it has gone. Once the owner is unmounted, further requests are
 * refused.
 */
export function useConfirmAction(): (options: ConfirmActionOptions) => Promise<boolean> {
  let owned: AbortController | null = null;
  let disposed = false;
  const cancelOwned = () => {
    owned?.abort();
    owned = null;
  };
  onScopeDispose(() => {
    disposed = true;
    cancelOwned();
  });
  if (getCurrentInstance()) onDeactivated(cancelOwned);

  return async (options) => {
    if (disposed || owned) return false;
    const controller = new AbortController();
    owned = controller;
    try {
      return await confirmAction(options, { signal: controller.signal });
    } finally {
      if (owned === controller) owned = null;
    }
  };
}
