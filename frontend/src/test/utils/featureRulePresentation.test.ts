import { describe, expect, it } from "vitest";
import { bindPresentationInput, featureRulePresentation, centroidPresentation, outOfFoldIdentityPresentation } from "@/utils/featureRulePresentation";

describe("feature rule coordinate authority", () => {
  it("dispatches by the declared input port without inferring a node identity", () => {
    const output = { data: [true, false], metadata: {}, descriptor: { dimensions: [] } } as any;
    const inputs = { scientific_input: { value: { data: [[1, 2]], x_axis: { labels: ["A", "B"] } } } } as any;
    expect(bindPresentationInput(output, ["scientific_input", "feature_axis"], inputs)?.metadata.feature_names).toEqual(["A", "B"]);
    expect(bindPresentationInput(output, ["missing", "feature_axis"], inputs)).toBe(output);
    expect(bindPresentationInput(output, undefined, inputs)).toBe(output);
  });
  it("carries exact X row identities onto OOF rows without altering the bound evidence record", () => {
    const evidence = { observations: [1], predictions: [1.1], fold_assignments: [0] };
    const output = { data: [{ observation: 1, prediction: 1.1, fold_index: 0 }], metadata: {}, presentation_value: evidence };
    const result = outOfFoldIdentityPresentation(output, { value: { data: [[9, 8]], y_axis: { labels: ["corn-002"] } } } as any);
    expect(result?.data[0]).toMatchObject({ Sample: "corn-002", observation: 1 });
    expect(result?.presentation_value).toBe(evidence);
    expect(outOfFoldIdentityPresentation(output, { value: { data: [[9]], y_axis: { labels: ["A", "B"] } } } as any)).toBe(output);
  });
  it("labels canonical K-means rows by zero-based cluster and columns by fitted features", () => {
    const centroids = { data: [[1, 2], [3, 4]], metadata: { diagnostics: { n_clusters: 2 } }, descriptor: { dimensions: [] } } as any;
    const result = centroidPresentation(centroids, { value: { data: [[1, 2]], x_axis: { labels: ["A", "B"] } } } as any);
    expect(result?.metadata.cluster_labels).toEqual(["Cluster 0", "Cluster 1"]);
    expect(result?.metadata.feature_names).toEqual(["A", "B"]);
    expect(result?.descriptor?.dimensions[0].role).toBe("cluster");
    expect(centroidPresentation({ ...centroids, metadata: {} }, null)?.metadata.cluster_labels).toBeUndefined();
  });
  const output = { data: [true, false, true], metadata: {},
    descriptor: { dimensions: [{ role: "entry", size: 3 }] } } as any;
  it("uses the full X feature axis, not specimen or selected-feature labels", () => {
    const input = { value: { data: [[1, 2, 3]], x_axis: { data: [1100, 1102, 1104], units: "nm" },
      y_axis: { labels: ["specimen"] } } } as any;
    const result = featureRulePresentation(output, input);
    expect(result?.metadata.feature_names).toEqual(["1100", "1102", "1104"]);
    expect(result?.metadata.feature_coordinate_units).toBe("nm");
    expect(result?.descriptor?.dimensions[0].role).toBe("feature");
    expect(output.metadata).toEqual({});
  });
  it("refuses a mismatched or missing coordinate authority", () => {
    expect(featureRulePresentation(output, null)).toBe(output);
    expect(featureRulePresentation(output, { value: { data: [[1, 2]], x_axis: { data: [1100, 1104] } } } as any)).toBe(output);
  });
});
