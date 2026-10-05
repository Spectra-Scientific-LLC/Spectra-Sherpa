import { describe, expect, it } from "vitest";
import { buildRegressionComparisonPlot } from "@/utils/scientificPlots";

describe("regression comparison population authority", () => {
  const rows = [
    { sample: "train-a", target: "Concentration", reference: 1, predicted: 1.1, residual: -0.1, role: "calibration" },
    { sample: "test-b", target: "Concentration", reference: 2, predicted: 2.1, residual: -0.1, role: "held_out_test" },
  ];
  it.each([{ input: rows }, { input: [...rows].reverse() }])("does not label pooled populations with the first row's role", ({ input }) => {
    const plot = buildRegressionComparisonPlot(input);
    const points = plot.data.filter((trace) => trace.mode === "markers");
    expect(points).toHaveLength(2);
    expect(points.map((trace) => trace.name).sort()).toEqual([
      "Concentration · calibration", "Concentration · held out test",
    ]);
    for (const trace of points) {
      expect(new Set((trace.customdata as unknown[][]).map((row) => row[1])).size).toBe(1);
    }
    expect(JSON.stringify(plot.layout.title)).toContain("multiple populations");
    expect(plot.layout.showlegend).toBe(true);
  });
  it("keeps the original single-cohort meaning", () => {
    const plot = buildRegressionComparisonPlot([rows[1]]);
    expect(plot.data[0].name).toBe("Concentration");
    expect(JSON.stringify(plot.layout.title)).toContain("held out test");
    expect(plot.data[0].text).toEqual(["test-b"]);
  });
});
