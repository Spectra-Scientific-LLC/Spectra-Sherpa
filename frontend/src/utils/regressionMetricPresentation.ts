/** A display projection; immutable original records remain audit evidence. */
const containers = ["default", "diagnostics", "meta", "metadata", "metrics", "quality_summary"];
const aggregates = ["r2", "rmse", "r2_cal", "rmse_cal", "score", "mae", "bias", "sep", "latest_r2", "latest_rmse"];
const legacy = "legacy_multiresponse_aggregate_unqualified";
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
function isMulti(value: Record<string, unknown>, depth = 0): boolean {
  if (depth > 6) return false;
  const count = value.n_targets ?? value.target_count;
  return (typeof count === "number" && Number.isInteger(count) && count > 1)
    || ["target_names", "per_target"].some(key => Array.isArray(value[key]) && value[key].length > 1)
    || ["per_response_only", legacy].includes(String(value.metric_summary_scope))
    || containers.some(key => record(value[key]) && isMulti(value[key], depth + 1));
}
export function regressionMetricPresentation(value: Record<string, unknown>): Record<string, unknown> {
  if (!isMulti(value)) return value;
  function qualify(source: Record<string, unknown>, depth = 0): Record<string, unknown> {
    if (depth > 6) return source;
    const result = { ...source };
    const suppressed: Record<string, unknown> = {};
    for (const key of aggregates) if (key in result) { suppressed[key] = result[key]; delete result[key]; }
    result.metric_summary_scope = Object.keys(suppressed).length || source.metric_summary_scope === legacy ? legacy : "per_response_only";
    if (Object.keys(suppressed).length) {
      result.legacy_aggregate_evidence = suppressed;
      result.metric_qualification_message = "Legacy multi-response scalar metrics withheld; inspect per-response evidence.";
    }
    for (const key of containers) if (record(source[key])) result[key] = qualify(source[key], depth + 1);
    return result;
  }
  return qualify(value);
}
export function regressionMetricQualification(value: Record<string, unknown>): string | null {
  if (!isMulti(value)) return null;
  return "Per-response metrics only; mixed-response scalar summaries are unqualified.";
}
