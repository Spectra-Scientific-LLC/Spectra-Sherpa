import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import PlotsPanel from "@/views/workflow-builder/node-detail/panels/PlotsPanel.vue";

function emptyState(overrides: Record<string, unknown> = {}) {
  return {
    hasOutput: true,
    availablePlots: [{ key: "demo" }],
    nodeTypeKey: "",
    isPCAOutput: false,
    isPreprocessingNode: false,
    isDataNode: false,
    isSpectraData: false,
    isGenericDataNode: false,
    nodeOutput: null,
    contourClickPoint: null,
    pcaAxisOptions: [],
    regressionTargetOptions: [],
    spectraDisplayOptions: [],
    genericDisplayOptions: [],
    featureOptions: [],
    holdoutVisualization: null,
    pcaScoresData: [], pcaScoresLayout: {}, pcaScoresConfig: {},
    pcaBiplotData: [], pcaBiplotLayout: {},
    pcaLoadingsData: [], pcaLoadingsLayout: {}, pcaLoadingsConfig: {},
    pcaScreeData: [], pcaScreeLayout: {},
    pcaDiagnosticsData: [], pcaDiagnosticsLayout: {},
    mcrConcentrationData: [], mcrConcentrationLayout: {},
    mcrSpectraData: [], mcrSpectraLayout: {},
    efaEigenvalueData: [], efaEigenvalueLayout: {},
    plsScoresData: [], plsScoresLayout: {},
    plsLoadingsData: [], plsLoadingsLayout: {},
    classificationScoresData: [], classificationScoresLayout: {},
    plsdaLoadingsData: [], plsdaLoadingsLayout: {},
    plsdaVipData: [], plsdaVipLayout: {},
    plsdaConfusionTrainData: [], plsdaConfusionTrainLayout: {},
    plsdaConfusionCVData: [], plsdaConfusionCVLayout: {},
    classificationAccuracyData: [], classificationAccuracyLayout: {},
    regressionCorrelationData: [], regressionCorrelationLayout: {},
    hcaDendrogramData: [], hcaDendrogramLayout: {},
    peakFindingPlotData: [], peakFindingPlotLayout: {},
    plotNodeData: [], plotNodeLayout: {},
    spectraOverlayData: [], spectraOverlayLayout: {},
    spectraContourData: [], spectraContourLayout: {},
    horizontalSliceData: [], horizontalSliceLayout: {},
    verticalSliceData: [], verticalSliceLayout: {},
    genericBoxPlotData: [], genericBoxPlotLayout: {},
    genericScatterData: [], genericScatterLayout: {},
    clusterScatterData: [], clusterScatterLayout: {},
    outlierChartData: [], outlierChartLayout: {},
    holdoutConfusionData: [], holdoutConfusionLayout: {},
    holdoutRegressionData: [], holdoutRegressionLayout: {},
    statsPlotData: [], statsPlotLayout: {},
    ...overrides,
  };
}

function factory(props: Partial<InstanceType<typeof PlotsPanel>["$props"]> = {}) {
  return mount(PlotsPanel, {
    props: {
      expanded: true,
      plotSections: {},
      pcaXAxis: 0,
      pcaYAxis: 1,
      plsdaLoadingsViewMode: "lines",
      regressionTargetIdx: 0,
      spectraDisplayMode: "overlay",
      genericDisplayMode: "boxplot",
      featureXAxis: 0,
      featureYAxis: 1,
      state: emptyState(),
      ...props,
    },
    global: { stubs: { Transition: false, PlotlyChart: true, Dropdown: true, Button: true } },
  });
}

describe("PlotsPanel", () => {
  it("does not render when hasOutput is false", () => {
    const w = factory({ state: emptyState({ hasOutput: false }) });
    expect(w.find(".detail-section").exists()).toBe(false);
  });

  it("does not render when availablePlots is empty", () => {
    const w = factory({ state: emptyState({ availablePlots: [] }) });
    expect(w.find(".detail-section").exists()).toBe(false);
  });

  it("renders the PCA subsections when isPCAOutput is true", () => {
    const w = factory({
      state: emptyState({ isPCAOutput: true }),
      plotSections: { pcaScores: false, pcaBiplot: false, pcaLoadings: false, pcaScree: false, pcaDiagnostics: false },
    });
    expect(w.text()).toContain("Scores Plot");
    expect(w.text()).toContain("Biplot");
    expect(w.text()).toContain("Loadings Plot");
    expect(w.text()).toContain("Scree Plot");
    expect(w.text()).toContain("Diagnostics Plot");
  });

  it("emits togglePlot with the correct key when a plot header is clicked", async () => {
    const w = factory({
      state: emptyState({ isPCAOutput: true }),
      plotSections: { pcaScores: false },
    });
    const headers = w.findAll(".plot-subsection-header");
    expect(headers.length).toBeGreaterThan(0);
    await headers[0].trigger("click");
    const events = w.emitted("togglePlot");
    expect(events?.[0]?.[0]).toBe("pcaScores");
  });

  it("emits toggle when the section header is clicked", async () => {
    const w = factory();
    await w.find(".section-header").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();
  });

  it("renders PLS-DA loadings view-mode buttons", () => {
    const w = factory({
      state: emptyState({ nodeTypeKey: "classification.plsda" }),
      plotSections: { plsdaLoadings: true },
    });
    expect(w.html()).toContain('label="Line Plot"');
    expect(w.html()).toContain('label="Biplot"');
  });

  it("renders the regression target dropdown only when regressionTargetOptions.length > 1", () => {
    const w = factory({
      state: emptyState({
        nodeTypeKey: "model.pls",
        regressionCorrelationData: [{ foo: 1 }],
        regressionTargetOptions: [
          { label: "target 0", value: 0 },
          { label: "target 1", value: 1 },
        ],
      }),
      plotSections: { regressionCorrelation: true },
    });
    // One dropdown from the regression target picker (two if PLS scores were expanded, but plsScores: false here)
    expect(w.findAllComponents({ name: "Dropdown" }).length).toBeGreaterThan(0);
  });

  it("renders slice hint when no contour point has been clicked", () => {
    const w = factory({
      state: emptyState({
        isDataNode: true,
        isSpectraData: true,
        contourClickPoint: null,
      }),
      plotSections: { spectraOverview: true },
      spectraDisplayMode: "contour",
    });
    expect(w.text()).toContain("Click on the contour plot");
    expect(w.find(".slice-plots").exists()).toBe(false);
  });

  it("renders slice plots when contourClickPoint is set", () => {
    const w = factory({
      state: emptyState({
        isDataNode: true,
        isSpectraData: true,
        contourClickPoint: { sampleIdx: 4, wavenumber: 1234.56 },
        nodeOutput: { metadata: { x_units: "cm⁻¹" } },
      }),
      plotSections: { spectraOverview: true },
      spectraDisplayMode: "contour",
    });
    expect(w.find(".slice-plots").exists()).toBe(true);
    expect(w.text()).toContain("Spectrum at Sample 5");
    expect(w.text()).toContain("Time Profile at 1234.6");
  });
});
