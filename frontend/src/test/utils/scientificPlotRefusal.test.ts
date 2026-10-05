import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import * as plots from "@/utils/scientificPlots";
import { scientificPlotRefusal } from "@/utils/scientificPlotState";
import PlotlyChart from "@/components/PlotlyChart.vue";
vi.mock("plotly.js-cartesian-dist-min", () => ({
  default: { react: vi.fn(), relayout: vi.fn(), purge: vi.fn(), Plots: { resize: vi.fn() } },
}));
const cases: Array<[string, () => plots.ScientificPlot, RegExp]> = [
  [
    "empty unsupervised concentrations",
    () => plots.buildComponentConcentrationHeatmap([]),
    /concentrations/i,
  ],
  [
    "supervised missing values",
    () => plots.buildPredictedVsActualPlot({ actual: [1], predicted: [null] }),
    /matching finite/,
  ],
  [
    "invalid target selection",
    () => plots.buildPredictedVsActualPlot({ actual: [1], predicted: [1], targetIndex: -1 }),
    /target column/,
  ],
  [
    "held-out comparison missing rows",
    () => plots.buildRegressionComparisonPlot([]),
    /sample, target, role/,
  ],
  [
    "ragged non-spectral matrix",
    () =>
      plots.buildScientificMatrixPlot({
        value: [[1], [2, 3]],
        seriesBy: "rows",
        xTitle: "Feature",
        yTitle: "Value",
        seriesPrefix: "Row",
      }),
    /rectangular/,
  ],
  ["nonfinite VIP", () => plots.buildVipPlot({ scores: [Infinity] }), /VIP/],
  [
    "missing class responses",
    () => plots.buildClassificationResponsesPlot([[null]]),
    /Classification responses/,
  ],
  ["empty ranked VIP", () => plots.buildRankedVipPlot({ scores: [] }), /Ranked VIP/],
  [
    "mismatched variance",
    () => plots.buildExplainedVariancePlot({ xVariance: [1], yVariance: [] }),
    /matching/,
  ],
  ["missing component variance", () => plots.buildComponentExplainedVariancePlot([]), /nonempty/],
  [
    "nonfinite component variance",
    () => plots.buildComponentExplainedVariancePlot([NaN]),
    /finite/,
  ],
  ["missing diagnostics", () => plots.buildT2QDiagnosticsPlot({}), /T²\/Q/],
  ["missing category", () => plots.buildCategoryCountsPlot([null]), /nonmissing/],
  ["nonfinite category", () => plots.buildCategoryCountsPlot([Infinity]), /finite/],
  ["non-square confusion", () => plots.buildConfusionMatrixPlot([[1, 2]]), /square/],
  ["empty peaks", () => plots.buildPeakTablePlot([]), /Peak/],
  ["missing salient features", () => plots.buildSalientFeaturesPlot({}), /feature list/],
  [
    "nonfinite salient features",
    () => plots.buildSalientFeaturesPlot({ features: [{ position: NaN, importance: 1 }] }),
    /invalid|finite/,
  ],
  ["missing retained OOF receipt", () => plots.buildOutOfFoldEvidencePlot(null), /evidence record/],
  ["missing declared record", () => plots.buildDeclaredVisualizationPlot(null), /record/],
  [
    "missing selected declared plot",
    () => plots.buildDeclaredVisualizationPlot({}, "missing"),
    /selected/,
  ],
  ["missing declared trace array", () => plots.buildDeclaredVisualizationPlot({}), /trace array/],
  [
    "empty declared traces after reopen",
    () => plots.buildDeclaredVisualizationPlot(JSON.parse('{"data":[]}')),
    /no retained traces/,
  ],
];
describe("F3 builder → shared renderer refusal chain", () => {
  it.each(cases)("%s", async (_name, build, reason) => {
    const plot = build();
    expect(plot.data).toEqual([]);
    expect(scientificPlotRefusal(plot.layout)).toMatch(reason);
    const wrapper = mount(PlotlyChart, { props: { ...plot, emptyMessage: "No data yet." } });
    await flushPromises();
    expect(wrapper.text()).toContain(scientificPlotRefusal(plot.layout));
    expect(wrapper.text()).not.toContain("No data yet.");
    wrapper.unmount();
  });
  it("keeps valid singleton and generic -1 categories", () => {
    expect(
      plots.buildPredictedVsActualPlot({ actual: [1], predicted: [1] }).data.length,
    ).toBeGreaterThan(0);
    const categorical = plots.buildCategoryCountsPlot([-1, -1]);
    expect(categorical.data[0].y).toEqual([2]);
    expect(scientificPlotRefusal(categorical.layout)).toBeNull();
  });
  it("preserves a producer's refusal through declared visualization reopen", () => {
    const plot = plots.buildDeclaredVisualizationPlot({
      data: [],
      layout: { meta: { refusal_reason: "Retained output limit exceeded." } },
    });
    expect(scientificPlotRefusal(plot.layout)).toBe("Retained output limit exceeded.");
  });
});
