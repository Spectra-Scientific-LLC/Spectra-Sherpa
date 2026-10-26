import { describe, expect, it } from "vitest";
import { scientificMatrixColumns, scientificMatrixRowLabels } from "@/utils/scientificMatrixColumns";
import type { NodeOutput } from "@/utils/nodeOutput";

describe("declared scientific matrix columns", () => {
  it("reads exact row-axis labels without borrowing similarly sized metadata", () => {
    const output = { data: [[1], [2]], metadata: { sample_labels: ["stale A", "stale B"] },
      presentation_value: { y_axis: { labels: ["Specimen 135", "Specimen 142"] } } } as NodeOutput;
    expect(scientificMatrixRowLabels(output, 2)).toEqual(["Specimen 135", "Specimen 142"]);
    expect(scientificMatrixRowLabels(output, 1)).toEqual([]);
    expect(scientificMatrixRowLabels({ ...output,
      presentation_value: { y_axis: { labels: ["", "B"] } } }, 2)).toEqual([]);
  });
  it("uses the loading variable axis even when component labels have the same length", () => {
    const output = { data: [[1, 2]], metadata: { pc_labels: ["PC1", "PC2"], feature_names: ["stale", "stale"] },
      presentation_value: { feature_axis: { labels: ["sepal length", "petal width"] } },
      descriptor: { dimensions: [{ role: "component", size: 1 }, { role: "feature", size: 2 }] },
    } as unknown as NodeOutput;
    expect(scientificMatrixColumns(output, 2)).toEqual(["sepal length", "petal width"]);
  });
  it("uses a declared component axis for scores, never source variable labels", () => {
    const output = { metadata: { pc_labels: ["PC1", "PC2"], feature_names: ["length", "width"] },
      descriptor: { dimensions: [{ role: "sample", size: 2 }, { role: "component", size: 2 }] },
    } as unknown as NodeOutput;
    expect(scientificMatrixColumns(output, 2)).toEqual(["PC1", "PC2"]);
  });
  it("uses reference class identities for confusion columns", () => {
    expect(scientificMatrixColumns({ metadata: {
      type: "ClassificationTest", labels: ["setosa", "virginica"], pc_labels: ["LV1", "LV2"],
    } } as NodeOutput, 2)).toEqual(["setosa", "virginica"]);
  });
  it("carries heterogeneous peak units into the table and CSV headings", () => {
    expect(scientificMatrixColumns({ metadata: {
      feature_names: ["peak_position_1", "magnitude_at_peak_1"],
      column_units: { peak_position_1: "cm-1", magnitude_at_peak_1: "absorbance" },
    } } as NodeOutput, 2)).toEqual(["peak_position_1 (cm-1)", "magnitude_at_peak_1 (absorbance)"]);
  });
  it("does not establish column identity from an unrelated matching row count", () => {
    expect(scientificMatrixColumns({ metadata: { sample_labels: ["A", "B"], pc_labels: ["PC1", "PC2"] } } as NodeOutput, 2))
      .toEqual(["Col_1", "Col_2"]);
  });
});
