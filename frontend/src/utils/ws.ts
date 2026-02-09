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
 * Prefers JWT token (user login) over api_key (machine key).
 * Backend accepts both via query params: ?api_key=... or ?token=...
 */
export const withCredentials = (wsUrl: string): string => {
  const apiKey = localStorage.getItem("api_key");
  const token = localStorage.getItem("token");
  if (!apiKey && !token) {
    return wsUrl;
  }
  const url = new URL(wsUrl);
  if (token) {
    url.searchParams.set("token", token);
  } else if (apiKey) {
    url.searchParams.set("api_key", apiKey);
  }
  return url.toString();
};

/** @deprecated Use withCredentials instead */
export const withApiKey = (wsUrl: string, apiKey?: string | null): string => {
  if (!apiKey) {
    return wsUrl;
  }
  const url = new URL(wsUrl);
  url.searchParams.set("api_key", apiKey);
  return url.toString();
};
