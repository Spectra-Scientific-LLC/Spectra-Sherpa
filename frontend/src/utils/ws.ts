import { readStoredApiKey } from "@/utils/authStorage";

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
 * The backend expects `{type: "authenticate", token, api_key}` for explicit
 * remote WebSocket authentication.
 */
export const buildAuthMessage = (): string => {
  const token = localStorage.getItem("token");
  const apiKey = readStoredApiKey();
  return JSON.stringify({
    type: "authenticate",
    token: token || null,
    api_key: apiKey || null,
  });
};
