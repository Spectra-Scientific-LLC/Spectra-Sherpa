export interface CompactLabelOptions {
  maxLength?: number;
  headLength?: number;
  tailLength?: number;
}

export interface LabelDelimiterOptions {
  delimiterCandidates?: string[];
  minCoverage?: number;
}

export interface LabelTableOptions extends LabelDelimiterOptions {
  limit?: number;
  columnHeaderPrefix?: string;
}

export interface LabelTableData {
  headers: string[];
  rows: string[][];
  delimiter: string | null;
}

const DEFAULT_DELIMITERS = [",", ";", "|", "\t"];

const collapseWhitespace = (text: string): string => text.replace(/\s+/g, " ").trim();

export function normalizeSampleLabel(value: unknown): string {
  if (value === null || value === undefined) return "";

  if (Array.isArray(value)) {
    const readable = value
      .slice()
      .reverse()
      .find((item) => typeof item === "string" && item.trim().length > 0);
    if (typeof readable === "string") return readable.trim();

    return value
      .map((item) => normalizeSampleLabel(item))
      .filter((item) => item.length > 0)
      .join(" | ");
  }

  if (typeof value === "object") {
    if ("label" in value && typeof value.label === "string" && value.label.trim().length > 0) {
      return value.label.trim();
    }
    if ("name" in value && typeof value.name === "string" && value.name.trim().length > 0) {
      return value.name.trim();
    }
    return String(value);
  }

  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed.startsWith("[") || trimmed.startsWith("(")) {
      const quoted = [...trimmed.matchAll(/'([^']+)'|"([^"]+)"/g)]
        .map((match) => match[1] || match[2])
        .filter(Boolean);
      if (quoted.length > 0) return quoted[quoted.length - 1];
    }
    return trimmed;
  }

  return String(value);
}

export function normalizeSampleLabels(values: unknown[], limit?: number): string[] {
  if (!Array.isArray(values) || values.length === 0) return [];
  const slice = typeof limit === "number" && limit > 0 ? values.slice(0, limit) : values;
  return slice.map((value) => collapseWhitespace(normalizeSampleLabel(value)));
}

export function compactSampleLabel(value: unknown, options: CompactLabelOptions = {}): string {
  const text = collapseWhitespace(normalizeSampleLabel(value));
  if (!text) return "";

  const maxLength = options.maxLength ?? 64;
  if (text.length <= maxLength) return text;

  const headLength = options.headLength ?? 40;
  const tailLength = options.tailLength ?? 18;
  return `${text.slice(0, headLength)}...${text.slice(-tailLength)}`;
}

export function detectLabelDelimiter(
  labels: string[],
  options: LabelDelimiterOptions = {},
): string | null {
  if (!Array.isArray(labels) || labels.length === 0) return null;

  const candidates = options.delimiterCandidates ?? DEFAULT_DELIMITERS;
  const minCoverage = options.minCoverage ?? 0.8;
  let best: { delimiter: string; coverage: number; columns: number } | null = null;

  for (const delimiter of candidates) {
    const partCounts = labels.map((label) => (
      splitLabelByDelimiter(label, delimiter).length
    ));
    const splitCounts = partCounts.filter((count) => count > 1);
    if (splitCounts.length === 0) continue;

    const coverage = splitCounts.length / labels.length;
    if (coverage < minCoverage) continue;

    const minCols = Math.min(...splitCounts);
    const maxCols = Math.max(...splitCounts);
    if (maxCols - minCols > 1) continue;

    const columns = Math.round(splitCounts.reduce((sum, count) => sum + count, 0) / splitCounts.length);
    if (!best || coverage > best.coverage || (coverage === best.coverage && columns > best.columns)) {
      best = { delimiter, coverage, columns };
    }
  }

  return best?.delimiter || null;
}

export function splitLabelByDelimiter(label: string, delimiter: string | null): string[] {
  if (!delimiter) return [label];
  const parts = label
    .split(delimiter)
    .map((part) => collapseWhitespace(part))
    .filter((part) => part.length > 0);
  return parts.length > 0 ? parts : [label];
}

export function buildLabelTable(
  labels: unknown[],
  options: LabelTableOptions = {},
): LabelTableData {
  const normalized = normalizeSampleLabels(labels, options.limit);
  if (normalized.length === 0) {
    return { headers: ["Label"], rows: [], delimiter: null };
  }

  const delimiter = detectLabelDelimiter(normalized, options);
  if (!delimiter) {
    return {
      headers: ["Label"],
      rows: normalized.map((label) => [label]),
      delimiter: null,
    };
  }

  const splitRows = normalized.map((label) => splitLabelByDelimiter(label, delimiter));
  const maxCols = Math.max(...splitRows.map((row) => row.length));
  const rows = splitRows.map((row) => {
    if (row.length >= maxCols) return row;
    return [...row, ...Array.from({ length: maxCols - row.length }, () => "")];
  });

  const prefix = options.columnHeaderPrefix ?? "Field";
  const headers = Array.from({ length: maxCols }, (_, idx) => `${prefix} ${idx + 1}`);
  return { headers, rows, delimiter };
}
