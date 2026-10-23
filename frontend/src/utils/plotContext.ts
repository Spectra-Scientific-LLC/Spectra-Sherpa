/** Compact plot disclosure from retained population metadata, never parsed prose. */
type Population = {
  shown: number; total: number; method?: string; excluded?: number; excluded_features?: number;
};

const object = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;

function population(value: unknown): Population | null {
  if (!value || typeof value !== "object") return null;
  const p = value as Population;
  return Number.isInteger(p.shown) && Number.isInteger(p.total) && p.shown >= 0 && p.total >= p.shown
    ? p : null;
}

function counts(p: Population): string {
  const selection = p.shown < p.total && p.method === "first_rows" ? " (first active rows)" : "";
  const exclusions = [
    p.excluded ? `${p.excluded} excluded rows` : "",
    p.excluded_features ? `${p.excluded_features} excluded features` : "",
  ].filter(Boolean);
  return `${p.shown} of ${p.total} active rows${selection}${exclusions.length ? `; ${exclusions.join(", ")}` : ""}`;
}

/** Visible existence signal; counts and methodology stay in the plot context. */
export function plotHasSubset(layout: Record<string, unknown>, omitted = 0, sourcePopulation?: unknown): boolean {
  const meta = object(layout.meta) ?? {};
  const comparison = object(meta.comparison_populations);
  const populations = comparison
    ? [comparison.original, comparison.preprocessed, sourcePopulation]
    : [meta.display_population, sourcePopulation];
  return omitted > 0 || populations.some(value => {
    const p = population(value);
    return p !== null && p.shown < p.total;
  });
}

export function plotContext(
  layout: Record<string, unknown>,
  additional = "",
  omitted = "",
): string {
  const meta = object(layout.meta) ?? {};
  const comparison = object(meta.comparison_populations);
  const original = population(comparison?.original);
  const processed = population(comparison?.preprocessed);
  const parts: string[] = [];
  if (original && processed) {
    const before = counts(original), after = counts(processed);
    parts.push(before === after ? `Both panels: ${after}.` : `Original: ${before}. Preprocessed: ${after}.`);
  } else if (comparison) {
    if (original) parts.push(`Original: ${counts(original)}.`);
    if (processed) parts.push(`Preprocessed: ${counts(processed)}.`);
  } else {
    const p = population(meta.display_population);
    if (p && (p.shown < p.total || p.excluded || p.excluded_features)) parts.push(`Plot: ${counts(p)}.`);
  }
  if (typeof meta.comparison_scale_notice === "string") parts.push(meta.comparison_scale_notice);
  const colors = object(meta.comparison_color_notices);
  if (typeof colors?.original === "string" && colors.original === colors.preprocessed) {
    parts.push(`Both panels: ${colors.original}`);
  } else if (colors) {
    if (typeof colors.original === "string") parts.push(`Original: ${colors.original}`);
    if (typeof colors.preprocessed === "string") parts.push(`Preprocessed: ${colors.preprocessed}`);
  } else if (typeof meta.color_encoding_notice === "string") parts.push(meta.color_encoding_notice);
  if (additional) parts.push(additional);
  if (omitted) parts.push(`Display settings additionally omit ${omitted}.`);
  return [...new Set(parts)].join(" ");
}
