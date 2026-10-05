import { describe, expect, it } from "vitest";
import { featureColumnOptions } from "@/utils/featureColumnOptions";

describe("canonical feature column choices", () => {
  it("uses all exact peak measurement labels from a serialized input", () => {
    const labels = Array.from({ length: 44 }, (_, i) => `measurement_${i + 1}`);
    expect(featureColumnOptions({ value: { x_axis: { labels }, shape: [155, 44] } })).toEqual(labels);
  });
  it("uses one-based column names for an unnamed spectral axis", () => {
    expect(featureColumnOptions({ default: { x_axis: { data: [600, 602] }, shape: [155, 2] } }))
      .toEqual(["Column 1", "Column 2"]);
    expect(featureColumnOptions(null)).toEqual([]);
    expect(featureColumnOptions({ shape: [155, 1], metadata: { feature_names: ["Column 2"] } }))
      .toEqual(["Column 2"]);
    expect(featureColumnOptions({ shape: [155, -1] })).toEqual([]);
  });
});
