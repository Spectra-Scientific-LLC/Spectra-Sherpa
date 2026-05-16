import { onBeforeUnmount } from "vue";
import { useAppConfig } from "@/composables/useAppConfig";
import { subscribeSherpaEvents } from "@/lib/sherpaEvents";
import {
  useGuidanceStore,
  type GuidanceEvent,
  type GuidanceUnavailableEvent,
} from "@/stores/guidance";

// Bounded backoff schedule for the initial guidance-settings fetch.
// A transient 401 right after login (token not yet attached to the
// client) or a cold-start race used to leave guidance frozen disabled
// until a full page reload — audit F2.  Retry a few times with growing
// delays before giving up; readiness re-entry (MainLayout watcher) is
// the longer-horizon backstop after that.
const _SETTINGS_RETRY_DELAYS_MS = [500, 1500, 4000];

export function useGuidance() {
  const { appMode, isFeatureEnabled } = useAppConfig();
  const guidanceStore = useGuidanceStore();
  let unsubscribe: (() => void) | null = null;
  let settingsRetryTimer: ReturnType<typeof setTimeout> | null = null;
  // Resolver for the in-flight backoff sleep.  ``clearTimeout`` alone
  // never settles the awaited promise, so a cancel mid-sleep would hang
  // ``start()`` forever — review finding.  ``stop()`` must resolve it.
  let pendingSleepResolve: (() => void) | null = null;
  // Cancellation token: ``stop()`` (incl. the MainLayout watcher
  // tearing down an in-flight startup) flips this so the retry loop
  // exits promptly instead of marching through the full backoff and
  // then reporting a stale "ready".
  let cancelled = false;

  function _abortPendingSleep(): void {
    if (settingsRetryTimer !== null) {
      clearTimeout(settingsRetryTimer);
      settingsRetryTimer = null;
    }
    if (pendingSleepResolve !== null) {
      const resolve = pendingSleepResolve;
      pendingSleepResolve = null;
      // Settle the awaited promise so ``_loadSettingsWithRetry`` /
      // ``start()`` unwinds immediately rather than hanging.
      resolve();
    }
  }

  function _sleep(ms: number): Promise<void> {
    return new Promise<void>((resolve) => {
      pendingSleepResolve = resolve;
      settingsRetryTimer = setTimeout(() => {
        settingsRetryTimer = null;
        pendingSleepResolve = null;
        resolve();
      }, ms);
    });
  }

  async function _loadSettingsWithRetry(attempt = 0): Promise<boolean> {
    if (cancelled) return false;
    const ok = await guidanceStore.loadSettings();
    if (cancelled || ok || attempt >= _SETTINGS_RETRY_DELAYS_MS.length) {
      return !cancelled;
    }
    await _sleep(_SETTINGS_RETRY_DELAYS_MS[attempt]);
    if (cancelled) return false;
    return _loadSettingsWithRetry(attempt + 1);
  }

  async function start(): Promise<boolean> {
    if (appMode.value === "local" || !isFeatureEnabled("sherpaGuidance")) {
      return false;
    }
    cancelled = false;
    // Subscribe first so the event handler is wired even if the
    // settings fetch is still retrying — events only render once
    // settings report guidance_enabled, but we must not miss the
    // subscription window.
    if (!unsubscribe) {
      unsubscribe = subscribeSherpaEvents(
        (payload) => {
          if (payload.type === "guidance.event") {
            void guidanceStore.handleEvent(payload as unknown as GuidanceEvent);
            return;
          }
          if (payload.type === "guidance.unavailable") {
            guidanceStore.markUnavailable(payload as unknown as GuidanceUnavailableEvent);
          }
        },
        { types: ["guidance.event", "guidance.unavailable"] }
      );
    }
    return _loadSettingsWithRetry();
  }

  function stop(): void {
    cancelled = true;
    _abortPendingSleep();
    unsubscribe?.();
    unsubscribe = null;
  }

  onBeforeUnmount(stop);

  return { start, stop };
}
