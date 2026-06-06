export interface DiagnosticEntry {
  key: string;
  label: string;
  displayValue: string;
  detail?: string;
}

const STRUCTURED_CONTAINER_KEYS = new Set([
  "classification_metrics",
  "confusion_matrices",
  "metrics",
  "plots",
  "raw",
  "table",
]);

const EMPTY_STRINGS = new Set(["", "nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity", "none", "null"]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

const isPrimitiveDiagnostic = (value: unknown): value is string | number | boolean =>
  typeof value === "string" || typeof value === "number" || typeof value === "boolean";

export const formatDiagnosticLabel = (key: string): string =>
  key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase())
    .replace(/\bCv\b/g, "CV")
    .replace(/\bRmse\b/g, "RMSE")
    .replace(/\bSnr\b/g, "SNR")
    .replace(/\bSpe\b/g, "SPE");

export const isEmptyDiagnosticValue = (value: unknown): boolean => {
  if (value == null) {
    return true;
  }
  if (typeof value === "number") {
    return !Number.isFinite(value);
  }
  if (typeof value === "string") {
    return EMPTY_STRINGS.has(value.trim().toLowerCase());
  }
  if (Array.isArray(value)) {
    return value.length === 0 || value.every(isEmptyDiagnosticValue);
  }
  if (isRecord(value)) {
    return Object.keys(value).length === 0 || Object.values(value).every(isEmptyDiagnosticValue);
  }
  return false;
};

export const formatDiagnosticValue = (value: unknown): string => {
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      return "";
    }
    if (Number.isInteger(value)) {
      return String(value);
    }
    const abs = Math.abs(value);
    if ((abs > 0 && abs < 0.0001) || abs >= 100000) {
      return value.toExponential(3);
    }
    return Number(value.toPrecision(4)).toString();
  }
  if (typeof value === "string") {
    return value.trim();
  }
  if (Array.isArray(value)) {
    const values = value.filter((item) => !isEmptyDiagnosticValue(item));
    if (values.length === 0) {
      return "";
    }
    if (values.every(isPrimitiveDiagnostic) && values.length <= 6) {
      return values.map(formatDiagnosticValue).join(", ");
    }
    if (values.every(Array.isArray)) {
      const firstRow = values[0] as unknown[];
      return `${values.length} x ${firstRow.length} matrix`;
    }
    return `${values.length} values`;
  }
  if (isRecord(value)) {
    const scalarEntries = Object.entries(value).filter(
      ([, item]) => isPrimitiveDiagnostic(item) && !isEmptyDiagnosticValue(item),
    );
    if (scalarEntries.length > 0 && scalarEntries.length <= 4) {
      return scalarEntries
        .map(([key, item]) => `${formatDiagnosticLabel(key)}: ${formatDiagnosticValue(item)}`)
        .join("; ");
    }
    const nonEmptyCount = Object.values(value).filter((item) => !isEmptyDiagnosticValue(item)).length;
    return nonEmptyCount > 0 ? `${nonEmptyCount} fields` : "";
  }
  return String(value);
};

const buildDetail = (value: unknown): string | undefined => {
  if (isPrimitiveDiagnostic(value)) {
    return undefined;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
};

export const buildDiagnosticEntries = (diagnostics: Record<string, unknown> | null | undefined): DiagnosticEntry[] => {
  if (!diagnostics) {
    return [];
  }

  return Object.entries(diagnostics)
    .filter(([key, value]) => !STRUCTURED_CONTAINER_KEYS.has(key) && !isEmptyDiagnosticValue(value))
    .map(([key, value]) => ({
      key,
      label: formatDiagnosticLabel(key),
      displayValue: formatDiagnosticValue(value),
      detail: buildDetail(value),
    }))
    .filter((entry) => entry.displayValue.length > 0);
};
