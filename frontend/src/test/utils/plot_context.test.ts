import { describe, expect, it } from "vitest";
import { plotContext } from "@/utils/plotContext";

describe("one plot context disclosure", () => {
  const p = { shown: 50, total: 150, method: "first_rows", excluded: 0 };
  const comparison = (other = p) => ({ meta: {
    display_population: p,
    comparison_populations: { original: p, preprocessed: other },
    comparison_scale_notice: "Panels use independent axes.",
  } });
  it("states identical panel counts once, without redundant percentages or omission arithmetic", () => {
    expect(plotContext(comparison())).toBe("Both panels: 50 of 150 active rows (first active rows). Panels use independent axes.");
  });
  it("retains differing populations and exclusions rather than implying equal cohorts", () => {
    expect(plotContext(comparison({ ...p, total: 99, excluded: 51 }))).toBe(
      "Original: 50 of 150 active rows (first active rows). Preprocessed: 50 of 99 active rows (first active rows); 51 excluded rows. Panels use independent axes.",
    );
  });
  it("combines display settings and optional styling context without losing either", () => {
    expect(plotContext(comparison(), "Metadata styling unavailable.", "20 traces")).toContain(
      "Panels use independent axes. Metadata styling unavailable. Display settings additionally omit 20 traces.",
    );
  });
  it("does not invent a disclosure for an ordinary complete plot", () => {
    expect(plotContext({})).toBe("");
    expect(plotContext({ meta: { display_population: { shown: 5, total: 5 } } })).toBe("");
  });
  it("preserves physical-baseline and color-limit meaning in standalone and comparison heatmaps", () => {
    const sequential = "Sequential color scale; limits follow this displayed matrix. Physical baseline unspecified.";
    const signed = "Symmetric color limits about numerical zero (±2). Declared value semantics.";
    expect(plotContext({ meta: { color_encoding_notice: sequential } })).toBe(sequential);
    expect(plotContext({ meta: { comparison_color_notices: { original: sequential, preprocessed: signed } } })).toBe(
      `Original: ${sequential} Preprocessed: ${signed}`,
    );
    expect(plotContext({ meta: { comparison_color_notices: { original: sequential, preprocessed: sequential } } })).toBe(
      `Both panels: ${sequential}`,
    );
  });
  it("retains independently scaled heatmap context and feature exclusions", () => {
    const layout = comparison({ ...p, excluded_features: 3 } as typeof p);
    layout.meta.comparison_scale_notice = "Panels use independent axes and color scales.";
    expect(plotContext(layout)).toContain("3 excluded features");
    expect(plotContext(layout)).toContain("independent axes and color scales");
  });
});
