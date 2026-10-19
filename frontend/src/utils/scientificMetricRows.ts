import { evaluationRoleLabel } from "./scientificDisplay";
/** Project retained classification metrics, without recomputing or promoting their scope. */
export function classificationMetricRows(value: unknown): Record<string, unknown>[] | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.task_type !== "classification") return null;
  const rows: Record<string, unknown>[] = [];
  // Evaluator records retain overall and per-class quantities together. Do
  // not discard the overall quantities when a per_class array is present.
  if (!record.splits) {
    if (!Array.isArray(record.per_class)) return null;
    const scope = evaluationRoleLabel(typeof record.evaluation_scope === "string" ? record.evaluation_scope : "unqualified_evaluation");
    for (const metric of ["n_samples", "accuracy", "balanced_accuracy", "macro_precision", "macro_recall", "macro_specificity", "macro_f1"]) {
      const result = record[metric];
      if (typeof result === "number" && Number.isFinite(result)) {
        rows.push({ Split: "evaluation", Scope: scope, Class: "Overall", Metric: metric, Value: result });
      }
    }
    for (const item of record.per_class) {
      if (!item || typeof item !== "object" || item.label == null) continue;
      for (const metric of ["support", "predicted_count", "precision", "recall", "specificity", "f1"]) {
        const result = item[metric];
        if (typeof result === "number" && Number.isFinite(result)) {
          rows.push({ Split: "evaluation", Scope: scope, Class: String(item.label), Metric: metric, Value: result });
        }
      }
    }
    return rows;
  }
  if (typeof record.splits !== "object") return null;
  for (const [split, metrics] of Object.entries(record.splits)) {
    if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) continue;
    for (const [metric, result] of Object.entries(metrics)) {
      if (typeof result !== "number" || !Number.isFinite(result)) continue;
      rows.push({ Split: split, Scope: evaluationRoleLabel(split === "train" ? "calibration" : split === "cv" ? "cross_validation" : "unqualified_evaluation"), Metric: metric, Value: result });
    }
  }
  return rows;
}
