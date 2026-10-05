import api, { expireBrowserSession } from "@/api/client";
import {
  clearStoredToken,
  hasStoredApiKey,
  hasStoredToken,
  readStoredApiKey,
} from "@/utils/authStorage";

export const buildWsUrl = (): string => {
  // In development, use explicit API URL
  // In production, derive from current page location (nginx proxies /ws)
  const apiBase = import.meta.env.VITE_API_BASE_URL;

  if (apiBase) {
    // Explicit URL configured - use it
    const url = new URL(apiBase);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/ws";
    url.search = "";
    return url.toString();
  }

  // No explicit URL - derive from window.location
  // This works in production where nginx serves everything
  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/ws`;
  }

  // Fallback for SSR or testing
  return "ws://127.0.0.1:8000/ws";
};

/**
 * Keep the WebSocket URL credential-free.
 *
 * WebSocket authentication is handled by {@link buildAuthMessage} as the first
 * message after connect. This helper remains a no-op so callers don't need to
 * know whether older code previously tried to decorate the URL.
 */
export const withCredentials = (wsUrl: string): string => {
  // Keep tokens out of URLs, logs, and proxy metadata.
  return wsUrl;
};

/**
 * Build an authentication message to send as the first WebSocket frame.
 * Send one credential authority. An explicitly configured API key retains its
 * historical precedence over a stored browser token.
 */
export const buildAuthMessage = (): string => {
  const token = localStorage.getItem("token");
  const apiKey = readStoredApiKey();
  return JSON.stringify({
    type: "authenticate",
    token: apiKey ? null : token || null,
    api_key: apiKey || null,
  });
};

/** A policy close is not proof that the browser credential is invalid. */
export type WsPolicyCloseResolution =
  | "retry-with-api-key"
  | "session-confirmed"
  | "session-unconfirmed"
  | "session-rejected"
  | "no-credentials"
  | "cancelled";

export const WS_SESSION_PROBE_TIMEOUT_MS = 5_000;

export const resolveWsPolicyClose = async (
  signal?: AbortSignal,
): Promise<WsPolicyCloseResolution> => {
  if (signal?.aborted) return "cancelled";
  if (!hasStoredToken()) return "no-credentials";
  if (hasStoredApiKey()) {
    clearStoredToken();
    return "retry-with-api-key";
  }
  const token = localStorage.getItem("token");
  const controller = new AbortController();
  let cancelWait!: () => void;
  const cancelled = new Promise<null>((resolve) => {
    cancelWait = () => { controller.abort(); resolve(null); };
  });
  signal?.addEventListener("abort", cancelWait, { once: true });
  const deadline = setTimeout(cancelWait, WS_SESSION_PROBE_TIMEOUT_MS);
  try {
    const response = await Promise.race([
      api.get("/auth/me", {
        signal: controller.signal,
        timeout: WS_SESSION_PROBE_TIMEOUT_MS,
        // Handle 401 here, before the global interceptor can expire a newer
        // session on behalf of a cancelled or superseded connection.
        validateStatus: (status: number) => status === 401 || (status >= 200 && status < 300),
      }),
      cancelled,
    ]);
    if (signal?.aborted) return "cancelled";
    // Renewal is not a disconnect: the current connection must retry with
    // its new credential rather than leave the handshake unresolved.
    if (token !== localStorage.getItem("token")) return "session-unconfirmed";
    if (!response || controller.signal.aborted) return "session-unconfirmed";
    if (response.status === 401) {
      expireBrowserSession();
      return "session-rejected";
    }
    return "session-confirmed";
  } catch {
    if (signal?.aborted) return "cancelled";
    // Renewal is not a disconnect: the current connection must retry with
    // its new credential rather than leave the handshake unresolved.
    if (token !== localStorage.getItem("token")) return "session-unconfirmed";
    // A transport/server failure cannot invalidate a credential.
    return "session-unconfirmed";
  } finally {
    clearTimeout(deadline);
    signal?.removeEventListener("abort", cancelWait);
  }
};
