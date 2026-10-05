import { describe, expect, it } from "vitest";
import { computed, nextTick, ref } from "vue";
import { useQuickPlotProjection, type QuickPlotSelection } from "@/composables/useScientificPlotProjection";
import { useNodePlotData } from "@/views/workflow-builder/node-detail/composables/useNodePlotData";
import type { NodeOutput } from "@/utils/nodeOutput";

function views(output: NodeOutput, type: string) {
  const nodeOutput = ref(output);
  const nodeType = ref(type);
  const quick = useQuickPlotProjection(nodeOutput, nodeType);
  const x = ref(0);
  const y = ref(1);
  const detail = useNodePlotData({
    nodeOutput, nodeType, nodeTypeKey: nodeType,
    hasOutput: computed(() => true),
    isPCAOutput: computed(() => type === "model.pca"),
    pcaXAxis: x, pcaYAxis: y,
    scoreColorMode: ref("auto"), sampleColorField: ref(""), sampleSymbolField: ref(""),
    selectedFeatureScale: ref("__primary__"), selectedFeatureLabels: ref("__primary__"),
    selectedFeatureTitle: ref("__primary__"), selectedSampleLabels: ref("__primary__"),
    plsdaLoadingsViewMode: ref("lines"), featureXAxis: ref(0), featureYAxis: ref(1),
    contourClickPoint: ref(null), regressionTargetOptions: ref([]),
  });
  return { quick, detail, x, y, nodeOutput };
}

const pca = (): NodeOutput => ({
  data: [[1, 2, 3], [2, 4, 1], [3, 1, 2]],
  metadata: {
    type: "PCA", isPCA: true, n_components: 3,
    pc_labels: ["PC1 (60%)", "PC2 (30%)", "PC3 (10%)"],
    explained_variance_ratio: [0.6, 0.3, 0.1],
    sample_labels: ["A", "B", "C"], t2: [1, 2, 3], spe: [0.1, 0.2, 0.3],
  },
  ports: { loadings: {
    data: [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1], [0.2, 0.3, 0.1]],
    value: { x_axis: { data: [600, 1000, 1400], title: "Wavenumber", units: "cm-1" } },
  } },
} as unknown as NodeOutput);

describe("Quick Plot and detailed plot parity", () => {
  it.each([
    ["pca_scores", "pcaScores"], ["pca_loadings", "pcaLoadings"],
    ["pca_explained_variance", "pcaScree"],
  ])("shares the selected scientific %s presentation", (kind, prefix) => {
    const data = kind === "pca_explained_variance" ? [0.6, 0.4] : [[0.6, 0.3], [0.4, 0.7]];
    const output = {
      data, presentation_value: data,
      metadata: { scientific_presentation: {
        schema_version: "spectrasherpa-node-presentation/1", contract_digest: "a".repeat(64),
        presentation_id: "result", label: "Result", kind, source_port: "result",
        source_ports: ["result"], modes: ["plot"], description: "",
      } },
    } as unknown as NodeOutput;
    const { quick, detail } = views(output, "model.pca");
    quick.selectedPlotKey.value = `scientific_${kind}`;
    const bag = detail.plotBag.value as unknown as Record<string, unknown>;
    expect(quick.plotData.value.length).toBeGreaterThan(0);
    expect(quick.plotData.value).toEqual(bag[`${prefix}Data`]);
    expect(quick.plotLayout.value).toEqual(bag[`${prefix}Layout`]);
  });

  it("uses the caller's live component and grouping selections", async () => {
    const selection: QuickPlotSelection = {
      pcaXAxis: ref(1), pcaYAxis: ref(2), featureXAxis: ref(0), featureYAxis: ref(1),
      regressionTargetIdx: ref(0), scoreColorMode: ref("labels"), sampleColorField: ref(""),
      sampleSymbolField: ref(""), selectedFeatureScale: ref("__primary__"),
      selectedFeatureLabels: ref("__primary__"), selectedFeatureTitle: ref("__primary__"),
      selectedSampleLabels: ref("__primary__"),
    };
    const quick = useQuickPlotProjection(ref(pca()), ref("model.pca"), undefined, undefined, selection);
    quick.selectedPlotKey.value = "pca_scores";
    expect(quick.xAxis).toBe(selection.pcaXAxis);
    expect(quick.yAxis).toBe(selection.pcaYAxis);
    expect(quick.plotLayout.value.xaxis.title).toBe("PC2 (30%)");
    selection.pcaXAxis.value = 0;
    await nextTick();
    expect(quick.plotLayout.value.xaxis.title).toBe("PC1 (60%)");
  });

  it("keeps persisted PLS-DA class groups identical in quick and detailed plots", () => {
    const output = {
      data: [[1, 2], [3, 4], [5, 6], [7, 8]],
      presentation_value: [[1, 2], [3, 4], [5, 6], [7, 8]],
      metadata: {
        type: "PLS_DA",
        sample_labels: ["sample-1", "sample-2", "sample-3", "sample-4"],
        sample_classes: ["A", "B", "A", "B"],
        label_categories: ["A", "B"],
        lv_labels: ["LV1", "LV2"],
        scientific_presentation: {
          schema_version: "spectrasherpa-node-presentation/1",
          contract_digest: "a".repeat(64),
          presentation_id: "scores",
          label: "PLS-DA Scores",
          kind: "plsda_scores",
          source_port: "X_scores",
          source_ports: ["X_scores"],
          modes: ["plot"],
          description: "",
        },
      },
    } as unknown as NodeOutput;
    const { quick, detail } = views(output, "classification.plsda");
    const quickTraces = quick.plotData.value as Array<{ name?: string; text?: string[] }>;

    expect(quickTraces.map((trace) => trace.name)).toEqual(["A", "B"]);
    expect(detail.plotBag.value.classificationScoresData).toEqual(quick.plotData.value);
    expect(quickTraces.flatMap((trace) => trace.text ?? [])).toEqual([
      "sample-1", "sample-3", "sample-2", "sample-4",
    ]);
  });

  it.each([
    ["pca_scores", "pcaScores"], ["pca_biplot", "pcaBiplot"],
    ["pca_loadings", "pcaLoadings"], ["pca_scree", "pcaScree"],
    ["pca_diagnostics", "pcaDiagnostics"],
  ])("shares traces and layouts for %s, including changed PCs", async (key, prefix) => {
    const { quick, detail, x, y } = views(pca(), "model.pca");
    quick.selectedPlotKey.value = key;
    const assertParity = () => {
      const bag = detail.plotBag.value as unknown as Record<string, unknown>;
      expect(quick.plotData.value.length).toBeGreaterThan(0);
      expect(quick.plotData.value).toEqual(bag[`${prefix}Data`]);
      expect(quick.plotLayout.value).toEqual(bag[`${prefix}Layout`]);
    };
    assertParity();
    quick.xAxis.value = x.value = 1;
    quick.yAxis.value = y.value = 2;
    await nextTick();
    assertParity();
  });

  it.each([
    ["mcr_concentrations", "mcrConcentration"], ["mcr_spectra", "mcrSpectra"],
    ["mcr_original_contour", "mcrOriginalContour"],
    ["mcr_reconstructed_contour", "mcrReconstructedContour"],
    ["mcr_residual_contour", "mcrResidualContour"],
  ])("shares decomposition coordinates and layouts for %s", (key, prefix) => {
    const { quick, detail } = views({
      data: [[1, 2], [3, 4]],
      metadata: {
        type: "MCR_ALS", St: [[1, 2, 3], [4, 5, 6]],
        spectral_wavenumbers: [600, 1000, 1400],
        spectral_x_title: "Wavenumber", spectral_x_units: "cm-1",
      },
      ports: { residuals: { data: [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]] } },
    } as unknown as NodeOutput, "model.mcr_als");
    quick.selectedPlotKey.value = key;
    const bag = detail.plotBag.value as unknown as Record<string, unknown>;
    expect(quick.plotData.value.length).toBeGreaterThan(0);
    expect(quick.plotData.value).toEqual(bag[`${prefix}Data`]);
    expect(quick.plotLayout.value).toEqual(bag[`${prefix}Layout`]);
    if (key !== "mcr_concentrations") expect(quick.plotLayout.value.xaxis.autorange).toBe("reversed");
  });

  it("shares classification accuracy and its validation label", () => {
    const { quick, detail } = views({
      data: [[1], [2]], metadata: {
        type: "KNN", y_true: ["a", "b"], y_pred_cv: ["a", "a"], label_categories: ["a", "b"],
      },
    } as unknown as NodeOutput, "classification.knn");
    quick.selectedPlotKey.value = "classification_accuracy";
    expect(quick.plotData.value).toEqual(detail.plotBag.value.classificationAccuracyData);
    expect(quick.plotLayout.value).toEqual(detail.plotBag.value.classificationAccuracyLayout);
    expect(quick.plotData.value[0].y).toEqual([100, 0]);
    expect(quick.plotLayout.value.title.text).toContain("Cross-Validation");
  });

  it("retains labels inherited from the quick plot input", () => {
    const output = pca();
    delete output.metadata.sample_labels;
    const labels = ["Specimen 1", "Specimen 2", "Specimen 3"];
    const quick = useQuickPlotProjection(ref(output), ref("model.pca"), ref({ metadata: { sample_labels: labels } }));
    quick.selectedPlotKey.value = "pca_scores";
    const { detail } = views({ ...output, metadata: { ...output.metadata, sample_labels: labels } }, "model.pca");
    expect(quick.plotData.value).toEqual(detail.plotBag.value.pcaScoresData);
  });
});
