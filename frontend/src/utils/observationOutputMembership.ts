import { observationAxisRefs } from "@/utils/workflowPopulation";
import { isProjectedScientificKind, scientificEvidenceShape } from "@/utils/scientificPresentation";
import type { NodeOutput } from "@/utils/nodeOutput";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue | null => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as RecordValue : null;

/** T²/Q declares its observation axis alongside its paired diagnostic ports. */
export function observationOutputAxis(output: NodeOutput | null): unknown {
  const value = record(output?.presentation_value);
  return value?.sample_axis ?? value?.y_axis ?? (isProjectedScientificKind(output, "t2_q_diagnostics")
    ? output?.metadata.observation_axis : null);
}

export function observationOutputRowCount(output: NodeOutput | null): number {
  return isProjectedScientificKind(output, "t2_q_diagnostics") ? scientificEvidenceShape(output)?.rows ?? 0
    : Array.isArray(output?.data) ? output.data.length : 0;
}

/** Exact membership in the retained computational output, never the optional
 * display projection or a same-sized upstream input. This is not fit authority. */
export function observationOutputMembership(output: unknown): Map<string, boolean> | null {
  const node = record(output);
  if (!node) return null;
  if (record(node.metadata)?.workflow_population_projected === true) return null;
  const value = record(node.presentation_value);
  const data = value?.data ?? node.data;
  if (!Array.isArray(data)) return null;
  const count = isProjectedScientificKind(node as unknown as NodeOutput, "t2_q_diagnostics")
    ? observationOutputRowCount(node as unknown as NodeOutput) : data.length;
  for (const shape of [record(node.descriptor)?.shape, value?.shape]) {
    if (shape != null && (!Array.isArray(shape) || !Number.isSafeInteger(shape[0]) || shape[0] !== count)) return null;
  }
  const axis = record(observationOutputAxis(node as unknown as NodeOutput));
  const refs = observationAxisRefs(axis, count);
  if (!refs) return null;
  const mask = axis?.include_mask;
  if (mask != null && (!Array.isArray(mask) || mask.length !== refs.length || mask.some(flag => typeof flag !== "boolean"))) return null;
  return new Map(refs.map((reference, index) => [reference, !Array.isArray(mask) || mask[index] !== false]));
}
