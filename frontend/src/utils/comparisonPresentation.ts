import type { EvidenceComparison, EvaluationRole } from "@/types/scientificComparison";
import { scientificNumber } from "@/utils/scientificEncoding";

type Pair = EvidenceComparison["pairs"][number];
/** Direction is meaningful only inside a server-qualified comparison role. */
export function metricPreference(metric: string, left: number, right: number): "better" | "worse" | "equal" | null {
  if (![left, right].every(Number.isFinite)) return null;
  if (metric === "bias") { left = Math.abs(left); right = Math.abs(right); }
  const lower = ["rmse", "mse", "mae", "sep", "bias"].includes(metric);
  const higher = ["r2", "accuracy", "balanced_accuracy", "macro_f1", "mcc"].includes(metric);
  if (!lower && !higher) return null; // RER, for example, also depends on reference range.
  if (left === right) return "equal";
  return (lower ? right < left : right > left) ? "better" : "worse";
}
export function comparisonVerdict(evidence: EvidenceComparison, pair: Pair): string | null {
  // Prefer held-out prediction, then out-of-fold development error. Calibration
  // fit alone never establishes which model predicts better.
  for (const role of ["held_out", "training_cv"] as EvaluationRole[]) {
    const section = pair.sections.find(s => s.role === role && s.state === "comparable");
    const values = section?.metric_values.rmse;
    const leftUnits = evidence.items[pair.left_index]?.sections[role]?.population.units;
    const rightUnits = evidence.items[pair.right_index]?.sections[role]?.population.units;
    if (!values || !leftUnits || leftUnits !== rightUnits ||
      ![values.left, values.right].every(Number.isFinite)) continue;
    const title = role === "held_out" ? "held-out error" : "cross-validation error";
    const metric = role === "held_out" ? "RMSEP" : "RMSECV";
    const first = pair.left_index + 1, second = pair.right_index + 1;
    const origins = [pair.left_index, pair.right_index].some(index => evidence.items[index]?.reference.kind === "external")
      ? ` Evaluations: Run ${first}: ${evidence.items[pair.left_index].label}; Run ${second}: ${evidence.items[pair.right_index].label}.` : "";
    if (values.left === values.right) return `Runs ${first} and ${second} have equal ${title}: ${metric} ${scientificNumber(values.left, { significantDigits: 4 })} ${leftUnits}.${origins}`;
    const winner = values.right < values.left ? second : first;
    const low = Math.min(values.left, values.right), high = Math.max(values.left, values.right);
    return `Run ${winner} has lower ${title}: ${metric} ${scientificNumber(low, { significantDigits: 4 })} vs ${scientificNumber(high, { significantDigits: 4 })} ${leftUnits}.${origins}`;
  }
  return null;
}
