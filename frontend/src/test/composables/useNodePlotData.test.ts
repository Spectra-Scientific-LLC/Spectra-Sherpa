import { describe, expect, it } from "vitest";
import { nextTick, ref, toRaw } from "vue";
import { useNodePlotData } from "@/views/workflow-builder/node-detail/composables/useNodePlotData";
import type { NodeOutput } from "@/utils/nodeOutput";

const makePlotData = (
  options: {
    output?: NodeOutput;
    nodeType?: string;
    isPCAOutput?: boolean;
    sampleColorField?: string;
    sampleSymbolField?: string;
    selectedFeatureScale?: string;
    selectedFeatureLabels?: string;
    selectedFeatureTitle?: string;
    selectedSampleLabels?: string;
  } = {},
) => {
  const nodeOutput = ref<NodeOutput>(
    options.output ?? {
      data: [[1.1], [1.9], [3.2]],
      metadata: {
        diagnostics: {
          algorithm_id: "simpls",
          x_explained_variance: [0.7, 0.2],
          y_explained_variance: [0.8, 0.1],
        },
        scientific_presentation: {
          schema_version: "spectrasherpa-node-presentation/1",
          contract_digest: "a".repeat(64),
          presentation_id: "calibration_fit",
          label: "Calibration Fit",
          kind: "regression_comparison",
          source_port: "calibration_comparison",
          source_ports: ["calibration_comparison"],
          modes: ["plot", "table"],
          description: "Training-set reference and fitted values.",
        },
      },
      ports: {
        default: { data: [[1.1], [1.9], [3.2]], metadata: {}, value: [[1.1], [1.9], [3.2]] },
        vip_scores: { data: [0.8, 1.2, 1.5], metadata: {}, value: [0.8, 1.2, 1.5] },
        calibration_comparison: {
          data: [
            {
              sample: "1",
              target: "Moisture",
              reference: 1,
              predicted: 1.1,
              residual: -0.1,
              role: "calibration",
            },
            {
              sample: "2",
              target: "Moisture",
              reference: 2,
              predicted: 1.9,
              residual: 0.1,
              role: "calibration",
            },
            {
              sample: "3",
              target: "Moisture",
              reference: 3,
              predicted: 3.2,
              residual: -0.2,
              role: "calibration",
            },
          ],
          metadata: {},
          value: {
            schema_version: "spectrasherpa-regression-comparison/1",
            data: [
              {
                sample: "1",
                target: "Moisture",
                reference: 1,
                predicted: 1.1,
                residual: -0.1,
                role: "calibration",
              },
              {
                sample: "2",
                target: "Moisture",
                reference: 2,
                predicted: 1.9,
                residual: 0.1,
                role: "calibration",
              },
              {
                sample: "3",
                target: "Moisture",
                reference: 3,
                predicted: 3.2,
                residual: -0.2,
                role: "calibration",
              },
            ],
            metadata: { target_names: ["Moisture"], role: "calibration" },
          },
        },
        explained_variance: {
          data: [
            [0.7, 0.8],
            [0.2, 0.1],
          ],
          metadata: {},
          value: [
            [0.7, 0.8],
            [0.2, 0.1],
          ],
        },
      },
      primary_port: "default",
      presentation_value: {
        schema_version: "spectrasherpa-regression-comparison/1",
        data: [
          {
            sample: "1",
            target: "Moisture",
            reference: 1,
            predicted: 1.1,
            residual: -0.1,
            role: "calibration",
          },
          {
            sample: "2",
            target: "Moisture",
            reference: 2,
            predicted: 1.9,
            residual: 0.1,
            role: "calibration",
          },
          {
            sample: "3",
            target: "Moisture",
            reference: 3,
            predicted: 3.2,
            residual: -0.2,
            role: "calibration",
          },
        ],
        metadata: { target_names: ["Moisture"], role: "calibration" },
      },
    },
  );
  const pcaXAxis = ref(0);
  const pcaYAxis = ref(1);
  const plots = useNodePlotData({
    nodeOutput,
    nodeType: ref(options.nodeType ?? "model.fitted_pls"),
    nodeTypeKey: ref(options.nodeType ?? "model.fitted_pls"),
    hasOutput: ref(true),
    isPCAOutput: ref(options.isPCAOutput ?? false),
    pcaXAxis,
    pcaYAxis,
    scoreColorMode: ref("samples"),
    sampleColorField: ref(options.sampleColorField ?? "specimen_id"),
    sampleSymbolField: ref(options.sampleSymbolField ?? "block"),
    selectedFeatureScale: ref(options.selectedFeatureScale ?? "__primary__"),
    selectedFeatureLabels: ref(options.selectedFeatureLabels ?? "__primary__"),
    selectedFeatureTitle: ref(options.selectedFeatureTitle ?? "__primary__"),
    selectedSampleLabels: ref(options.selectedSampleLabels ?? "__primary__"),
    plsdaLoadingsViewMode: ref("lines"),
    featureXAxis: ref(0),
    featureYAxis: ref(1),
    contourClickPoint: ref(null),
    regressionTargetOptions: ref([{ label: "Moisture", value: 0 }]),
  });
  return { ...plots, nodeOutput, pcaXAxis, pcaYAxis };
};

describe("useNodePlotData canonical fitted PLS presentation", () => {
  it("renders the declared Peak Detection overlay from its visualization port", () => {
    const traces = [{ type: "scatter", mode: "lines", x: [1000, 900], y: [0.2, 0.8] }];
    const presentationValue = {
      peak_finding: {
        data: traces,
        layout: { title: "Spectra with Peaks", xaxis: { autorange: "reversed" } },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "analysis.peak_finding",
      output: {
        data: [],
        metadata: {
          scientific_presentation: {
            schema_version: "spectrasherpa-node-presentation/1",
            contract_digest: "b".repeat(64),
            presentation_id: "peak_overlay",
            label: "Spectra with Peaks",
            kind: "visualization",
            source_port: "plots",
            source_ports: ["plots"],
            modes: ["plot"],
            description: "Input spectra with detected peaks.",
          },
        },
        ports: {
          plots: { data: [], metadata: presentationValue, value: presentationValue },
        },
        primary_port: "plots",
        presentation_value: presentationValue,
      } as NodeOutput,
    });

    expect(plotBag.value.peakFindingPlotLabel).toBe("Spectra with Peaks");
    expect(plotBag.value.peakFindingPlotData).toEqual(traces);
    expect(plotBag.value.peakFindingPlotLayout).toMatchObject({
      title: { text: "Spectra with Peaks" },
      xaxis: { autorange: "reversed" },
    });
  });

  it("switches among stored PCA components without refitting and keeps axes distinct", async () => {
    const scoreWire = {
      data: [
        [1, 2, 3],
        [4, 5, 6],
      ],
      y_axis: { labels: ["sample-1", "sample-2"] },
    };
    const output = {
      data: scoreWire.data,
      metadata: { n_components: 3, explained_variance_ratio: [0.7, 0.2, 0.08] },
      ports: { scores: { value: scoreWire }, default: { value: scoreWire } },
      primary_port: "scores",
    } as NodeOutput;
    const { nodeOutput, pcaXAxis, pcaYAxis, plotBag } = makePlotData({
      nodeType: "model.pca",
      isPCAOutput: true,
      output,
    });

    pcaYAxis.value = 0;
    await nextTick();
    expect([pcaXAxis.value, pcaYAxis.value]).toEqual([0, 1]);

    pcaXAxis.value = 1;
    await nextTick();
    expect([pcaXAxis.value, pcaYAxis.value]).toEqual([1, 2]);
    expect(plotBag.value.pcaScoresLayout.xaxis.title).toBe("PC2 (20.0%)");
    expect(plotBag.value.pcaScoresLayout.yaxis.title).toBe("PC3 (8.0%)");
    expect(toRaw(nodeOutput.value)).toBe(output);
    expect(toRaw(nodeOutput.value?.ports?.scores?.value)).toBe(scoreWire);
  });

  it("uses the canonical PCA sample table for 11 specimen colors and three block symbols", () => {
    const specimens = Array.from({ length: 11 }, (_, index) => `S${index + 1}`);
    const specimenIds = [...specimens, ...specimens, ...specimens];
    const blocks = ["1", "2", "3"].flatMap((block) => Array(11).fill(block));
    const labels = specimenIds.map((specimen, index) => `${specimen}__B${blocks[index]}`);
    const scores = labels.map((_, index) => [index, index / 2, -index]);
    const scoreWire = {
      data: scores,
      y_axis: {
        labels,
        sample_table: {
          sample_id: labels,
          specimen_id: specimenIds,
          block: blocks,
          claimed_botanical_group: specimenIds.map((_, index) =>
            index % 2 ? "angustifolia" : "latifolia",
          ),
          acquisition_order: [
            ...Array.from({ length: 11 }, (_, index) => index + 1),
            ...Array.from({ length: 11 }, (_, index) => index + 1),
            ...Array.from({ length: 11 }, (_, index) => index + 1),
          ],
        },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "model.pca",
      isPCAOutput: true,
      output: {
        data: scores,
        metadata: { n_components: 3, explained_variance_ratio: [0.9, 0.06, 0.02] },
        ports: { scores: { value: scoreWire }, default: { value: scoreWire } },
        primary_port: "scores",
      } as NodeOutput,
    });
    const specimenTraces = plotBag.value.pcaScoresData.slice(0, 11) as any[];
    const blockTraces = plotBag.value.pcaScoresData.slice(11) as any[];
    expect(specimenTraces.flatMap((trace) => trace.x)).toHaveLength(33);
    expect(new Set(specimenTraces.map((trace) => trace.marker.color)).size).toBe(11);
    expect(blockTraces.map((trace) => trace.marker.symbol)).toEqual([
      "circle",
      "diamond",
      "square",
    ]);
    expect(plotBag.value.metadataGroupingError).toBe("");
    expect(plotBag.value.pcaScoresLayout.showlegend).toBe(true);
  });

  it("switches PCA color to any safe low-cardinality metadata column", () => {
    const labels = ["A__B1", "B__B1", "A__B2", "B__B2"];
    const scoreWire = {
      data: [
        [0, 0],
        [1, 1],
        [0.1, 0.2],
        [1.1, 1.2],
      ],
      y_axis: {
        labels,
        sample_table: {
          sample_id: labels,
          specimen_id: ["A", "B", "A", "B"],
          block: ["1", "1", "2", "2"],
          authenticity_status: ["reported", "pending", "reported", "pending"],
        },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "model.pca",
      isPCAOutput: true,
      sampleColorField: "authenticity_status",
      sampleSymbolField: "block",
      output: {
        data: scoreWire.data,
        metadata: { n_components: 2, explained_variance_ratio: [0.8, 0.15] },
        ports: { scores: { value: scoreWire } },
        primary_port: "scores",
      } as NodeOutput,
    });
    const colorTraces = plotBag.value.pcaScoresData.slice(0, 2) as any[];
    expect(colorTraces.map((trace) => trace.name)).toEqual(["reported", "pending"]);
    expect(plotBag.value.sampleColorFieldOptions.map((option) => option.value)).toContain(
      "authenticity_status",
    );
  });

  it("uses the same metadata selectors for classification score nodes", () => {
    const labels = ["A__B1", "B__B1", "A__B2", "B__B2"];
    const scoreWire = {
      data: [
        [0, 0],
        [1, 1],
        [0.1, 0.2],
        [1.1, 1.2],
      ],
      y_axis: {
        labels,
        sample_table: {
          sample_id: labels,
          specimen_id: ["A", "B", "A", "B"],
          block: ["1", "1", "2", "2"],
          supplier_batch: ["lot-1", "lot-2", "lot-1", "lot-2"],
        },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "classification.plsda",
      sampleColorField: "supplier_batch",
      output: {
        data: scoreWire.data,
        metadata: { lv_labels: ["LV1", "LV2"] },
        ports: { scores: { value: scoreWire } },
        primary_port: "scores",
      } as NodeOutput,
    });
    expect(
      (plotBag.value.classificationScoresData.slice(0, 2) as any[]).map((trace) => trace.name),
    ).toEqual(["lot-1", "lot-2"]);
  });

  it("uses metadata color and line style for spectral outputs from data and preprocessing nodes", () => {
    const labels = ["A__B1", "B__B1", "A__B2", "B__B2"];
    const wire = {
      data: [
        [1, 2, 3],
        [2, 3, 4],
        [1.1, 2.1, 3.1],
        [2.1, 3.1, 4.1],
      ],
      y_axis: {
        labels,
        sample_table: {
          sample_id: labels,
          specimen_id: ["A", "B", "A", "B"],
          block: ["1", "1", "2", "2"],
        },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "data.load_group",
      output: {
        data: wire.data,
        metadata: { data_type: "spectra", wavenumbers: [3, 2, 1], x_units: "cm-1" },
        ports: { default: { value: wire } },
        primary_port: "default",
      } as NodeOutput,
    });
    const samples = plotBag.value.spectraOverlayData.slice(0, 4) as any[];
    expect(new Set(samples.map((trace) => trace.line.color)).size).toBe(2);
    expect(new Set(samples.map((trace) => trace.line.dash)).size).toBe(2);
  });

  it("keeps PCA scores visible when a sample table is misaligned", () => {
    const scoreWire = {
      data: [
        [1, 2],
        [3, 4],
      ],
      y_axis: {
        labels: ["A", "B"],
        sample_table: {
          sample_id: ["B", "A"],
          specimen_id: ["S1", "S2"],
          block: ["1", "2"],
          acquisition_order: [1, 2],
        },
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "model.pca",
      isPCAOutput: true,
      output: {
        data: scoreWire.data,
        metadata: {
          n_components: 2,
          sample_classes: ["malignant", "benign"],
          label_categories: ["malignant", "benign"],
        },
        ports: {
          scores: { value: scoreWire },
          loadings: { data: [[0.1, 0.2], [0.3, 0.4]] },
        },
        primary_port: "scores",
      } as NodeOutput,
    });
    expect(plotBag.value.pcaScoresData).toHaveLength(1);
    expect(plotBag.value.pcaScoresData[0]).toMatchObject({
      x: [1, 3],
      y: [2, 4],
    });
    const scoreTraceNames = (
      plotBag.value.pcaScoresData as Array<{ name?: string }>
    ).map((trace) => trace.name);
    const biplotTraceNames = (
      plotBag.value.pcaBiplotData as Array<{ name?: string }>
    ).map((trace) => trace.name);
    expect(scoreTraceNames).not.toEqual(
      expect.arrayContaining(["malignant", "benign"]),
    );
    expect(biplotTraceNames).not.toEqual(
      expect.arrayContaining(["malignant", "benign"]),
    );
    expect(plotBag.value.metadataGroupingError).toContain("refused");
    expect(plotBag.value.pcaScoresLayout.meta).toMatchObject({
      metadata_grouping_notice: expect.stringContaining("refused"),
    });
    expect(plotBag.value.pcaScoresLayout.meta).not.toHaveProperty("refusal_reason");
    expect(plotBag.value.pcaScoresLayout.showlegend).toBe(false);
    expect(plotBag.value.pcaBiplotLayout.meta).not.toHaveProperty("refusal_reason");
  });

  it("renders an aligned sample table normally when no metadata style is useful", () => {
    const labels = Array.from({ length: 25 }, (_, index) => `sample-${index + 1}`);
    const scoreWire = {
      data: labels.map((_, index) => [index, index / 2]),
      y_axis: { labels, sample_table: { sample_id: labels } },
    };
    const { plotBag } = makePlotData({
      nodeType: "model.pca",
      isPCAOutput: true,
      output: {
        data: scoreWire.data,
        metadata: { n_components: 2 },
        ports: { scores: { value: scoreWire } },
        primary_port: "scores",
      } as NodeOutput,
    });
    expect(plotBag.value.metadataGroupingError).toBe("");
    expect(plotBag.value.sampleColorFieldOptions).toEqual([]);
    expect(plotBag.value.pcaScoresData.length).toBeGreaterThan(0);
  });

  it("uses the canonical calibration-comparison output directly", () => {
    const { plotBag } = makePlotData();
    expect(plotBag.value.regressionCorrelationData[0]).toMatchObject({
      x: [1, 2, 3],
      y: [1.1, 1.9, 3.2],
      name: "Moisture",
    });
    expect(plotBag.value.regressionCorrelationLayout.title.text).toContain("calibration");
  });

  it("renders the canonical evaluator comparison without a visualization alias", () => {
    const comparison = {
      schema_version: "spectrasherpa-regression-comparison/1",
      data: [
        {
          sample: "A",
          target: "Protein",
          reference: 9.8,
          predicted: 10.1,
          residual: -0.3,
          role: "held_out_test",
        },
        {
          sample: "B",
          target: "Protein",
          reference: 11.2,
          predicted: 11.0,
          residual: 0.2,
          role: "held_out_test",
        },
      ],
      metadata: { target_names: ["Protein"], role: "held_out_test" },
    };
    const { plotBag } = makePlotData({
      nodeType: "diagnostics.regression_evaluator",
      output: {
        data: { rmse: 0.25 },
        metadata: {
          scientific_presentation: {
            schema_version: "spectrasherpa-node-presentation/1",
            contract_digest: "b".repeat(64),
            presentation_id: "held_out_comparison",
            label: "Held-out Comparison",
            kind: "regression_comparison",
            source_port: "comparison",
            source_ports: ["comparison"],
            modes: ["plot", "table"],
            description: "Held-out reference and predicted values.",
          },
        },
        ports: {
          comparison: { data: comparison.data, metadata: comparison.metadata, value: comparison },
        },
        primary_port: "default",
        presentation_value: comparison,
      } as NodeOutput,
    });

    expect(plotBag.value.holdoutVisualization).toMatchObject({
      type: "predicted_vs_actual",
      comparison,
    });
    expect(plotBag.value.holdoutRegressionData[0]).toMatchObject({
      name: "Protein",
      x: [9.8, 11.2],
      y: [10.1, 11],
    });
  });

  it("does not union sibling presentations by node identity", () => {
    const { plotBag } = makePlotData();
    expect(plotBag.value.availablePlots).toEqual(["Predicted vs Reference"]);
    expect(plotBag.value.plsVipData[0].y).toEqual([0.8, 1.2, 1.5]);
    expect(plotBag.value.plsExplainedVarianceData).toEqual([
      expect.objectContaining({ name: "X", y: [70, 20] }),
      expect.objectContaining({ name: "Y", y: [80, 10] }),
    ]);
  });

  it("preserves the pre-existing PLS-DA Inspector plot as the first authority", () => {
    const prebuiltData = [{ type: "bar", x: ["legacy-ranked"], y: [1.7] }];
    const { plotBag } = makePlotData({
      nodeType: "classification.plsda",
      output: {
        data: [[0.1, 0.9]],
        metadata: {
          type: "PLS_DA",
          vip_scores: [0.5, 2.0],
          y_true: ["A"],
          y_pred: ["A"],
          label_categories: ["A"],
        },
        plots: {
          vip: {
            data: prebuiltData,
            layout: { title: "Existing Inspector VIP" },
          },
        },
      } as NodeOutput,
    });

    expect(plotBag.value.availablePlots).toContain("VIP Scores");
    expect(plotBag.value.plsdaVipData).toEqual(prebuiltData);
    expect(plotBag.value.plsdaVipLayout).toMatchObject({
      title: "Existing Inspector VIP",
      height: 350,
    });
  });

  it("applies DSO axis and class-set choices through the shared node plot path", () => {
    const wire = {
      data: [
        [1, 2, 3],
        [4, 5, 6],
      ],
      x_axis: {
        data: [1000, 900, 800],
        title: "Wavenumber",
        units: "cm-1",
        labels: ["v1", "v2", "v3"],
        alternate_scales: [
          {
            name: "Wavelength",
            values: [10000, 11111.111, 12500],
            title: "Wavelength",
            units: "nm",
            source_set_index: 1,
          },
        ],
        alternate_label_sets: [
          { name: "Channels", values: ["D1", "D2", "D3"], source_set_index: 1 },
        ],
        alternate_title_sets: [
          { name: "Detector title", title: "Detector response", source_set_index: 1 },
        ],
      },
      y_axis: {
        labels: ["sample-1", "sample-2"],
        alternate_label_sets: [
          { name: "Display names", values: ["Lavender A", "Lemon B"], source_set_index: 1 },
        ],
        class_sets: [
          {
            name: "Species",
            values: [1, 2],
            levels: [
              { code: 1, label: "Lavender" },
              { code: 2, label: "Lemon" },
            ],
            source_set_index: 0,
          },
        ],
      },
    };
    const { plotBag } = makePlotData({
      nodeType: "data.file_load",
      sampleColorField: "Species",
      sampleSymbolField: "__none__",
      selectedFeatureScale: "scale:Wavelength",
      selectedFeatureLabels: "labels:Channels",
      selectedFeatureTitle: "title:Detector title",
      selectedSampleLabels: "labels:Display names",
      output: {
        data: wire.data,
        metadata: { is_spectra: true, data_type: "spectra" },
        ports: { default: { data: wire.data, value: wire, metadata: {} } },
        primary_port: "default",
      } as NodeOutput,
    });

    expect(plotBag.value.featureScaleOptions.map((option) => option.value)).toContain(
      "scale:Wavelength",
    );
    expect(plotBag.value.sampleColorFieldOptions).toEqual([{ label: "Species", value: "Species" }]);
    const sampleTraces = plotBag.value.spectraOverlayData.filter((trace: any) =>
      trace.y?.some((value: unknown) => typeof value === "number"),
    );
    expect(sampleTraces.map((trace: any) => trace.x)).toEqual([
      [10000, 11111.111, 12500],
      [10000, 11111.111, 12500],
    ]);
    expect(sampleTraces.map((trace: any) => trace.name)).toEqual(["Lavender A", "Lemon B"]);
    expect(plotBag.value.spectraOverlayLayout.xaxis.title).toBe("Detector response (nm)");
    expect(plotBag.value.featureOptions.map((option) => option.label)).toEqual(["D1", "D2", "D3"]);
  });

  it("retains the complete pre-C2zr Inspector plot-family census", () => {
    const cases: Array<[string, string[]]> = [
      [
        "model.mcr_als",
        [
          "Concentration Profiles",
          "Pure Spectra",
          "Ground Truth Validation",
          "Original Contour",
          "Reconstructed Contour",
          "Residual Contour",
        ],
      ],
      ["model.simplisma", ["Concentration Profiles", "Pure Spectra"]],
      ["model.efa", ["Eigenvalue Plot"]],
      ["model.apply_fitted_pls", ["Predicted vs Actual"]],
      ["model.pcr", ["Predicted vs Actual"]],
      ["model.svr", ["Predicted vs Actual"]],
      ["classification.simca", ["Scores Plot", "Confusion Matrix", "Per-Class Accuracy"]],
      [
        "classification.knn",
        ["Feature Space Plot", "K-Optimization", "Confusion Matrix", "Per-Class Accuracy"],
      ],
      ["diagnostics.outliers", ["T² vs Q Control Chart"]],
      ["diagnostics.regression_evaluator", ["Evaluation Results"]],
      ["diagnostics.classification_evaluator", ["Evaluation Results"]],
      ["diagnostics.cross_validation", ["Evaluation Results"]],
      ["model.kmeans", ["Cluster Scatter"]],
      ["model.dbscan", ["Cluster Scatter"]],
      ["model.nmf", ["Concentration Profiles", "Pure Spectra"]],
      ["model.ica", ["Concentration Profiles", "Pure Spectra"]],
      ["model.hca", ["Dendrogram"]],
      ["stats.summary", ["Summary Plot"]],
      ["analysis.peak_finding", ["Spectra with Peaks"]],
      ["analysis.compare_library", ["Library Overlay"]],
      ["output.plot", ["Visualization"]],
      ["output.contour", ["Visualization"]],
      ["data.file_load", ["Data Overview"]],
      ["preprocess.normalize", ["Data Overview"]],
      ["preprocess.scale", ["Data Overview"]],
      ["preprocess.clip_range", ["Data Overview"]],
      ["preprocess.cosmic_ray", ["Data Overview"]],
      ["baseline.penalized_ls", ["Data Overview"]],
      ["baseline.rubberband", ["Data Overview"]],
      ["preprocess.smooth", ["Data Overview"]],
    ];
    const minimalOutput = {
      data: [[1]],
      metadata: {},
      ports: {},
      primary_port: "default",
    } as NodeOutput;

    for (const [nodeType, expected] of cases) {
      const { plotBag } = makePlotData({
        nodeType,
        output: minimalOutput,
      });
      expect(plotBag.value.availablePlots, nodeType).toEqual(expected);
    }

    const { plotBag: pcaPlots } = makePlotData({
      nodeType: "model.pca",
      output: minimalOutput,
      isPCAOutput: true,
    });
    expect(pcaPlots.value.availablePlots).toEqual([
      "Scores Plot",
      "Biplot",
      "Loadings Plot",
      "Scree Plot",
      "Diagnostics Plot",
    ]);
  });
});
