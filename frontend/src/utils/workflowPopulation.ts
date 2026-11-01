import type { NodeOutput, PortOutput } from "@/utils/nodeOutput";
import { enrichDeclaredContext, resolvePortPayload } from "@/utils/nodeOutput";
import { projectScientificPresentation, projectedPresentationIdentity, resolveScientificPresentation } from "@/utils/scientificPresentation";

export interface WorkflowObservation {
  observation_ref: string;
  source_row: number;
  sample_id: string | null;
  sample_label: string | null;
  source_included: boolean;
  included: boolean;
  workflow_excluded: boolean;
  result_row: number | null;
}
export interface WorkflowPopulation {
  schema_version: "spectrasherpa-workflow-population/1";
  source_node_id: string;
  source_digest: string;
  source_count: number;
  active_count: number;
  workflow_excluded_count: number;
  identity_basis: "typed_sample_id" | "source_bound_row";
  rows: WorkflowObservation[];
}
export interface WorkflowPopulationActions {
  scope?(): string;
  /** Exact source maps for inspection; never computational or projected rows. */
  populations?(): WorkflowPopulation[];
  resolve(ref: string): { excluded: boolean; restorable: boolean } | null;
  change(refs: string[], exclude: boolean): void;
}
export const WORKFLOW_POPULATION_ACTIONS = "workflow-population-actions";

/** Display-only companion. Tables, exports and computational ports stay active. */
export function populationPlotOutput(output: NodeOutput | null): NodeOutput | null {
  const population = output?.metadata?.workflow_population as {
    outputs?: Record<string, unknown>; availability?: string;
  } | undefined;
  if (!output || !population?.outputs || output.metadata.workflow_population_projected) return output;
  const ports = Object.fromEntries(Object.entries(output.ports ?? {}).map(([name, port]) =>
    [name, { ...port, metadata: { ...port.metadata } }]));
  for (const [name, value] of Object.entries(population.outputs)) {
    const payload = resolvePortPayload(value);
    ports[name] = { ...ports[name], data: Array.isArray(payload?.data) ? payload.data : Array.isArray(value) ? value : [],
      metadata: payload?.metadata ?? {}, descriptor: undefined, value } as PortOutput;
  }
  // Reapply the same declared context used for computational results. The
  // active cohort's labels/descriptors cannot describe a larger display cohort.
  enrichDeclaredContext(population.outputs, ports, output.presentation_contract);
  const axis = population.outputs.observation_axis;
  const raw = { ...output, ports, metadata: { ...output.metadata,
    workflow_population_projected: true, ...(axis ? { observation_axis: axis } : {}) } };
  const identity = projectedPresentationIdentity(output);
  if (identity) {
    const resolved = resolveScientificPresentation(null, raw, identity.presentation_id);
    return projectScientificPresentation(raw, resolved) ?? output;
  }
  const primary = output.primary_port && ports[output.primary_port];
  return primary && output.primary_port! in population.outputs
    ? { ...raw, data: primary.data, metadata: { ...raw.metadata, ...primary.metadata } }
    : raw;
}

export function observationAxisRefs(axis: unknown, rows: number): string[] | null {
  const refs = (axis as { workflow_observation_refs?: unknown } | null)?.workflow_observation_refs;
  return Array.isArray(refs) && refs.length === rows && refs.every(ref => typeof ref === "string")
    && new Set(refs).size === rows ? refs : null;
}

export function observationTraceContext(axis: unknown, rows: number, indices?: number[]) {
  const refs = observationAxisRefs(axis, rows);
  const mask = (axis as { include_mask?: boolean[] } | null)?.include_mask;
  if (!refs || (mask && (mask.length !== rows || mask.some(flag => typeof flag !== "boolean")))) return {};
  const selected = indices ?? refs.map((_, i) => i);
  return { workflow_observation_refs: selected.map(i => refs[i]),
    workflow_included: selected.map(i => mask?.[i] !== false) };
}

export function observationTraceMetadata(axis: unknown, rows: number, indices?: number[]) {
  const meta = observationTraceContext(axis, rows, indices);
  return "workflow_observation_refs" in meta ? { meta } : {};
}
