export interface DatasetTargetAuthority {
  hasEmbeddedTarget?: boolean;
  targetType?: string | null;
  targetFields?: string[] | null;
}

export const MODEL_NEUTRAL_DATASET_SOURCES = [
  "registered",
  "synthetic",
  "eigenvector",
  "oes",
  "sklearn",
] as const;

export function targetRequirementLabel(requiredType: string | null): string | null {
  if (requiredType === "continuous") return "a numeric target";
  if (requiredType === "categorical") return "categorical class labels";
  return requiredType ? `a ${requiredType} target` : null;
}

export function datasetTargetRequirementWarning(
  requiredType: string | null,
  dataset: DatasetTargetAuthority | null,
): string | null {
  const requirement = targetRequirementLabel(requiredType);
  if (!requirement || !dataset) return null;

  if (!dataset.hasEmbeddedTarget || !dataset.targetFields?.length) {
    return `This dataset has no declared target. This analysis requires ${requirement}. Choose a dataset with the required labels, or use this dataset with an unsupervised analysis such as PCA.`;
  }
  if (dataset.targetType !== requiredType) {
    const present = targetRequirementLabel(dataset.targetType || null) || "a different target type";
    return `This dataset provides ${present}, but this analysis requires ${requirement}. Choose a compatible target or a different analysis.`;
  }
  return null;
}

export function datasetMeetsTargetRequirement(
  requiredType: string | null,
  dataset: DatasetTargetAuthority | null,
): boolean {
  return datasetTargetRequirementWarning(requiredType, dataset) === null;
}
