import { reactive, watch } from "vue";

export interface DisplayPreferences {
  precision: "full" | "3" | "6" | "9";
  palette: "default" | "colorblind" | "high-contrast";
  lineScale: number;
  markerScale: number;
  tableDensity: "comfortable" | "compact";
  maxRows: number;
}

export const DEFAULT_DISPLAY_PREFERENCES: DisplayPreferences = {
  precision: "full",
  palette: "default",
  lineScale: 1,
  markerScale: 1,
  tableDensity: "comfortable",
  maxRows: 300,
};

const STORAGE_KEY = "spectra.display-preferences.v1";
const rowLimits = new Set([100, 300, 500, 1000, 3000]);

function validated(value: unknown): DisplayPreferences {
  const saved = value && typeof value === "object" ? value as Partial<DisplayPreferences> : {};
  return {
    precision: ["full", "3", "6", "9"].includes(String(saved.precision))
      ? saved.precision! : "full",
    palette: ["default", "colorblind", "high-contrast"].includes(String(saved.palette))
      ? saved.palette! : "default",
    lineScale: [0.75, 1, 1.5].includes(Number(saved.lineScale)) ? Number(saved.lineScale) : 1,
    markerScale: [0.75, 1, 1.5].includes(Number(saved.markerScale)) ? Number(saved.markerScale) : 1,
    tableDensity: saved.tableDensity === "compact" ? "compact" : "comfortable",
    maxRows: rowLimits.has(Number(saved.maxRows)) ? Number(saved.maxRows) : 300,
  };
}

function initial(): DisplayPreferences {
  if (typeof window === "undefined") return { ...DEFAULT_DISPLAY_PREFERENCES };
  try {
    return validated(JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null"));
  } catch {
    return { ...DEFAULT_DISPLAY_PREFERENCES };
  }
}

const preferences = reactive<DisplayPreferences>(initial());

watch(preferences, () => {
  try {
    if (typeof window !== "undefined")
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // Browsers can disable persistence; live display preferences still work.
  }
  if (typeof document !== "undefined") {
    document.documentElement.dataset.tableDensity = preferences.tableDensity;
  }
}, { deep: true, immediate: true });

export function useDisplayPreferences() {
  return preferences;
}

export function displayNumber(value: number, defaultDigits?: number): string {
  if (!Number.isFinite(value)) return "Unavailable";
  const digits = preferences.precision === "full"
    ? defaultDigits : Number(preferences.precision);
  return digits ? value.toPrecision(digits) : String(value);
}
