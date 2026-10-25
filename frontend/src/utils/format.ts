export const formatBytes = (bytes: number | null | undefined): string => {
  if (!bytes || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** index;
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
};

/*
 * Display-only formatting. These helpers round what is shown and never change
 * stored or exported values; callers keep the full value (for example in a
 * `title` or `datetime` attribute) so nothing is lost by rounding.
 */

export type TimestampInput = string | number | Date | null | undefined;

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const EMPTY = "—";

/** Parse an ISO string, epoch milliseconds or Date; null when absent or invalid. */
export function parseTimestamp(value: TimestampInput): Date | null {
  if (value === null || value === undefined || value === "") return null;
  // Legacy API timestamps without an offset are UTC database values. Date-only
  // strings retain their calendar-date behavior; explicit offsets stay intact.
  const normalized = typeof value === "string" && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)
    ? `${value.replace(" ", "T")}Z` : value;
  const date = normalized instanceof Date ? normalized : new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Absolute date and time in the viewer's locale, always with the time zone so
 * the reading is unambiguous, e.g. "Oct 8, 2026, 5:20 PM UTC".
 */
export function formatTimestamp(value: TimestampInput, options: { seconds?: boolean } = {}): string {
  const date = parseTimestamp(value);
  if (!date) return typeof value === "string" && value ? value : EMPTY;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: options.seconds ? "2-digit" : undefined,
    timeZoneName: "short",
  });
}

/** Calendar date only, e.g. "Oct 8, 2026"; the year is omitted for the current year when `short`. */
export function formatCalendarDate(value: TimestampInput, options: { short?: boolean; now?: number } = {}): string {
  const date = parseTimestamp(value);
  if (!date) return typeof value === "string" && value ? value : EMPTY;
  const sameYear = date.getFullYear() === new Date(options.now ?? Date.now()).getFullYear();
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: options.short && sameYear ? undefined : "numeric",
  });
}

/**
 * How long ago, in one wording across the app: "just now", "5 min ago",
 * "3 hr ago", "yesterday", "4 days ago", then the calendar date. Pair it with
 * `formatTimestamp` (see RelativeTime.vue) so the exact time stays available.
 */
export function formatRelativeTime(value: TimestampInput, now: number = Date.now()): string {
  const date = parseTimestamp(value);
  if (!date) return typeof value === "string" && value ? value : EMPTY;
  const elapsed = now - date.getTime();
  if (elapsed < -MINUTE_MS) return formatTimestamp(date);
  if (elapsed < MINUTE_MS) return "just now";
  if (elapsed < HOUR_MS) return `${Math.floor(elapsed / MINUTE_MS)} min ago`;
  if (elapsed < DAY_MS) return `${Math.floor(elapsed / HOUR_MS)} hr ago`;
  const days = Math.floor(elapsed / DAY_MS);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return formatCalendarDate(date, { short: true, now });
}

/** @deprecated Use formatTimestamp. */
export const formatDateTime = (value: string): string => formatTimestamp(value);

/**
 * A metric value for display: integers as they are, otherwise whole numbers
 * above 100, one decimal above 10,
 * three decimals down to 0.1, and three significant digits below that so a
 * small non-zero value (an RMSE of 0.0004) never reads as 0. Show the full
 * value alongside (e.g. `title`) where the rounded one is the only one shown.
 */
export function formatMetricValue(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return EMPTY;
  // Counts (samples, classes, components) are whole numbers: never "64.0".
  if (Number.isInteger(value)) return String(value);
  const magnitude = Math.abs(value);
  if (magnitude >= 100) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  if (magnitude >= 0.1 || value === 0) return trimZeros(value.toFixed(3));
  if (magnitude >= 1e-4) return trimZeros(value.toPrecision(3));
  return value.toExponential(2);
}

function trimZeros(text: string): string {
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}
