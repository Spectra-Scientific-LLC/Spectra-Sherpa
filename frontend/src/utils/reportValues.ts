/** Presentation only: retain scientific context without serializing execution artifacts. */
const internalField = /^(?:_.*|artifacts?|.*_artifact|.*artifact_manifest|artifact_refs?|model_state|serialized_model|fitted_parameters|arrays|estimator|pickle|joblib|storage_path|file_path|download_url|raw_data|plot_data|plotly_json|visualization|plots|x_axis|y_axis|preview)$/i;

/** Results and diagnostics are node maps, with reserved execution metadata at the root. */
export function reportGroups(value: unknown): [string, [string, string][]][] {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value).flatMap(([nodeId, payload]) => {
    if (internalField.test(nodeId)) return [];
    const rows = reportRows(payload);
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
    `Only ${Array.isArray(record.target) ? record.target.length : "preview"} of ${record.target_original_rows ?? "unknown"} target rows retained in this preview; not the population size. Enable complete target lists for exact retained comparison values.`]] : [];
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
