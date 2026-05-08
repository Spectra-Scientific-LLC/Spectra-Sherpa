import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import { ref, computed } from "vue";
import PlotsPanel from "@/views/workflow-builder/node-detail/panels/PlotsPanel.vue";
import {
  NODE_DETAIL_STATE_KEY,
  type NodeDetailState,
  type PlotDataBag,
} from "@/views/workflow-builder/node-detail/state/useNodeDetailState";

/* eslint-disable @typescript-eslint/no-explicit-any */

function emptyPlots(overrides: Partial<PlotDataBag> = {}): PlotDataBag {
  const base: PlotDataBag = {
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
  };
  const zeroes = [
    "pcaScoresData", "pcaScoresLayout", "pcaScoresConfig",
    "pcaBiplotData", "pcaBiplotLayout",
    "pcaLoadingsData", "pcaLoadingsLayout", "pcaLoadingsConfig",
    "pcaScreeData", "pcaScreeLayout",
    "pcaDiagnosticsData", "pcaDiagnosticsLayout",
    "mcrConcentrationData", "mcrConcentrationLayout",
    "mcrSpectraData", "mcrSpectraLayout",
    "efaEigenvalueData", "efaEigenvalueLayout",
    "plsScoresData", "plsScoresLayout",
    "plsLoadingsData", "plsLoadingsLayout",
    "classificationScoresData", "classificationScoresLayout",
    "plsdaLoadingsData", "plsdaLoadingsLayout",
    "plsdaVipData", "plsdaVipLayout",
    "plsdaConfusionTrainData", "plsdaConfusionTrainLayout",
    "plsdaConfusionCVData", "plsdaConfusionCVLayout",
    "classificationAccuracyData", "classificationAccuracyLayout",
    "regressionCorrelationData", "regressionCorrelationLayout",
    "hcaDendrogramData", "hcaDendrogramLayout",
    "peakFindingPlotData", "peakFindingPlotLayout",
    "plotNodeData", "plotNodeLayout",
    "spectraOverlayData", "spectraOverlayLayout",
    "spectraContourData", "spectraContourLayout",
    "horizontalSliceData", "horizontalSliceLayout",
    "verticalSliceData", "verticalSliceLayout",
    "genericBoxPlotData", "genericBoxPlotLayout",
    "genericScatterData", "genericScatterLayout",
    "clusterScatterData", "clusterScatterLayout",
    "outlierChartData", "outlierChartLayout",
    "holdoutConfusionData", "holdoutConfusionLayout",
    "holdoutRegressionData", "holdoutRegressionLayout",
    "statsPlotData", "statsPlotLayout",
  ];
  for (const k of zeroes) base[k] = k.endsWith("Data") ? [] : {};
  return { ...base, ...overrides };
}

function makeState(
  plotsOverrides: Partial<PlotDataBag> = {},
  plotSectionsOverrides: Record<string, boolean> = {},
): NodeDetailState {
  return {
    output: {
      summary: ref(""), hasOutput: ref(false), data: ref(null),
      metadata: ref({}), subsections: ref({
        coordinates: false, metadata: false, processing: false,
        provenance: false, quality: false, ports: false,
      }),
      datasetInfo: ref(null), datasetLabelTable: ref({ headers: [], rows: [] }),
      labelPreviewLimit: 10, processingHistory: ref(null), provenance: ref(null),
      quality: ref(null), portSummaries: ref([]),
      preview: computed(() => ({ rows: [], columns: [], summary: "" })),
      pcaDiagnostics: computed(() => ({ rows: [], columns: [], summary: "" })),
      isRegressionNode: ref(false), regressionTargetOptions: ref([]),
      selectedRegressionR2: ref(null), selectedRegressionRmse: ref(null),
      getMetaTooltip: () => "", formatMetaValue: (v: unknown) => String(v),
    },
    plots: ref(emptyPlots(plotsOverrides)),
    writable: {
      pcaXAxis: ref(0),
      pcaYAxis: ref(1),
      plsdaLoadingsViewMode: ref("lines"),
      regressionTargetIdx: ref(0),
      spectraDisplayMode: ref(
        (plotsOverrides as any).spectraDisplayMode ?? "overlay",
      ),
      genericDisplayMode: ref("boxplot"),
      featureXAxis: ref(0),
      featureYAxis: ref(1),
      contourClickPoint: ref(null),
    },
    plotSections: ref(plotSectionsOverrides),
  };
}

function factory(
  plotsOverrides: Partial<PlotDataBag> = {},
  plotSections: Record<string, boolean> = {},
  expanded = true,
  writableOverrides: Partial<NodeDetailState["writable"]> = {},
) {
  const state = makeState(plotsOverrides, plotSections);
  Object.assign(state.writable, writableOverrides);
  return {
    wrapper: mount(PlotsPanel, {
      props: { expanded },
      global: {
        provide: { [NODE_DETAIL_STATE_KEY as symbol]: state },
        stubs: { Transition: false, PlotlyChart: true, Dropdown: true, Button: true },
      },
    }),
    state,
  };
}

describe("PlotsPanel", () => {
  it("renders an empty state when hasOutput is false", () => {
    const { wrapper } = factory({ hasOutput: false });
    expect(wrapper.find(".detail-section").exists()).toBe(true);
    expect(wrapper.text()).toContain("Run the node to generate visualizations.");
  });

  it("renders an empty state when availablePlots is empty", () => {
    const { wrapper } = factory({ availablePlots: [] });
    expect(wrapper.find(".detail-section").exists()).toBe(true);
    expect(wrapper.text()).toContain("No visualizations available for this node type.");
  });

  it("renders the PCA subsections when isPCAOutput is true", () => {
    const { wrapper } = factory(
      { isPCAOutput: true },
      { pcaScores: false, pcaBiplot: false, pcaLoadings: false, pcaScree: false, pcaDiagnostics: false },
    );
    expect(wrapper.text()).toContain("Scores Plot");
    expect(wrapper.text()).toContain("Biplot");
    expect(wrapper.text()).toContain("Loadings Plot");
    expect(wrapper.text()).toContain("Scree Plot");
    expect(wrapper.text()).toContain("Diagnostics Plot");
  });

  it("emits togglePlot with the correct key when a plot header is clicked", async () => {
    const { wrapper } = factory({ isPCAOutput: true }, { pcaScores: false });
    const headers = wrapper.findAll(".plot-subsection-header");
    expect(headers.length).toBeGreaterThan(0);
    await headers[0].trigger("click");
    const events = wrapper.emitted("togglePlot");
    expect(events?.[0]?.[0]).toBe("pcaScores");
  });

  it("emits toggle when the section header is clicked", async () => {
    const { wrapper } = factory();
    await wrapper.find(".section-header").trigger("click");
    expect(wrapper.emitted("toggle")).toBeTruthy();
  });

  it("renders PLS-DA loadings view-mode buttons", () => {
    const { wrapper } = factory({ nodeTypeKey: "classification.plsda" }, { plsdaLoadings: true });
    expect(wrapper.html()).toContain('label="Line Plot"');
    expect(wrapper.html()).toContain('label="Biplot"');
  });

  it("renders the regression target dropdown only when regressionTargetOptions.length > 1", () => {
    const { wrapper } = factory(
      {
        nodeTypeKey: "model.pls",
        regressionCorrelationData: [{ foo: 1 }],
        regressionTargetOptions: [
          { label: "target 0", value: 0 },
          { label: "target 1", value: 1 },
        ],
      },
      { regressionCorrelation: true },
    );
    expect(wrapper.findAllComponents({ name: "Dropdown" }).length).toBeGreaterThan(0);
  });

  it("renders slice hint when no contour point has been clicked", () => {
    const { wrapper } = factory(
      {
        isDataNode: true,
        isSpectraData: true,
        contourClickPoint: null,
        spectraDisplayMode: "contour",
      } as any,
      { spectraOverview: true },
    );
    expect(wrapper.text()).toContain("Click on the contour plot");
    expect(wrapper.find(".slice-plots").exists()).toBe(false);
  });

  it("renders slice plots when contourClickPoint is set", () => {
    const { wrapper } = factory(
      {
        isDataNode: true,
        isSpectraData: true,
        contourClickPoint: { sampleIdx: 4, wavenumber: 1234.56 },
        nodeOutput: { metadata: { x_units: "cm⁻¹" } },
        spectraDisplayMode: "contour",
      } as any,
      { spectraOverview: true },
    );
    expect(wrapper.find(".slice-plots").exists()).toBe(true);
    expect(wrapper.text()).toContain("Spectrum at Sample 5");
    expect(wrapper.text()).toContain("Time Profile at 1234.6");
  });
});
