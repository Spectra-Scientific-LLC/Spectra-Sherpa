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
      "Concentration · calibration fit", "Concentration · test set",
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
    expect(JSON.stringify(plot.layout.title)).toContain("test set");
    expect(plot.data[0].text).toEqual(["test-b"]);
  });
  it("colours calibration fits apart from validation predictions", () => {
    const plot = buildRegressionComparisonPlot(rows);
    const colors = Object.fromEntries(plot.data.filter((trace) => trace.mode === "markers")
      .map((trace) => [String(trace.name), (trace.marker as { color: string }).color]));
    expect(colors["Concentration · calibration fit"]).not.toBe(colors["Concentration · test set"]);
  });
  it("retains producer statistics without printing a metric panel over the graph", () => {
    const value = {
      schema_version: "spectrasherpa-regression-comparison/1",
      data: [rows[1]],
      metadata: { role: "held_out_test" },
      statistics: { targets: [{ target: "Concentration", metrics: { rmse: 0.3974920466885316, r2: 0.9991506638934449, bias: -0.1411081585168226, slope: 0.9897439737800676, n_samples: 10 } }] },
    };
    const plot = buildRegressionComparisonPlot(value);
    expect(plot.layout.annotations).toBeUndefined();
    expect(plot.layout.meta.producer_statistics).toEqual(value.statistics);
    const calibration = { ...value, data: [rows[0]], metadata: { role: "calibration" } };
    expect(buildRegressionComparisonPlot(calibration).layout.meta.producer_statistics).toEqual(value.statistics);
    // Rows alone carry no producer statistics: nothing is recomputed.
    expect(buildRegressionComparisonPlot([rows[1]]).layout.meta).toBeUndefined();
  });
});
