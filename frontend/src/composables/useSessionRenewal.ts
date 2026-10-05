import { onBeforeUnmount, watch } from "vue";

import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { sessionExpiryMinutesRemaining } from "@/utils/sessionExpiry";

const CHECK_INTERVAL_MS = 15_000;
const ACTIVE_WINDOW_MS = 5 * 60_000;
const RENEW_AT_MINUTES = 15;
const RETRY_INTERVAL_MS = 60_000;

interface RefreshResponse {
  access_token: string;
}

export function useSessionRenewal() {
  const authStore = useAuthStore();
  let lastActivityAt = Date.now();
  let lastAttemptAt = 0;
  let refreshInFlight = false;
  let timer: number | null = null;
  let enabled = false;

  const noteActivity = () => {
    lastActivityAt = Date.now();
  };

  const maybeRenew = async (): Promise<boolean> => {
    const now = Date.now();
    const token = localStorage.getItem("token");
    const minutesRemaining = sessionExpiryMinutesRemaining(token, now);
    if (
      document.visibilityState !== "visible" ||
      minutesRemaining === null ||
      minutesRemaining > RENEW_AT_MINUTES ||
      now - lastActivityAt > ACTIVE_WINDOW_MS ||
      now - lastAttemptAt < RETRY_INTERVAL_MS ||
      refreshInFlight
    ) {
      return false;
    }

    lastAttemptAt = now;
    refreshInFlight = true;
    try {
      const response = await api.post<RefreshResponse>("/auth/refresh");
      const renewedToken = response.data.access_token;
      if (renewedToken && enabled && localStorage.getItem("token") === token) {
        localStorage.setItem("token", renewedToken);
        authStore.token = renewedToken;
        window.dispatchEvent(new StorageEvent("storage", { key: "token", newValue: renewedToken }));
        return true;
      }
      return false;
    } catch {
      // The shared API client handles an authoritative 401. Transient errors
      // leave the existing token in place and are retried while the tab stays
      // active, so the five-minute warning remains an honest fallback.
      return false;
    } finally {
      refreshInFlight = false;
    }
  };

  const onVisible = () => {
    if (document.visibilityState !== "visible") return;
    noteActivity();
    void maybeRenew();
  };

  const start = () => {
    enabled = true;
    if (timer !== null || !localStorage.getItem("token")) return;
    document.addEventListener("pointerdown", noteActivity, { capture: true });
    document.addEventListener("keydown", noteActivity, { capture: true });
    document.addEventListener("visibilitychange", onVisible);
    timer = window.setInterval(() => void maybeRenew(), CHECK_INTERVAL_MS);
    void maybeRenew();
  };

  const stopPolling = () => {
    document.removeEventListener("pointerdown", noteActivity, { capture: true });
    document.removeEventListener("keydown", noteActivity, { capture: true });
    document.removeEventListener("visibilitychange", onVisible);
    if (timer !== null) window.clearInterval(timer);
    timer = null;
  };

  const stop = () => {
    enabled = false;
    stopPolling();
  };

  watch(
    () => [authStore.token, authStore.user] as const,
    ([, user], [previousToken, previousUser]) => {
      if (!enabled) return;
      if (!localStorage.getItem("token")) {
        stopPolling();
        return;
      }
      if (!previousToken || user?.id !== previousUser?.id) {
        lastActivityAt = Date.now();
        lastAttemptAt = 0;
      }
      start();
    },
  );

  onBeforeUnmount(stop);

  return { start, stop, maybeRenew, noteActivity };
}
