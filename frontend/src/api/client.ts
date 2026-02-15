import axios from "axios";

// Use relative URL in production (nginx proxies to backend)
// Use absolute URL in development for Vite dev server
const defaultBaseUrl = import.meta.env.DEV
  ? "http://127.0.0.1:8000/api/v1"
  : "/api/v1";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultBaseUrl,
});

/**
 * Request interceptor to add authentication headers.
 *
 * Supports two auth mechanisms:
 * 1. JWT Bearer token (for user login in cloud/enterprise modes)
 * 2. X-API-Key (for machine-to-machine in hybrid mode)
 *
 * JWT takes precedence if both are present.
 */
api.interceptors.request.use((config) => {
  config.headers = config.headers || {};

  // Check for JWT token first (user login auth)
  const token = localStorage.getItem("token");
  if (token) {
    config.headers["Authorization"] = `Bearer ${token}`;
  }

  // Also add API key if present (for hybrid mode M2M auth)
  const apiKey = localStorage.getItem("api_key");
  if (apiKey) {
    config.headers["X-API-Key"] = apiKey;
  }

  return config;
});

/**
 * Response interceptor to handle expired sessions.
 *
 * When the backend returns 401 (e.g. expired JWT in enterprise mode),
 * clear stored credentials and redirect to login so the user
 * isn't stuck making failing requests.
 */
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const path = window.location.pathname;
      // Don't redirect if already on login page (avoid loop)
      if (!path.startsWith("/login")) {
        localStorage.removeItem("token");
        localStorage.removeItem("api_key");
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;
