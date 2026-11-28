export { CONTINUOUS_COLORSCALE, continuousColor } from "@/theme/plotTheme";

/**
 * Numeric sample-table columns that can colour spectra on a gradient: one finite
 * number per row and more distinct values than a category legend can show.
 */
export function numericSampleColumns(sampleTable: unknown, rows: number): Array<{ name: string; values: number[] }> {
  if (!sampleTable || typeof sampleTable !== "object" || Array.isArray(sampleTable)) return [];
  return Object.entries(sampleTable as Record<string, unknown>)
    .filter(([name, raw]) => name !== "sample_id" && Array.isArray(raw) && raw.length === rows
      && raw.every((value) => typeof value === "number" && Number.isFinite(value))
      && new Set(raw).size > 2)
    .map(([name, raw]) => ({ name, values: raw as number[] }));
}
