import type { components } from "@/types/api/v1";
import type { ExperimentFile, ExperimentSummary, ExperimentFileAssets, ExperimentDetail } from "@/types";

type Schemas = components["schemas"];

const workflowStages = {
  raw: true,
  preprocessed: true,
  synthetic: true,
} satisfies Record<Schemas["WorkflowSourceSelection"]["stage"], true>;

function isWorkflowStage(value: string): value is Schemas["WorkflowSourceSelection"]["stage"] {
  return Object.prototype.hasOwnProperty.call(workflowStages, value);
}

/** Narrow only on submission; historical file metadata remains readable. */
export function workflowSelectionStage(value: string): Schemas["WorkflowSourceSelection"]["stage"] {
  if (isWorkflowStage(value)) return value;
  throw new Error("Choose raw, preprocessed, or synthetic files for this workflow source.");
}

export function experimentSummary(value: Schemas["ExperimentSummary"]): ExperimentSummary {
  return { ...value, file_count: value.file_count ?? 0 };
}

export function experimentDetail(value: Schemas["ExperimentDetail"]): ExperimentDetail {
  return { ...value, file_count: value.file_count ?? 0 };
}

export function experimentFile(value: Schemas["ExperimentFileOut"]): ExperimentFile {
  return { ...value };
}

export function experimentFileAssets(value: Schemas["ExperimentFileAssetsOut"]): ExperimentFileAssets {
  return {
    ...value,
    assets: value.assets.map((asset) => ({ ...asset, warnings: asset.warnings ?? [] })),
  };
}
