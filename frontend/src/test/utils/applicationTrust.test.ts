import { describe, expect, it } from "vitest";
import { applicationTrustView, retainedNodeTrustView } from "@/utils/applicationTrust";

describe("retained application trust", () => {
  it("keeps PLS-DA rows aligned and labels screening as unqualified", () => {
    const view = applicationTrustView({
      artifact_uid: "model-1", model_type: "plsda", sample_indices: [2, 5], predictions: ["A", "B"],
      applicability: {
        method: "prediction_f_and_residual_spectrum_0.95_strict_greater", claim_scope: "provisional_calibration_screening",
        reference_samples: 12, t2_limit: 4, q_limit: 1,
        rows: [
          { row_index: 0, screening_status: "within_global_screen", t2: 2, q: 0.3 },
          { row_index: 1, screening_status: "outside_global_screen", t2: 5, q: 0.4 },
        ],
      },
    });
    expect(view?.rows.map(row => [row.sampleIndex, row.prediction, row.status])).toEqual([
      [2, "A", "within_global_screen"], [5, "B", "outside_global_screen"],
    ]);
    expect(view?.claimScope).toContain("unqualified");
  });

  it("refuses reordered diagnostic rows instead of assigning another prediction's T²/Q", () => {
    const view = applicationTrustView({
      artifact_uid: "model-4", model_type: "plsda", sample_indices: [2, 5], predictions: ["A", "B"],
      applicability: {
        method: "prediction_f_and_residual_spectrum_0.95_strict_greater", claim_scope: "provisional_calibration_screening",
        rows: [
          { row_index: 1, screening_status: "within_global_screen", t2: 2, q: 0.3 },
          { row_index: 0, screening_status: "outside_global_screen", t2: 5, q: 0.4 },
        ],
      },
    });
    expect(view?.rows.map(row => row.status)).toEqual(["unavailable", "unavailable"]);
    expect(view?.rows.map(row => row.t2)).toEqual([null, null]);
  });

  it("shows missing or mismatched row evidence as unavailable", () => {
    const view = applicationTrustView({
      artifact_uid: "model-2", model_type: "plsda", sample_indices: [0, 1], predictions: ["A", "B"],
      applicability: { rows: [{ screening_status: "within_global_screen", t2: 1, q: 1 }] },
    });
    expect(view?.rows.map(row => row.status)).toEqual(["unavailable", "unavailable"]);
    expect(view?.rows[0].reason).toContain("No fitted");
  });

  it("does not turn a legacy PLS applicability gap into a pass", () => {
    const view = applicationTrustView({
      artifact_uid: "model-3", model_type: "pls", sample_indices: [7], predictions: [[1.2]],
      applicability: { out_of_domain: [null], unavailable_reason: "refit_required" },
    });
    expect(view?.rows[0]).toMatchObject({ sampleIndex: 7, status: "unavailable", reason: "refit_required" });
  });

  it("projects a separately retained per-file screen only when row positions reconcile", () => {
    const screening = {
      claim_scope: "provisional_calibration_screening", method: "fitted_global_screen",
      rows: [
        { row_index: 0, screening_status: "within_global_screen", t2: 1, q: 0.1 },
        { row_index: 1, screening_status: "outside_global_screen", t2: 6, q: 0.2 },
      ],
    };
    expect(retainedNodeTrustView("file_0::model", screening, ["A", "B"])?.rows.map(row => row.status))
      .toEqual(["within_global_screen", "outside_global_screen"]);
    screening.rows.reverse();
    expect(retainedNodeTrustView("file_0::model", screening, ["A", "B"])?.rows.map(row => row.status))
      .toEqual(["unavailable", "unavailable"]);
  });

  it("pairs fitted PLS regression screening with the exact result port", () => {
    const screening = { claim_scope: "provisional_calibration_screening", method: "fitted_global_screen",
      out_of_domain: [false, true], hotelling_t2: [1, 5], q_residuals: [0.2, 0.3] };
    const view = retainedNodeTrustView("file_0::regression", screening, [[1.2], [1.4]]);
    expect(view?.modelType).toBe("pls");
    expect(view?.rows.map(row => [row.prediction, row.status])).toEqual([
      [[1.2], "within_global_screen"], [[1.4], "outside_global_screen"],
    ]);
    expect(retainedNodeTrustView("file_0::regression", screening, [1.2])).toBeNull();
  });
});
