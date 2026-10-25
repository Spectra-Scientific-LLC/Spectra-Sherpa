import { describe, expect, it } from "vitest";
import {
  buildDiagnosticEntries,
  formatDiagnosticLabel,
  formatDiagnosticValue,
  isEmptyDiagnosticValue,
} from "@/utils/diagnostics";

describe("diagnostics formatting", () => {
  it("keeps executed peak arguments and row indices in their canonical details block", () => {
    expect(buildDiagnosticEntries({ n_peaks: 133,
      scipy_find_peaks_arguments: { prominence: 0.1 },
      scipy_peak_widths_sample_indices: [0, 1, 2],
    }).map(entry => entry.key)).toEqual(["n_peaks"]);
  });
  it("does not suppress a new field just because its name ends in definition", () => {
    expect(buildDiagnosticEntries({ population_definition: "independent specimens" }))
      .toEqual([{ key: "population_definition", label: "Population Definition", displayValue: "independent specimens", detail: undefined }]);
  });

  it("keeps MCR fit values compact and formulas in hover without altering retained metadata", () => {
    const metadata = { n_components: 3, residual_rms: 0.005532, lof_percent: 10.99,
      lof_definition: "100 * sqrt(sum(residual^2) / sum(X^2))",
      fitted_state_serializer: "spectrasherpa.model-artifact.mcr-als/2" };
    const entries = buildDiagnosticEntries(metadata);
    expect(entries.map(entry => entry.key)).toEqual(["n_components", "residual_rms", "lof_percent"]);
    expect(entries[2].detail).toBe(metadata.lof_definition);
    expect(metadata.fitted_state_serializer).toBe("spectrasherpa.model-artifact.mcr-als/2");
  });

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

  it("explains when selection retains every variable and omits worker internals", () => {
    const entries = buildDiagnosticEntries({
      n_selected: 5401, n_total: 5401, n_resamples: 100,
      worker_execution: { worker_pid: 123, execution_id: "private-runtime-id" },
    });
    expect(entries.map((entry) => entry.key)).toEqual(["n_selected", "n_resamples"]);
    expect(entries[0].displayValue).toBe("All 5,401 variables retained; none excluded");
    expect(buildDiagnosticEntries({ n_selected: 20, n_total: 100 })[0].displayValue)
      .toBe("20 of 100 variables retained");
  });

  it("summarizes short objects and arrays without rendering blank strings", () => {
    expect(formatDiagnosticValue({ selected: 12, total: 40 })).toBe("Selected: 12; Total: 40");
    expect(formatDiagnosticValue([[1, 0], [0, 1]])).toBe("2 x 2 matrix");
    expect(formatDiagnosticValue([1, 2, 3])).toBe("1, 2, 3");
    expect(isEmptyDiagnosticValue({ a: null, b: [] })).toBe(true);
  });

  it("formats common scientific abbreviations in labels", () => {
    expect(formatDiagnosticLabel("cv_rmse")).toBe("CV RMSE");
    expect(formatDiagnosticLabel("mae")).toBe("MAE");
    expect(formatDiagnosticLabel("r2")).toBe("R²");
    expect(formatDiagnosticLabel("sep")).toBe("SEP");
    expect(formatDiagnosticLabel("rer")).toBe("RER");
    expect(formatDiagnosticLabel("snr_before")).toBe("SNR Before");
    expect(formatDiagnosticLabel("hotelling_t2_limit")).toBe("Hotelling T2 Limit");
  });
});
