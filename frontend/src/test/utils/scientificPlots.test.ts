import { describe, expect, it } from "vitest";
import canonicalOof from "../fixtures/oof-scientific-surface.json";
import {
  buildCategoryCountsPlot,
  buildClassificationResponsesPlot,
  buildComponentConcentrationHeatmap,
  buildComponentExplainedVariancePlot,
  buildConfusionMatrixPlot,
  buildDeclaredVisualizationPlot,
  buildExplainedVariancePlot,
  buildOutOfFoldEvidencePlot,
  buildPeakTablePlot,
  buildPredictedVsActualPlot,
  buildRankedVipPlot,
  buildRegressionComparisonPlot,
  buildSalientFeaturesPlot,
  buildT2QDiagnosticsPlot,
  buildVipPlot,
  exactScientificFeatureLabels,
  scientificPortMetadata,
  t2QDiagnosticRows,
} from "@/utils/scientificPlots";

describe("standard scientific plot builders", () => {
  it("shares exact feature labels and component heatmaps across plot surfaces", () => {
    const metadata = scientificPortMetadata({
      metadata: { diagnostics: { feature_names: ["1650 cm-1", "1600 cm-1"] } },
    });
    expect(exactScientificFeatureLabels(metadata, 2)).toEqual(["1650 cm-1", "1600 cm-1"]);
    expect(exactScientificFeatureLabels(metadata, 3)).toBeNull();

    const heatmap = buildComponentConcentrationHeatmap({
      data: [[0.8, 0.2], [0.3, 0.7]],
      metadata: {
        feature_names: ["Linalool", "Linalyl acetate"],
        sample_labels: ["Lavender 01", "Lavender 02"],
        value_units: "Relative concentration",
      },
    });
    expect(heatmap.data[0]).toMatchObject({
      type: "heatmap",
      x: ["Linalool", "Linalyl acetate"],
      y: ["Lavender 01", "Lavender 02"],
      z: [[0.8, 0.2], [0.3, 0.7]],
    });
  });

  it("uses one predicted-versus-actual grammar for any regression node", () => {
    const fittedPls = buildPredictedVsActualPlot({
      actual: [[1], [2]],
      predicted: [[0.9], [2.1]],
      targetName: "Moisture",
    });
    const evaluator = buildPredictedVsActualPlot({
      actual: [[1], [2]],
      predicted: [[0.9], [2.1]],
      targetName: "Moisture",
    });
    expect(fittedPls).toEqual(evaluator);
    expect(fittedPls.data[0]).toMatchObject({ x: [1, 2], y: [0.9, 2.1] });
  });

  it("preserves scientific values in VIP and explained-variance projections", () => {
    const vip = buildVipPlot({ scores: [0.7, 1.3], featureLabels: ["a", "b"] });
    const variance = buildExplainedVariancePlot({
      xVariance: [0.5, 0.25],
      yVariance: [0.75, 0.1],
    });
    expect(vip.data[0]).toMatchObject({ x: ["a", "b"], y: [0.7, 1.3] });
    expect(vip.layout.margin).toMatchObject({ b: 150 });
    expect(vip.layout.xaxis).toMatchObject({
      automargin: true,
      tickangle: -45,
      title: { text: "Feature", standoff: 24 },
    });
    expect(variance.data).toEqual([
      expect.objectContaining({ name: "X", y: [50, 25] }),
      expect.objectContaining({ name: "Y", y: [75, 10] }),
    ]);
    expect(variance.layout.title).toMatchObject({ x: 0.02, xanchor: "left" });
    expect(variance.layout.margin).toMatchObject({ t: 58 });
  });

  it("keeps the selected response visible in held-out regression evidence", () => {
    const plot = buildRegressionComparisonPlot({
      data: [
        {
          sample: "sample-1",
          target: "Carbon dioxide",
          reference: 10,
          predicted: 9.8,
          residual: 0.2,
          role: "held_out_test",
        },
      ],
    });

    expect(plot.layout.title).toMatchObject({
      text: "Predicted vs Reference — Carbon dioxide · held out test",
      x: 0.02,
      xanchor: "left",
    });
    expect(plot.layout.xaxis).toMatchObject({
      title: "Reference — Carbon dioxide",
      constrain: "domain",
    });
    expect(plot.layout.xaxis.range[0]).toBeCloseTo(9.79);
    expect(plot.layout.xaxis.range[1]).toBeCloseTo(10.01);
    expect(plot.layout.yaxis).toMatchObject({
      title: "Predicted — Carbon dioxide",
      scaleanchor: "x",
      scaleratio: 1,
      constrain: "domain",
    });
    expect(plot.layout.yaxis.range).toEqual(plot.layout.xaxis.range);
  });

  it("renders a complete dense VIP profile on its scientific feature axis", () => {
    const scores = Array.from({ length: 5401 }, (_, index) => 0.5 + index / 5401);
    const wavenumbers = Array.from({ length: 5401 }, (_, index) => 4000 - index * 0.5);
    const plot = buildVipPlot({
      scores,
      featureLabels: wavenumbers,
      xTitle: "Wavenumber (cm-1)",
      reverseX: true,
    });

    expect(plot.data[0]).toMatchObject({
      type: "scatter",
      mode: "lines",
      x: wavenumbers,
      y: scores,
    });
    expect(plot.layout.xaxis).toMatchObject({
      title: "Wavenumber (cm-1)",
      autorange: "reversed",
    });
  });

  it("keeps the PCA scree title, axes, and legend in separate layout regions", () => {
    const plot = buildComponentExplainedVariancePlot([[0.7], [0.2], [0.1]]);

    expect(plot.layout.title).toMatchObject({ x: 0.02, xanchor: "left" });
    expect(plot.layout.margin).toMatchObject({ t: 58, b: 124 });
    expect(plot.layout.xaxis.title).toMatchObject({
      text: "Principal component",
      standoff: 12,
    });
    expect(plot.layout.legend).toMatchObject({ orientation: "h", y: -0.46, yanchor: "top" });
  });

  it("retains the pre-existing ranked top-feature VIP computation as a distinct profile", () => {
    const ranked = buildRankedVipPlot({
      scores: [0.7, 1.8, 1.2, 0.5],
      featureLabels: ["a", "b", "c", "d"],
      maxFeatures: 3,
    });
    expect(ranked.data[0]).toMatchObject({
      x: ["b", "c", "a"],
      y: [1.8, 1.2, 0.7],
    });
    expect(ranked.layout.shapes[0]).toMatchObject({ y0: 1, y1: 1 });
  });

  it("fails closed on malformed or mismatched evidence", () => {
    expect(buildPredictedVsActualPlot({ actual: [[1]], predicted: [[1], [2]] }).data).toEqual([]);
    expect(buildVipPlot({ scores: [1, Number.NaN] }).data).toEqual([]);
    expect(buildRankedVipPlot({ scores: [1, Number.NaN] }).data).toEqual([]);
    expect(buildExplainedVariancePlot({ xVariance: [0.5], yVariance: [0.5, 0.1] }).data).toEqual([]);
  });

  it("renders only the closed PeakTable and SalientFeatures schemas", () => {
    const peaks = buildPeakTablePlot({
      data: [{ median_pos: 1045.2, median_height: 0.42, detection_fraction: 0.8 }],
    });
    const salient = buildSalientFeaturesPlot({
      method: "peak_finding",
      features: [{ position: 1045.2, importance: 0.8, label: "consensus peak" }],
    });
    expect(peaks.data[0]).toMatchObject({ x: [1045.2], y: [0.42] });
    expect(salient.data[0]).toMatchObject({ x: [1045.2], y: [0.8] });
    expect(buildPeakTablePlot({ data: [{ position: 1045.2, height: 0.42 }] }).data).toEqual([]);
    expect(buildSalientFeaturesPlot([{ position: 1045.2, importance: 0.8 }]).data).toEqual([]);
  });

  it("renders categorical, confusion, out-of-fold, and declared visualization contracts", () => {
    expect(buildCategoryCountsPlot(["A", "B", "A"]).data[0]).toMatchObject({
      x: ["A", "B"],
      y: [2, 1],
    });
    expect(buildConfusionMatrixPlot([[3, 1], [0, 2]]).data[0]).toMatchObject({
      z: [[0.75, 0.25], [0, 1]],
    });
    expect(buildOutOfFoldEvidencePlot(canonicalOof).data[0]).toMatchObject({
      x: canonicalOof.observations,
      y: canonicalOof.predictions,
    });
    const declared = buildDeclaredVisualizationPlot({
        data: [{ type: "scatter", x: [1], y: [2] }],
        layout: {
          title: "Declared",
          xaxis: { title: "Component" },
          legend: { orientation: "h" },
        },
      });
    expect(declared.data).toEqual([{ type: "scatter", x: [1], y: [2] }]);
    expect(declared.layout).toMatchObject({
      title: { text: "Declared", x: 0.02, xanchor: "left" },
      margin: { t: 58, b: 124 },
      xaxis: { title: { text: "Component", standoff: 12 } },
      legend: { orientation: "h", y: -0.46, yanchor: "top" },
    });
  });

  it("renders evaluator confusion labels and PLS-DA response semantics", () => {
    const confusion = buildConfusionMatrixPlot({
      type: "confusion_matrix",
      data: [[3, 1], [0, 2]],
      metadata: { labels: ["control", "treated"] },
    });
    expect(confusion.data[0]).toMatchObject({
      x: ["control", "treated"],
      y: ["control", "treated"],
      z: [[0.75, 0.25], [0, 1]],
    });
    expect(confusion.layout.margin).toMatchObject({ l: 90, b: 78 });

    const botanical = buildConfusionMatrixPlot({
      type: "confusion_matrix",
      data: [[5, 0, 0], [0, 0, 2], [1, 0, 0]],
      metadata: {
        labels: [
          "Lavandula angustifolia",
          "Lavandula latifolia",
          "Lavandula x intermedia",
        ],
      },
    });
    expect(botanical.data[0]).toMatchObject({
      x: [
        "Lavandula angustifolia",
        "Lavandula latifolia",
        "Lavandula x intermedia",
      ],
      y: [
        "Lavandula angustifolia",
        "Lavandula latifolia",
        "Lavandula x intermedia",
      ],
    });
    expect(botanical.layout.xaxis).toMatchObject({
      tickvals: [
        "Lavandula angustifolia",
        "Lavandula latifolia",
        "Lavandula x intermedia",
      ],
      ticktext: [
        "Lavandula<br>angustifolia",
        "Lavandula<br>latifolia",
        "Lavandula x<br>intermedia",
      ],
      tickangle: 0,
      automargin: true,
    });
    expect(botanical.layout.yaxis.ticktext).toEqual([
      "Lavandula<br>angustifolia",
      "Lavandula<br>latifolia",
      "Lavandula x<br>intermedia",
    ]);

    const responses = buildClassificationResponsesPlot(
      [[0.9, 0.1], [0.2, 0.8]],
      {
        label_categories: ["control", "treated"],
        sample_labels: ["S1", "S2"],
        sample_classes: ["control", "treated"],
      },
    );
    expect(responses.data[0]).toMatchObject({
      x: ["control", "treated"],
      y: [1, 2],
      z: [[0.9, 0.1], [0.2, 0.8]],
      customdata: [
        [["S1", "control"], ["S1", "control"]],
        [["S2", "treated"], ["S2", "treated"]],
      ],
    });
    expect(responses.layout.yaxis.title).toBe("Calibration sample index");
    expect(responses.layout.title.text).toContain("not probabilities");
  });
});

describe("persisted T2/Q diagnostic labels", () => {
  const value = {
    T2: [1, 2, 3, 4],
    Q: [0.1, 0.2, 0.3, 0.4],
    flags: [false, true, false, true],
  };
  const metadata = {
    diagnostics: {
      sample_labels: {
        _truncated_sequence: true,
        length: 4,
        preview: ["sample-a", "sample-b"],
        last: "sample-d",
      },
      t2_limit: 1.5,
      q_limit: 0.15,
      confidence_level: 0.95,
      n_outliers: 2,
    },
  };

  it("retains available identities from a compacted label preview", () => {
    expect(t2QDiagnosticRows(value, metadata).map((row) => row.sample)).toEqual([
      "sample-a",
      "sample-b",
      "Sample 3",
      "sample-d",
    ]);
  });

  it("uses the same persisted identities in plot hover labels", () => {
    const plot = buildT2QDiagnosticsPlot(value, metadata);

    expect(plot.data[0].text).toEqual(["sample-a", "Sample 3"]);
    expect(plot.data[1].text).toEqual(["sample-b", "sample-d"]);
  });
});
