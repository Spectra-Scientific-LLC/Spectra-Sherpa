import { describe, expect, it } from "vitest";
import { scientificMatrixColumns, scientificMatrixRowLabels } from "@/utils/scientificMatrixColumns";
import type { NodeOutput } from "@/utils/nodeOutput";

describe("declared scientific matrix columns", () => {
  it("normalizes finite numeric display labels without inventing sample identity", () => {
    expect(scientificMatrixRowLabels({ metadata: { sample_labels: [101, 102] } } as NodeOutput, 2))
      .toEqual(["101", "102"]);
    for (const labels of [[NaN, 102], [Infinity, 102], [null, 102], ["", 102]]) {
      expect(scientificMatrixRowLabels({ descriptor: { dimensions: [{ labels }] },
        metadata: { sample_labels: ["stale A", "stale B"] } } as unknown as NodeOutput, 2)).toEqual([]);
    }
  });
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


describe("declared confusion reference rows", () => {
  const classes = ["class_0", "class_1", "class_2"];
  const confusion = (sampleCount = 134) => ({
    data: [[44, 0, 0], [2, 50, 2], [0, 0, 36]],
    descriptor: { scientific_kind: "confusion_matrix", shape_valid: true, shape: [3, 3],
      dimensions: [{ role: "actual_class", size: 3 }, { role: "predicted_class", size: 3 }] },
    metadata: { classes, diagnostics: { classes,
      sample_labels: Array.from({ length: sampleCount }, (_, i) => `stale specimen ${i}`) } },
  } as unknown as NodeOutput);

  it.each([134, 3])("uses class identity, not %i sample labels", sampleCount => {
    const output = confusion(sampleCount);
    const original = structuredClone(output);
    expect(scientificMatrixRowLabels(output, 3)).toEqual(classes);
    expect(scientificMatrixColumns(output, 3)).toEqual(classes);
    expect(output).toEqual(original);
    delete output.metadata.classes;
    expect(scientificMatrixRowLabels(output, 3)).toEqual(classes);
  });

  it("preserves explicit reference order and finite numeric labels", () => {
    const output = confusion();
    output.descriptor!.dimensions[0].labels = ["C", "A", "B"];
    expect(scientificMatrixRowLabels(output, 3)).toEqual(["C", "A", "B"]);
    output.descriptor!.dimensions[0].labels = [10, 20, 30] as unknown as string[];
    expect(scientificMatrixRowLabels(output, 3)).toEqual(["10", "20", "30"]);
  });

  it.each([[], ["A", "B"], ["A", "", "C"], ["A", NaN, "C"], ["A", null, "C"]].map(labels => ({ labels })))(
    "refuses invalid typed labels without class fallback: %j", ({ labels }) => {
      const output = confusion();
      output.descriptor!.dimensions[0].labels = labels as string[];
      expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
    },
  );

  it("refuses invalid typed value-axis labels and class metadata without fallback", () => {
    const output = confusion(3);
    output.presentation_value = { y_axis: { labels: ["A", "B"] } };
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
    delete output.presentation_value;
    output.metadata.classes = ["A", "B"];
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
    output.metadata.classes = classes;
    output.descriptor!.dimensions[0].size = 2;
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
  });

  it.each(["sample", "feature", "component"])("refuses a contradictory %s row role", role => {
    const output = confusion(3);
    output.descriptor!.dimensions[0].role = role;
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
  });

  it("does not infer class rows from a square shape or matching class count", () => {
    const output = confusion();
    delete output.descriptor;
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
    output.metadata = { classes };
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
  });

  it("never borrows matching sample labels when declared classes are absent", () => {
    const output = confusion(3);
    output.metadata = { sample_labels: ["stale A", "stale B", "stale C"],
      diagnostics: { sample_labels: ["stale A", "stale B", "stale C"] } };
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
  });

  it("accepts declared confusion identity without dimension labels, but refuses an invalid shape", () => {
    const output = confusion();
    output.descriptor!.dimensions = [];
    expect(scientificMatrixRowLabels(output, 3)).toEqual(classes);
    output.descriptor!.shape_valid = false;
    expect(scientificMatrixRowLabels(output, 3)).toEqual([]);
  });
});
