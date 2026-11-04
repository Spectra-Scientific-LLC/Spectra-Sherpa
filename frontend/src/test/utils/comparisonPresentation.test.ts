import { describe, expect, it } from "vitest";
import { comparisonVerdict, metricPreference } from "@/utils/comparisonPresentation";
import type { EvidenceComparison, EvaluationRole } from "@/types/scientificComparison";

function comparison(left: number, right: number, role: EvaluationRole = "held_out") {
  const evidence = {
    items: ["First", "Second"].map(label => ({
      label, reference: { kind: "run" }, sections: { [role]: { population: { units: "ppm" } } },
    })),
    pairs: [{ left_index: 0, right_index: 1, sections: [{
      role, state: "comparable", metric_values: { rmse: { left, right, delta: right - left } },
    }] }],
  } as unknown as EvidenceComparison;
  return { evidence, pair: evidence.pairs[0] };
}

describe("metricPreference", () => {
  it.each([1e-12, 1, 1e12])("keeps numerical ties unchanged by unit scaling %s", scale => {
    expect(metricPreference("rmse", scale, (1 + 1e-14) * scale)).toBe("equal");
    expect(metricPreference("rmse", scale, 9 * scale)).toBe("worse");
    expect(metricPreference("rmse", 9 * scale, scale)).toBe("better");
  });

  it("does not infer an absolute zero threshold without response-scale evidence", () => {
    expect(metricPreference("bias", 4.42445e-15, -2.22748e-14)).toBe("worse");
    expect(metricPreference("rmse", 0, 1e-15)).toBe("worse");
    expect(metricPreference("rmse", 0, 0)).toBe("equal");
  });

  it("keeps real differences directional", () => {
    expect(metricPreference("rmse", 0.9183, 2.69)).toBe("worse");
    expect(metricPreference("bias", -16.2, 1.5)).toBe("better");
    expect(metricPreference("r2", 0.9, 0.95)).toBe("better");
  });

  it("leaves unsupported or non-finite metrics unranked", () => {
    expect(metricPreference("rer", 1, 2)).toBeNull();
    expect(metricPreference("rmse", Number.NaN, 2)).toBeNull();
    expect(metricPreference("rmse", 1, Infinity)).toBeNull();
  });
});

describe("comparisonVerdict", () => {
  it.each(["held_out", "training_cv"] as EvaluationRole[])("uses the badge's numerical tie rule for %s", role => {
    const { evidence, pair } = comparison(1, 1 + 1e-14, role);
    const before = structuredClone(evidence);
    expect(metricPreference("rmse", 1, 1 + 1e-14)).toBe("equal");
    expect(comparisonVerdict(evidence, pair)).toContain("numerically equal");
    expect(comparisonVerdict(evidence, pair)).not.toContain("lower");
    expect(evidence).toEqual(before);
  });

  it.each([1e-13, 1, 1e13])("does not hide a real difference in small units %s", scale => {
    const { evidence, pair } = comparison(scale, 9 * scale);
    expect(metricPreference("rmse", scale, 9 * scale)).toBe("worse");
    expect(comparisonVerdict(evidence, pair)).toContain("Run 1 has lower held-out error");
  });

  it("shows enough digits when four digits would conceal a directional difference", () => {
    const { evidence, pair } = comparison(1, 1.00001);
    expect(comparisonVerdict(evidence, pair)).toContain("RMSEP 1.00000 vs 1.00001 ppm");
  });

  it("does not issue a verdict for unqualified populations or missing units", () => {
    const { evidence, pair } = comparison(1, 2);
    pair.sections[0].state = "unavailable";
    expect(comparisonVerdict(evidence, pair)).toBeNull();
    pair.sections[0].state = "comparable";
    evidence.items[1].sections.held_out.population.units = null;
    expect(comparisonVerdict(evidence, pair)).toBeNull();
  });
});
