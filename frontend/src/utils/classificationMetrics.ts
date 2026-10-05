const CLASSIFICATION_METRIC_NAMES = [
  "accuracy",
  "balanced_accuracy",
  "f1_macro",
  "precision_macro",
  "recall_macro",
  "sensitivity_macro",
  "specificity_macro",
];

export function flattenClassificationMetricsContract(value: unknown): Record<string, number> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.task_type !== "classification" || !record.splits || typeof record.splits !== "object") return null;

  const out: Record<string, number> = {};
  const splits = record.splits as Record<string, unknown>;
  for (const [split, rawMetrics] of Object.entries(splits)) {
    if (!rawMetrics || typeof rawMetrics !== "object" || Array.isArray(rawMetrics)) continue;
    const metrics = rawMetrics as Record<string, unknown>;
    for (const name of CLASSIFICATION_METRIC_NAMES) {
      const candidate = metrics[name];
      if (typeof candidate === "number" && Number.isFinite(candidate)) {
        out[`${split}_${name}`] = candidate;
      }
    }
  }

  const nClasses = record.n_classes;
  if (typeof nClasses === "number" && Number.isFinite(nClasses)) out.n_classes = nClasses;
  return Object.keys(out).length > 0 ? out : null;
}

export function primaryClassificationMetricSummary(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.task_type !== "classification" || !record.splits || typeof record.splits !== "object") return null;

  const splits = record.splits as Record<string, unknown>;
  const declared = typeof record.primary_split === "string" ? record.primary_split : "";
  const primary = [declared, "test", "cv", "train"].find((name) => {
    const candidate = splits[name];
    return candidate && typeof candidate === "object" && !Array.isArray(candidate);
  });
  if (!primary) return null;

  const metrics = splits[primary] as Record<string, unknown>;
  const summary: Record<string, unknown> = {
    task_type: "classification",
    primary_split: primary,
    n_classes: record.n_classes,
    classes: record.classes,
  };
  const matrices = record.confusion_matrices;
  if (matrices && typeof matrices === "object" && !Array.isArray(matrices)) {
    const matrix = (matrices as Record<string, unknown>)[primary];
    if (Array.isArray(matrix)) {
      const nSamples = matrix.flatMap((row) => Array.isArray(row) ? row : []).reduce<number>(
        (total, item) => typeof item === "number" && Number.isFinite(item) ? total + item : total,
        0,
      );
      if (nSamples > 0) summary.n_samples = nSamples;
    }
  }
  for (const [source, target] of [
    ["accuracy", "accuracy"],
    ["balanced_accuracy", "balanced_accuracy"],
    ["precision_macro", "macro_precision"],
    ["recall_macro", "macro_recall"],
    ["specificity_macro", "macro_specificity"],
    ["f1_macro", "macro_f1"],
  ]) {
    summary[target] = metrics[source];
  }
  return summary;
}

export function collectCanonicalClassificationMetrics(
  value: unknown,
  out: Record<string, unknown>,
  depth = 0,
): void {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  if (depth > 4) return;
  const record = value as Record<string, unknown>;
  const canonical = flattenClassificationMetricsContract(record);
  if (canonical) {
    Object.assign(out, canonical);
    return;
  }

  for (const key of ["metrics", "classification_metrics"]) {
    collectCanonicalClassificationMetrics(record[key], out, depth + 1);
  }
}
