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
 * Attach credentials to a WebSocket URL.
 *
 * @deprecated Prefer sending credentials via {@link buildAuthMessage} as the
 * first message after connection opens. Query-param auth is retained for
 * backward compatibility with older backend versions.
 */
export const withCredentials = (wsUrl: string): string => {
  // Credentials are now sent via the first WebSocket message (buildAuthMessage).
  // Return the URL unchanged to avoid leaking tokens in server logs / browser history.
  return wsUrl;
};

/**
 * Build an authentication message to send as the first WebSocket frame.
 * The backend accepts `{type: "authenticate", token, api_key}` as an
 * alternative to query-param auth, keeping tokens out of URLs and logs.
 */
export const buildAuthMessage = (): string => {
  const token = localStorage.getItem("token");
  const apiKey = localStorage.getItem("api_key");
  return JSON.stringify({
    type: "authenticate",
    token: token || null,
    api_key: apiKey || null,
  });
};
