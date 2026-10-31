/**
 * Scientist-facing wording and number display shared by result surfaces.
 *
 * Saved evidence keeps full precision and every provenance field; these
 * helpers only decide how a value reads on screen. Full values stay
 * available through `title` attributes, downloads and the audit details.
 */
import { formatDiagnosticLabel, formatDiagnosticValue } from "@/utils/diagnostics";

const ROLE_LABELS: Record<string, string> = {
  calibration: "Calibration fit",
  calibration_fit: "Calibration fit",
  training: "Calibration fit",
  cross_validation: "Cross-validation",
  held_out_test: "Test set",
  held_out: "Test set",
  test: "Test set",
  unqualified_evaluation: "Evaluation (lineage not verified)",
};

/** Plain chemometric name for a saved evaluation role. */
export function evaluationRoleLabel(role: string): string {
  return ROLE_LABELS[role] ?? formatDiagnosticLabel(role);
}

/**
 * Decimals that show `significant` figures for the largest magnitude in a
 * column, so every row of one quantity carries the same precision.
 */
export function columnDecimals(values: unknown[], significant = 4): number {
  const finite = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const largest = finite.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
  if (largest === 0) return 0;
  return Math.min(10, Math.max(0, significant - 1 - Math.floor(Math.log10(largest))));
}

/** A measured value at a fixed column precision; labels pass through unchanged. */
export function formatMeasurement(value: unknown, decimals: number): string {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "";
    if (Number.isInteger(value) && decimals === 0) return String(value);
    const text = value.toFixed(decimals);
    // A common column scale must not turn a small nonzero measurement or
    // residual into an apparent exact zero. Retained/exported values are untouched.
    if (value !== 0 && Number(text) === 0) return value.toExponential(3);
    return /^-0(\.0*)?$/.test(text) ? text.slice(1) : text;
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return value == null ? "" : String(value);
}

/** Full-precision text for a `title` attribute when the shown value is rounded. */
export function fullPrecisionTitle(value: unknown): string | undefined {
  return typeof value === "number" && Number.isFinite(value) && !Number.isInteger(value)
    ? String(value)
    : undefined;
}

const FIELD_LABELS: Record<string, string> = {
  accounted_samples: "Samples evaluated",
  predicted_only_label_count: "Predictions outside the known classes",
  n_samples: "Samples",
  n_features: "Variables",
  n_components: "Components",
  n_folds: "Folds",
  n_classes: "Classes",
  n_outliers: "Flagged samples",
  rmsec: "RMSEC",
  rmsecv: "RMSECV",
  rmsep: "RMSEP",
  r2_cv: "Q² (cross-validated R²)",
  q2: "Q²",
};

/** Scientist-facing label for a saved field name. */
export function scientificFieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? formatDiagnosticLabel(key);
}

const ERROR_METRIC = /^(?:latest_)?(?:rmse(?:c|cv|p|_cv|_cal|_test)?|mae|bias|sep)$/i;
export function scientificMetricKey(key: string): string {
  return key.replace(/\[\d+\]$/, "").replace(/_per_(target|response)$/, "");
}
const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

/** Typed heterogeneous column units; never infer them from a column's spelling. */
export function scientificColumnLabel(key: string, metadata: unknown, label = key): string {
  const unit = asRecord(asRecord(metadata).column_units)[key];
  return typeof unit === "string" && unit.trim() && !label.endsWith(`(${unit.trim()})`) ? `${label} (${unit.trim()})` : label;
}

/** All retained record fields, in first-seen order, independent of the displayed page. */
export function scientificRecordColumnKeys(data: unknown): string[] {
  const keys = new Set<string>();
  if (Array.isArray(data)) {
    for (const row of data) {
      if (row && typeof row === "object" && !Array.isArray(row)) {
        for (const key of Object.keys(row)) keys.add(key);
      }
    }
  }
  return [...keys];
}

/** Friendly record headings shared by standalone and embedded scientific tables. */
export function scientificRecordColumnLabel(key: string, metadata: unknown, kind?: string): string {
  const record = asRecord(metadata);
  const peak = kind === "peak_table" || (!kind && !record.scientific_presentation && record.type === "PeakFinding");
  if (!peak) return scientificColumnLabel(key, metadata);
  const names: Record<string, string> = {
    consensus_peak_id: "Peak", consensus_group: "Consensus group", label: "Label",
    median_pos: "Median position", mean_pos: "Mean position", std_pos: "Position standard deviation",
    min_pos: "Minimum position", max_pos: "Maximum position",
    detection_count: "Detections", sample_count: "Samples", detection_fraction: "Detection fraction",
    member_sample_indices: "Member sample indices", member_sample_labels: "Member sample labels",
    constituent_detections: "Constituent detections",
    median_height: "Median height", q1_height: "First-quartile height", q3_height: "Third-quartile height",
    median_half_prominence_width: "Half-prominence width",
    q1_half_prominence_width: "First-quartile half-prominence width", q3_half_prominence_width: "Third-quartile half-prominence width",
    median_absolute_window_integral: "Median absolute window integral",
    q1_absolute_window_integral: "First-quartile absolute window integral", q3_absolute_window_integral: "Third-quartile absolute window integral",
  };
  const label = names[key] ?? key.replace(/_/g, " ");
  const declared = scientificColumnLabel(key, metadata, label);
  if (declared !== label || Object.prototype.hasOwnProperty.call(asRecord(record.column_units), key)) return declared;
  // Historical PeakFinding records may retain only the coordinate-unit declaration.
  const coordinateKeys = ["median_pos", "mean_pos", "std_pos", "min_pos", "max_pos",
    "median_half_prominence_width", "q1_half_prominence_width", "q3_half_prominence_width"];
  return coordinateKeys.includes(key) && typeof record.x_units === "string" && record.x_units.trim()
    ? `${label} (${record.x_units.trim()})` : label;
}

/** Compact structured cells; the full retained value remains available in hover/export. */
export function scientificStructuredCell(value: unknown): string | null {
  if (value === null || typeof value !== "object") return null;
  if (Array.isArray(value) && value.some(item => item !== null && typeof item === "object")) {
    return `${value.length} ${value.length === 1 ? "record" : "records"} (hover for details)`;
  }
  const text = JSON.stringify(value);
  return text.length > 100 ? `${text.slice(0, 100)}…` : text;
}

/** Compact common response-unit context for an independently usable result. */
export function scientificResponseUnit(value: unknown): string | null {
  const units = scientificMetricContext(value).target_units;
  const declarations = Array.isArray(units) ? units : [units];
  return declarations.length > 0 && declarations.every(unit => typeof unit === "string" && unit.trim() && unit === declarations[0])
    ? String(declarations[0]) : null;
}

/** Inherit only response units and declared population roles, never spectral metadata. */
export function scientificMetricContext(value: unknown, inherited: unknown = {}): Record<string, unknown> {
  const record = asRecord(value);
  const metadata = asRecord(record.metadata);
  const diagnostics = asRecord(record.diagnostics ?? metadata.diagnostics);
  const parent = asRecord(inherited);
  const units = [record.target_units, metadata.target_units, diagnostics.target_units,
    asRecord(record.response_identity).units, asRecord(metadata.response_identity).units,
    asRecord(diagnostics.response_identity).units,
    record.task_type === "regression" || typeof record.target === "string" || typeof record.target_name === "string" ? record.units : undefined,
  ].find(item => item !== undefined);
  const role = [asRecord(record.population_authority).role, asRecord(metadata.population_authority).role,
    record.evaluation_role, metadata.evaluation_role, record.role, metadata.role,
  ].find(item => item !== undefined);
  const names = [record.target_names, metadata.target_names, asRecord(record.response_identity).names,
    asRecord(metadata.response_identity).names, asRecord(diagnostics.response_identity).names].find(item => item !== undefined);
  return {
    ...(units !== undefined ? { target_units: units } : "target_units" in parent ? { target_units: parent.target_units } : {}),
    ...(role !== undefined ? { role } : "role" in parent ? { role: parent.role } : {}),
    ...(names !== undefined ? { target_names: names } : "target_names" in parent ? { target_names: parent.target_names } : {}),
  };
}

/** Select one response's declaration; index is zero-based and never a guessed unit. */
export function scientificTargetMetricContext(context: unknown, index: number, target?: unknown): Record<string, unknown> {
  const projected = scientificMetricContext(context);
  const names = projected.target_names;
  const namedIndex = typeof target === "string" && Array.isArray(names) ? names.indexOf(target) : -1;
  const targetIndex = namedIndex >= 0 ? namedIndex : index;
  return Array.isArray(projected.target_units)
    ? { ...projected, target_units: projected.target_units[targetIndex] ?? null } : projected;
}

/** Only target declarations qualify error units; spectral axis units do not. */
export function scientificErrorMetricLabel(key: string, context: unknown, label = scientificFieldLabel(key)): string {
  if (!ERROR_METRIC.test(scientificMetricKey(key))) return label;
  const declared = scientificMetricContext(context).target_units;
  const units = Array.isArray(declared) ? declared : [declared];
  const known = units.length > 0 && units.every(unit => typeof unit === "string" && unit.trim()
    && !/unknown|unavailable|not recorded|units not declared/i.test(unit.trim()));
  const unique = [...new Set(units.map(unit => typeof unit === "string" ? unit.trim() : unit))];
  return `${label} (${known && unique.length === 1 ? unique[0] : "units not declared"})`;
}

/** Roles must be declared by the result; fold settings and model names are not evidence. */
export function scientificProtocolLabel(context: unknown): string {
  const role = scientificMetricContext(context).role;
  const labels: Record<string, string> = {
    calibration: "Calibration fit", training: "Calibration fit", train: "Calibration fit",
    cross_validation: "Cross-validation (CV)", cv: "Cross-validation (CV)",
    held_out_test: "Held-out test", held_out: "Held-out test", test: "Held-out test",
    unqualified_evaluation: "Evaluation (lineage not verified)",
  };
  return `Protocol: ${typeof role === "string" && labels[role] ? labels[role] : "not declared"}`;
}

/**
 * Scalar display: whole numbers as they are, fractions to four significant
 * figures, larger values to five (enough for a band position such as
 * 1450.2 cm⁻¹), Yes/No for flags.
 */
export function scientificScalar(value: unknown): string {
  if (value == null) return "Not recorded";
  if (typeof value === "boolean") return formatDiagnosticValue(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "Not finite";
    if (Number.isInteger(value)) return String(value);
    const magnitude = Math.abs(value);
    if (magnitude < 1e-4 || magnitude >= 1e6) return value.toExponential(3);
    return String(Number(value.toPrecision(magnitude < 1 ? 4 : 5)));
  }
  return String(value);
}

const AUDIT_KEYS = new Set([
  "node_id",
  "worker_execution",
  "worker_pid",
  "origin_pid",
  "execution_id",
  "population_authority",
  "fitted_state_custody",
  "canonical_artifact",
  "producer",
  "schema_version",
  "registry_version",
  "serializer",
  "algorithm_id",
  "algorithm_version",
  "input_identity",
  "response_identity",
  "evidence_scope",
  "scope",
]);

/**
 * Provenance and execution bookkeeping: kept for audit, but not part of the
 * scientific reading of a result.
 */
export function isAuditField(key: string): boolean {
  return AUDIT_KEYS.has(key) || /(_sha256|_digest|_hash|_version)$/.test(key);
}


/** Explain differing metric populations using only retained declarations. */
export function scientificMetricNotes(value: unknown, depth = 0): string[] {
  if (!value || typeof value !== "object" || Array.isArray(value) || depth > 5) return [];
  const record = value as Record<string, unknown>;
  const notes: string[] = [];
  if (record.population === "non_noise_samples_only") {
    notes.push("Silhouette and Davies–Bouldin indices describe assigned samples only; DBSCAN noise samples are excluded.");
  }
  if (record.schema_version === "spectrasherpa.classification-evaluation/1"
    && Array.isArray(record.predicted_only_labels) && record.predicted_only_labels.length) {
    notes.push("Macro averages include predicted-only labels (such as unassigned). Balanced accuracy averages recall over reference classes only.");
  }
  if (record.schema_version === 1 && record.task_type === "classification"
    && record.method === "simca"
    && record.evidence_scope === "calibration_fit_diagnostics_not_validation_evidence") {
    notes.push("Calibration-fit macro precision, recall/sensitivity, F1, specificity and balanced accuracy average over the recorded reference classes. Rejected predictions count as errors for their reference class; the rejection label is not an additional class in these averages. These are calibration diagnostics, not held-out validation.");
  }
  // Only inspect named scientific containers, never arbitrary fitted-state trees.
  for (const key of ["metrics", "classification_metrics", "quality_summary", "diagnostics", "metadata"]) {
    for (const note of scientificMetricNotes(record[key], depth + 1)) {
      if (!notes.includes(note)) notes.push(note);
    }
  }
  return notes;
}

/** Remove execution bookkeeping at every depth of a scientific metadata view. */
export function scientificMetadata(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(scientificMetadata);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>)
    .filter(([key]) => !key.startsWith("_") && !isAuditField(key))
    .map(([key, item]) => [key, scientificMetadata(item)]));
}
