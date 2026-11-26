import { describe, expect, it } from "vitest";
import { appliedResultTable } from "@/utils/appliedResultTable";
import { columnDecimals } from "@/utils/scientificDisplay";

const ids = ["s-1", "s-2"];
const table = (values: Record<string, unknown>, port = "result", label: string | null = "Applied Result Matrix") =>
  appliedResultTable(values, port, ids, label, columnDecimals);

describe("applied saved-model result table", () => {
  it("calls a regression result predictions only when the run saved it as predictions", () => {
    const regression = table({ result: [[8.6], [9.1]], y_pred: [[8.6], [9.1]] });
    expect(regression).toMatchObject({ title: "Predictions", columns: ["Predicted"] });
    expect(regression?.rows.map((row) => row.sample)).toEqual(ids);
    // The same matrix without saved predictions is not assumed to be predictions.
    expect(table({ result: [[8.6], [9.1]] })).toMatchObject({ title: "Applied Result Matrix", columns: ["Column"] });
  });

  it("names class responses by the saved classes beside the predicted class", () => {
    const result = table({
      result: [[0.9, 0.1], [0.2, 0.8]], labels: ["Pass", "Fail"],
      metadata: { classes: ["Pass", "Fail"], classification_output_semantics: "class_response_scores" },
    });
    expect(result?.title).toBe("Class responses");
    expect(result?.columns).toEqual(["Predicted class", "Pass", "Fail"]);
    expect(result?.rows[1].cells).toEqual(["Fail", 0.2, 0.8]);
    expect(result?.decimals[0]).toBeNull();
    expect(result?.title).not.toContain("Predict");
  });

  it("labels PCA scores by their own component axis, never as predictions", () => {
    const result = table({ result: { type: "SherpaDataset", title: "PCA Scores", data: [[1, 2], [3, 4]],
      x_axis: { labels: ["PC1", "PC2"] } } });
    expect(result).toMatchObject({ title: "PCA Scores", columns: ["PC1", "PC2"] });
  });

  it("follows the output the user selected", () => {
    const values = { result: [[0.9, 0.1], [0.2, 0.8]], labels: ["Pass", "Fail"], metadata: { classes: ["Pass", "Fail"] } };
    expect(table(values, "labels")).toMatchObject({ title: "Predicted classes", columns: ["Predicted class"] });
    expect(table(values, "applicability")).toBeNull();
  });

  it("keeps a missing value missing and refuses rows that do not match the samples", () => {
    expect(table({ result: [[8.6], [null]], y_pred: [] })?.rows[1].cells).toEqual([null]);
    expect(table({ result: [[8.6]], y_pred: [] })).toBeNull();
    expect(appliedResultTable({ result: [[1], [2]], y_pred: [] }, "result", null, null, columnDecimals)).toBeNull();
  });
});
