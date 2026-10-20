import type { components } from "@/types/api/v1";
import type { ExecutionRunSummary, RunListItem, BatchPredictionResult } from "@/types";

type Schemas = components["schemas"];

export function runSummary(value: Schemas["ExecutionRunOut"]): ExecutionRunSummary {
  return {
    ...value,
    project_id: value.project_id ?? null,
    run_kind: value.run_kind ?? "other",
    params_snapshot: value.params_snapshot ?? {},
    results_summary: value.results_summary ?? {},
    labels: value.labels ?? null,
    source_type: value.source_type ?? null,
    source_metadata: value.source_metadata ?? null,
    produced_artifact_uids: value.produced_artifact_uids ?? null,
    attempted_artifact_uids: value.attempted_artifact_uids ?? null,
    succeeded_artifact_uids: value.succeeded_artifact_uids ?? null,
  };
}

/** List navigation must not invent full run evidence from a page projection. */
export function runListItem(value: Schemas["RunListItem"]): RunListItem {
  return { ...value };
}

export function batchPrediction(value: Schemas["BatchPredictionOut"]): BatchPredictionResult {
  return { ...value, model_id: value.model_id ?? null };
}
