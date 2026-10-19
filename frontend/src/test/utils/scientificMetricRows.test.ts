import { describe, expect, it } from "vitest";
import { classificationMetricRows } from "@/utils/scientificMetricRows";
import { t2QDiagnosticRows } from "@/utils/scientificPlots";

describe("retained scientific records", () => {
  it("retains overall and per-class evaluator metrics without computing missing values", () => {
    const rows = classificationMetricRows({ task_type: "classification", n_samples: 11,
      accuracy: 9 / 11, macro_f1: 5 / 9,
      per_class: [{ label: "A", support: 7, precision: 1 }, { label: "B", support: 2, precision: null }] });
    expect(rows).toHaveLength(6);
    expect(rows?.[1]).toMatchObject({ Class: "Overall", Metric: "accuracy", Value: 9 / 11 });
    expect(rows?.[4]).toMatchObject({ Class: "A", Metric: "precision", Value: 1 });
    expect(rows?.some(row => row.Class === "B" && row.Metric === "precision")).toBe(false);
  });
  it("reports split metrics rather than classifier configuration", () => {
    const rows = classificationMetricRows({ task_type: "classification", n_neighbors: 5,
      splits: { train: { accuracy: .98, f1_macro: .97 }, test: { accuracy: .91 } } });
    expect(rows).toHaveLength(3);
    expect(rows?.[0]).toEqual({ Split: "train", Scope: "Calibration fit (not validation)", Metric: "accuracy", Value: .98 });
    expect(rows?.[2].Split).toBe("test");
    expect(classificationMetricRows({ accuracy: .9 })).toBeNull();
  });
  it("does not turn missing screening decisions into negative decisions", () => {
    expect(t2QDiagnosticRows({ T2: [1, 2], Q: [.1, .2] }, { sample_labels: ["A", "B"] })).toEqual([
      { sample: "A", t2: 1, q: .1, outlier: null }, { sample: "B", t2: 2, q: .2, outlier: null },
    ]);
    expect(t2QDiagnosticRows({ T2: [1], Q: [.1], flags: [false] })[0].outlier).toBe(false);
  });
});
