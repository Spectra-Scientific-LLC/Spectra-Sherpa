import axios from "axios";

interface ErrorBody {
  detail?: string | Record<string, unknown> | Array<Record<string, unknown>>;
  message?: string;
  error?: string;
  upgrade_url?: string;
}

function formatValidationDetail(detail: Array<Record<string, unknown>>): string {
  const messages = detail
    .map((item) => {
      const loc = Array.isArray(item.loc) ? item.loc.join(".") : "";
      const msg = typeof item.msg === "string" ? item.msg : "";
      return [loc, msg].filter(Boolean).join(": ");
    })
    .filter(Boolean);
  return messages.join("; ");
}

/**
 * Check if an error is a demo upgrade prompt (403 or 429 with upgrade_url).
 *
 * Demo 403 guards put upgrade fields inside `detail` (object).
 * Demo 429 rate limits put upgrade fields at the top level of the body.
 */
export function isDemoUpgradeError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false;
  const status = error.response?.status;
  if (status !== 403 && status !== 429) return false;
  const data = error.response?.data;
  if (!data || typeof data !== "object") return false;
  const detail = data.detail;
  // 403: detail is an object with upgrade_url
  if (typeof detail === "object" && detail !== null && "upgrade_url" in detail) {
    return true;
  }
  // 429: upgrade_url at top level
  return "upgrade_url" in data;
}

export interface DemoUpgradeInfo {
  message: string;
  upgradeUrl: string;
  availablePlans: string[];
  blockedCapability?: string;
}

/**
 * Extract demo upgrade info from a 403/429 response.
 *
 * Returns null if the error is not a demo upgrade error.
 */
export function getDemoUpgradeInfo(error: unknown): DemoUpgradeInfo | null {
  if (!axios.isAxiosError(error)) return null;
  const data = error.response?.data;
  if (!data || typeof data !== "object") return null;

  const detail = data.detail;

  // 403: structured detail object
  if (typeof detail === "object" && detail !== null && "upgrade_url" in detail) {
    const d = detail as Record<string, unknown>;
    return {
      message: String(d.message || "This feature requires a paid plan."),
      upgradeUrl: String(d.upgrade_url),
      availablePlans: Array.isArray(d.available_plans) ? d.available_plans : [],
      blockedCapability: d.blocked_capability ? String(d.blocked_capability) : undefined,
    };
  }

  // 429: fields at top level
  if ("upgrade_url" in data) {
    return {
      message: String(data.message || data.detail || "Demo limit reached."),
      upgradeUrl: String(data.upgrade_url),
      availablePlans: Array.isArray(data.available_plans) ? data.available_plans : [],
    };
  }

  return null;
}

export function getErrorMessage(
  error: unknown,
  fallback = "An unexpected error occurred",
): string {
  if (axios.isAxiosError<ErrorBody>(error)) {
    const detail = error.response?.data?.detail;
    if (Array.isArray(detail)) {
      return formatValidationDetail(detail) || fallback;
    }
    // Handle object detail (demo 403/429)
    if (typeof detail === "object" && detail !== null) {
      const message = (detail as Record<string, unknown>).message;
      return typeof message === "string" && message ? message : fallback;
    }
    return (
      detail ||
      error.response?.data?.message ||
      error.response?.data?.error ||
      error.message ||
      fallback
    );
  }

  if (error instanceof Error) {
    return error.message || fallback;
  }

  if (typeof error === "string") {
    return error;
  }

  return fallback;
}
