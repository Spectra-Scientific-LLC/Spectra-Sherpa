import { describe, expect, it } from "vitest";
import { regressionMetricPresentation, regressionMetricQualification } from "@/utils/regressionMetricPresentation";

describe("historical regression metric presentation", () => {
  it("withholds known mixed-response scalars throughout summary containers without rewriting evidence", () => {
    const original = {
      metadata: { n_targets: 2, rmse: 12, r2: .9, quality_summary: { rmse: 12 },
        per_target: [{ target_name: "A", rmse: 1 }, { target_name: "B", rmse: 17 }] },
    };
    const before = JSON.stringify(original);
    const projected = regressionMetricPresentation(original) as any;
    expect(projected.metadata.rmse).toBeUndefined();
    expect(projected.metadata.r2).toBeUndefined();
    expect(projected.metadata.quality_summary.rmse).toBeUndefined();
    expect(projected.metadata.legacy_aggregate_evidence.rmse).toBe(12);
    expect(projected.metadata.per_target).toEqual(original.metadata.per_target);
    expect(regressionMetricQualification(original)).toContain("unqualified");
    expect(JSON.stringify(original)).toBe(before);
  });
  it("preserves single-response and unrelated classification summaries", () => {
    for (const value of [{ n_targets: 1, rmse: 2 }, { accuracy: .9, class_names: ["A", "B"] }]) {
      expect(regressionMetricPresentation(value)).toEqual(value);
      expect(regressionMetricQualification(value)).toBeNull();
    }
  });
  it("retains current named per-response records without inventing aggregates", () => {
    const value = { metric_summary_scope: "per_response_only", per_target: [{ rmse_cal: 2 }, { rmse_cal: .01 }] };
    expect(regressionMetricPresentation(value)).toEqual(value);
  });
});
