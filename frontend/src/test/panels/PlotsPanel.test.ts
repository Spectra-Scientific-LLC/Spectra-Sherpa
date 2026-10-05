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
    isRegressionComparison: false,
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
    metadataGroupingError: "",
    sampleColorFieldOptions: [],
    sampleSymbolFieldOptions: [],
    featureScaleOptions: [],
    featureLabelSetOptions: [],
    featureTitleSetOptions: [],
    sampleLabelSetOptions: [],
    axisSetError: "",
    scoreColorOptions: [],
    spectraOverlayNotice: "",
    peakFindingPlotLabel: "Spectra with Peaks",
  };
  const zeroes = [
    "pcaScoresData",
    "pcaScoresLayout",
    "pcaScoresConfig",
    "pcaBiplotData",
    "pcaBiplotLayout",
    "pcaLoadingsData",
    "pcaLoadingsLayout",
    "pcaLoadingsConfig",
    "pcaScreeData",
    "pcaScreeLayout",
    "pcaDiagnosticsData",
    "pcaDiagnosticsLayout",
    "mcrConcentrationData",
    "mcrConcentrationLayout",
    "mcrConcentrationHeatmapData",
    "mcrConcentrationHeatmapLayout",
    "mcrSpectraData",
    "mcrSpectraLayout",
    "efaEigenvalueData",
    "efaEigenvalueLayout",
    "classificationScoresData",
    "classificationScoresLayout",
    "plsdaLoadingsData",
    "plsdaLoadingsLayout",
    "plsdaVipData",
    "plsdaVipLayout",
    "plsdaConfusionTrainData",
    "plsdaConfusionTrainLayout",
    "plsdaConfusionCVData",
    "plsdaConfusionCVLayout",
    "classificationAccuracyData",
    "classificationAccuracyLayout",
    "regressionCorrelationData",
    "regressionCorrelationLayout",
    "plsVipData",
    "plsVipLayout",
    "plsExplainedVarianceData",
    "plsExplainedVarianceLayout",
    "hcaDendrogramData",
    "hcaDendrogramLayout",
    "peakFindingPlotData",
    "peakFindingPlotLayout",
    "plotNodeData",
    "plotNodeLayout",
    "spectraOverlayData",
    "spectraOverlayLayout",
    "spectraContourData",
    "spectraContourLayout",
    "horizontalSliceData",
    "horizontalSliceLayout",
    "verticalSliceData",
    "verticalSliceLayout",
    "genericBoxPlotData",
    "genericBoxPlotLayout",
    "genericScatterData",
    "genericScatterLayout",
    "clusterScatterData",
    "clusterScatterLayout",
    "outlierChartData",
    "outlierChartLayout",
    "holdoutConfusionData",
    "holdoutConfusionLayout",
    "holdoutRegressionData",
    "holdoutRegressionLayout",
    "statsPlotData",
    "statsPlotLayout",
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
      summary: ref(""),
      hasOutput: ref(false),
      data: ref(null),
      metadata: ref({}),
      subsections: ref({
        coordinates: false,
        metadata: false,
        processing: false,
        provenance: false,
        quality: false,
        ports: false,
      }),
      datasetInfo: ref(null),
      datasetLabelTable: ref({ headers: [], rows: [] }),
      labelPreviewLimit: 10,
      processingHistory: ref(null),
      provenance: ref(null),
      quality: ref(null),
      portSummaries: ref([]),
      preview: computed(() => ({ rows: [], columns: [], summary: "" })),
      pcaDiagnostics: computed(() => ({ rows: [], columns: [], summary: "" })),
      isRegressionComparison: ref(false),
      regressionTargetOptions: ref([]),
      selectedRegressionR2: ref(null),
      selectedRegressionRmse: ref(null),
      getMetaTooltip: () => "",
      formatMetaValue: (v: unknown) => String(v),
    },
    plots: ref(emptyPlots(plotsOverrides)),
    writable: {
      selectedPresentationId: ref(null),
      pcaXAxis: ref(0),
      pcaYAxis: ref(1),
      scoreColorMode: ref("samples"),
      sampleColorField: ref("specimen_id"),
      sampleSymbolField: ref("block"),
      selectedFeatureScale: ref("__primary__"),
      selectedFeatureLabels: ref("__primary__"),
      selectedFeatureTitle: ref("__primary__"),
      selectedSampleLabels: ref("__primary__"),
      plsdaLoadingsViewMode: ref("lines"),
      regressionTargetIdx: ref(0),
      spectraDisplayMode: ref((plotsOverrides as any).spectraDisplayMode ?? "overlay"),
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
        stubs: {
          Transition: false,
          PlotlyChart: true,
          Dropdown: {
            name: "Dropdown",
            props: ["modelValue", "options", "optionDisabled"],
            template: "<select />",
          },
          Button: true,
        },
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
      {
        pcaScores: false,
        pcaBiplot: false,
        pcaLoadings: false,
        pcaScree: false,
        pcaDiagnostics: false,
      },
    );
    expect(wrapper.text()).toContain("Scores Plot");
    expect(wrapper.text()).toContain("Biplot");
    expect(wrapper.text()).toContain("Loadings Plot");
    expect(wrapper.text()).toContain("Scree Plot");
    expect(wrapper.text()).toContain("Diagnostics Plot");
  });

  it("disables the selected opposite PCA axis in both presentation-only selectors", () => {
    const { wrapper } = factory(
      {
        isPCAOutput: true,
        pcaAxisOptions: [
          { label: "PC1 (70.0%)", value: 0 },
          { label: "PC2 (20.0%)", value: 1 },
          { label: "PC3 (8.0%)", value: 2 },
        ],
      },
      { pcaScores: true },
    );
    const selectors = wrapper
      .findAllComponents({ name: "Dropdown" })
      .filter((selector) => selector.props("optionDisabled") === "disabled");
    expect(selectors).toHaveLength(2);
    expect(selectors[0].props("options")[1].disabled).toBe(true);
    expect(selectors[1].props("options")[0].disabled).toBe(true);
    expect(selectors[0].props("options")[2].disabled).toBe(false);
  });

  it.each([
    [{ isPCAOutput: true }, { pcaScores: true }],
    [{ nodeTypeKey: "classification.plsda" }, { classificationScores: true }],
    [{ isDataNode: true, isSpectraData: true }, { spectraOverview: true }],
    [{ isGenericDataNode: true }, { dataOverview: true }],
  ])(
    "uses the same metadata-style control across sample-resolved node plots",
    (plotOverrides, sections) => {
      const { wrapper } = factory(
        {
          ...plotOverrides,
          sampleColorFieldOptions: [{ label: "Specimen", value: "specimen_id" }],
          sampleSymbolFieldOptions: [{ label: "Block", value: "block" }],
        } as Partial<PlotDataBag>,
        sections,
      );
      expect(wrapper.findComponent({ name: "SampleMetadataStyleControls" }).exists()).toBe(true);
      expect(wrapper.text()).toContain("Color by metadata");
    },
  );

  it("exposes one shared axis-set control panel for every node plot family", () => {
    const { wrapper } = factory({
      isPCAOutput: true,
      featureScaleOptions: [
        { label: "Wavenumber · cm-1", value: "__primary__" },
        { label: "Wavelength · nm", value: "scale:Wavelength" },
      ],
      featureLabelSetOptions: [
        { label: "Variables", value: "__primary__" },
        { label: "Channels", value: "labels:Channels" },
      ],
      sampleLabelSetOptions: [
        { label: "Sample IDs", value: "__primary__" },
        { label: "Display names", value: "labels:Display names" },
      ],
    });
    expect(wrapper.get("[aria-label='Dataset axis display controls']").text()).toContain(
      "Coordinate scale",
    );
    expect(wrapper.findAllComponents({ name: "AxisSetControls" })).toHaveLength(2);
  });

  it("shows malformed metadata refusal in the generic data view", () => {
    const { wrapper } = factory(
      {
        isGenericDataNode: true,
        metadataGroupingError: "Metadata grouping refused: row mismatch.",
      },
      { dataOverview: true },
    );
    expect(wrapper.find('[role="alert"]').text()).toContain("row mismatch");
  });

  it("hides metadata line-style controls when the spectral view is a contour", () => {
    const { wrapper } = factory(
      {
        isDataNode: true,
        isSpectraData: true,
        sampleColorFieldOptions: [{ label: "Specimen", value: "specimen_id" }],
        sampleSymbolFieldOptions: [{ label: "Block", value: "block" }],
      },
      { spectraOverview: true },
      true,
      { spectraDisplayMode: ref("contour") },
    );
    expect(wrapper.findComponent({ name: "SampleMetadataStyleControls" }).exists()).toBe(false);
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

  it.each(["diagnostics.regression_evaluator", "diagnostics.classification_evaluator"])(
    "renders the canonical evaluator result section for %s",
    (nodeTypeKey) => {
      const { wrapper } = factory(
        { nodeTypeKey, holdoutVisualization: { type: "predicted_vs_actual" } },
        { evaluationResults: false },
      );
      expect(wrapper.text()).toContain("Evaluation Results");
    },
  );

  it("renders the regression target dropdown only when regressionTargetOptions.length > 1", () => {
    const { wrapper } = factory(
      {
        nodeTypeKey: "model.fitted_pls",
        isRegressionComparison: true,
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

  it("renders canonical fitted PLS result plots", () => {
    const { wrapper } = factory(
      {
        nodeTypeKey: "model.fitted_pls",
        isRegressionComparison: true,
        regressionCorrelationData: [{ x: [1], y: [1] }],
        plsVipData: [{ x: [1], y: [1.1] }],
        plsExplainedVarianceData: [{ x: ["LV 1"], y: [80] }],
      },
      { regressionCorrelation: true, plsVip: true, plsExplainedVariance: true },
    );
    expect(wrapper.text()).toContain("Predicted vs Actual");
    expect(wrapper.text()).toContain("VIP Scores");
    expect(wrapper.text()).toContain("Explained Variance");
    expect(wrapper.findAllComponents({ name: "PlotlyChart" })).toHaveLength(3);
  });

  it.each(["model.mcr_als", "model.nmf", "model.ica"])(
    "shows the component-concentration profile and heatmap for %s",
    (nodeTypeKey) => {
      const { wrapper } = factory(
        {
          nodeTypeKey,
          mcrConcentrationData: [{ x: [1, 2], y: [0.8, 0.3] }],
          mcrConcentrationHeatmapData: [{ type: "heatmap", z: [[0.8], [0.3]] }],
        },
        { mcrConcentrations: true },
      );
      expect(wrapper.get('[aria-label="Concentration heatmap"]').text()).toContain(
        "Concentration heatmap",
      );
      expect(wrapper.findAllComponents({ name: "PlotlyChart" })).toHaveLength(2);
    },
  );

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
