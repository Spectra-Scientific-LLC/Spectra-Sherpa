import { describe, expect, it } from "vitest";
import {
  buildDiagnosticEntries,
  formatDiagnosticLabel,
  formatDiagnosticValue,
  isEmptyDiagnosticValue,
} from "@/utils/diagnostics";

describe("diagnostics formatting", () => {
  it("filters empty and non-finite values from compact diagnostic entries", () => {
    const entries = buildDiagnosticEntries({
      train_accuracy: 0.987654,
      cv_accuracy: Number.NaN,
      component_limit_warning: null,
      warnings: [],
      notes: "",
      effective_n_components: 5,
    });

    expect(entries.map((entry) => entry.key)).toEqual(["train_accuracy", "effective_n_components"]);
    expect(entries[0].label).toBe("Train Accuracy");
    expect(entries[0].displayValue).toBe("0.9877");
    expect(entries[1].displayValue).toBe("5");
  });

  it("keeps compact diagnostics clear of duplicated structured result containers", () => {
    const entries = buildDiagnosticEntries({
      metrics: {
        task_type: "classification",
        splits: { cv: { accuracy: 0.9 } },
      },
      confusion_matrices: { cv: [[3, 0], [1, 2]] },
      n_classes: 2,
      probability_method: "softmax",
    });

    expect(entries.map((entry) => entry.key)).toEqual(["n_classes", "probability_method"]);
  });

  it("summarizes short objects and arrays without rendering blank strings", () => {
    expect(formatDiagnosticValue({ selected: 12, total: 40 })).toBe("Selected: 12; Total: 40");
    expect(formatDiagnosticValue([[1, 0], [0, 1]])).toBe("2 x 2 matrix");
    expect(formatDiagnosticValue([1, 2, 3])).toBe("1, 2, 3");
    expect(isEmptyDiagnosticValue({ a: null, b: [] })).toBe(true);
  });

  it("formats common scientific abbreviations in labels", () => {
    expect(formatDiagnosticLabel("cv_rmse")).toBe("CV RMSE");
    expect(formatDiagnosticLabel("snr_before")).toBe("SNR Before");
    expect(formatDiagnosticLabel("hotelling_t2_limit")).toBe("Hotelling T2 Limit");
  });
});
