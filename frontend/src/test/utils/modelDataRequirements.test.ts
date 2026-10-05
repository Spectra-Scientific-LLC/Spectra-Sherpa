import { describe, expect, it } from "vitest";
import {
  datasetMeetsTargetRequirement,
  datasetTargetRequirementWarning,
  MODEL_NEUTRAL_DATASET_SOURCES,
} from "@/utils/modelDataRequirements";

describe("model data requirements", () => {
  it("keeps user-acquired registered references in the model-neutral picker", () => {
    expect(MODEL_NEUTRAL_DATASET_SOURCES).toContain("registered");
  });

  it("warns when regression data has no target without binding the dataset to a model", () => {
    const warning = datasetTargetRequirementWarning("continuous", {
      hasEmbeddedTarget: false,
      targetType: null,
      targetFields: [],
    });

    expect(warning).toContain("no declared target");
    expect(warning).toContain("numeric target");
    expect(warning).toContain("PCA");
    expect(
      datasetMeetsTargetRequirement("continuous", {
        hasEmbeddedTarget: false,
        targetType: null,
        targetFields: [],
      }),
    ).toBe(false);
  });

  it("warns when classification receives a continuous response", () => {
    expect(
      datasetTargetRequirementWarning("categorical", {
        hasEmbeddedTarget: true,
        targetType: "continuous",
        targetFields: ["Moisture"],
      }),
    ).toBe(
      "This dataset provides a numeric target, but this analysis requires categorical class labels. Choose a compatible target or a different analysis.",
    );
  });

  it("accepts the required target type and leaves unsupervised analyses unrestricted", () => {
    const categorical = {
      hasEmbeddedTarget: true,
      targetType: "categorical",
      targetFields: ["species"],
    };
    expect(datasetTargetRequirementWarning("categorical", categorical)).toBeNull();
    expect(datasetMeetsTargetRequirement("categorical", categorical)).toBe(true);
    expect(datasetMeetsTargetRequirement(null, null)).toBe(true);
  });
});
