/** Presentation only: retain scientific context without serializing execution artifacts. */
import { scientificErrorMetricLabel, scientificProtocolLabel, scientificMetricContext, scientificTargetMetricContext } from "./scientificDisplay";
const internalField = /^(?:_.*|artifacts?|.*_artifact|.*artifact_manifest|artifact_refs?|model_state|serialized_model|fitted_parameters|arrays|estimator|pickle|joblib|storage_path|file_path|download_url|raw_data|plot_data|plotly_json|visualization|plots|x_axis|y_axis|preview)$/i;

/** Results and diagnostics are node maps, with reserved execution metadata at the root. */
export function reportGroups(value: unknown): [string, [string, string][]][] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).flatMap(([nodeId, payload]) => {
    if (internalField.test(nodeId)) return [];
    const rows = reportRows(payload).map(([path, text]): [string, string] => {
      const parts = path.split(" / ");
      const key = parts.pop() || "";
      let context = payload;
      let inherited = scientificMetricContext(context);
      for (const part of parts) {
        const match = part.match(/^([^[]+)(?:\[(\d+)\])?$/);
        if (!match || !context || typeof context !== "object") { context = undefined; break; }
        context = (context as Record<string, unknown>)[match[1]];
        if (match[2] && Array.isArray(context)) {
          context = context[Number(match[2]) - 1];
          if (["targets", "per_target", "per_response"].includes(match[1])) {
            const target = context && typeof context === "object" ? (context as Record<string, unknown>).target ?? (context as Record<string, unknown>).target_name : undefined;
            inherited = scientificTargetMetricContext(inherited, Number(match[2]) - 1, target);
          }
        }
        inherited = scientificMetricContext(context, inherited);
      }
      const indexedMetric = key.match(/_per_(?:target|response)\[(\d+)\]$/);
      if (indexedMetric) inherited = scientificTargetMetricContext(inherited, Number(indexedMetric[1]) - 1);
      const qualified = scientificErrorMetricLabel(key, inherited, key);
      return [path, qualified === key ? text : `${text} ${qualified.slice(key.length).trim()} · ${scientificProtocolLabel(inherited)}`];
    });
    return rows.length ? [[nodeId, rows] as [string, [string, string][]]] : [];
  });
}

export function reportRows(value: unknown, path = ""): [string, string][] {
  if (value == null) return [];
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return [];
    // Fixed decimals would turn small, scientifically meaningful quantities into zero.
    return [[path, String(value)]];
  }
  if (typeof value === "string") return value.trim() ? [[path, value]] : [];
  if (typeof value === "boolean") return [[path, String(value)]];
  if (Array.isArray(value)) {
    if (value.length && value.every(Array.isArray)) {
      const widths = value.map((row) => row.length);
      if (widths.reduce((total, width) => total + width, 0) > 100) {
        if (!value.some((row) => row.some((cell) => reportRows(cell).length))) return [];
        const columns = widths.every((width) => width === widths[0]) ? String(widths[0]) : "variable";
        return [[path, `Matrix: ${value.length} rows × ${columns} columns (values omitted)`]];
      }
    }
    if (value.length > 100) {
      if (!value.some((item) => reportRows(item).length)) return [];
      return [[path, `${value.length} entries (values omitted)`]];
    }
    // Keep original indices when missing entries are omitted; never silently truncate folds/targets.
    return value.flatMap((item, index) => reportRows(item, `${path}[${index + 1}]`));
  }
  if (typeof value !== "object") return [];
  const record = value as Record<string, unknown>;
  const previewNotice: [string, string][] = record.target_truncated ? [[path ? `${path} / Target preview` : "Target preview",
    `${Array.isArray(record.target) ? record.target.length : "preview"} of ${record.target_original_rows ?? "unknown"} target rows in preview. Enable complete target lists for all values.`]] : [];
  return [...previewNotice, ...Object.entries(value).flatMap(([key, item]) =>
    internalField.test(key) ? [] : reportRows(item, path ? `${path} / ${key}` : key),
  )];
}

export function formatReportValue(value: unknown): string {
  return reportRows(value).map(([label, text]) => label ? `${label}: ${text}` : text).join("; ");
}

/** Escape text within Markdown tables, including embedded HTML and line breaks. */
export function reportMarkdownText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/([\\`*_{}[\]()#!|])/g, "\\$1").replace(/\r?\n/g, " ");
}
