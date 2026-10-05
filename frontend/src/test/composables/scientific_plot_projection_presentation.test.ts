/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";

import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";
import type { NodePortMetadata, NodeTypeMetadata } from "@/types";
import { buildNodeOutput } from "@/utils/nodeOutput";
import {
  projectScientificPresentation,
  resolveScientificPresentation,
} from "@/utils/scientificPresentation";

const projectedOutput = (
  kind: string,
  data: unknown,
  presentationValue: unknown = data,
  descriptor?: Record<string, unknown>,
) => ({
  data,
  descriptor,
  presentation_value: presentationValue,
  presentation_contract: {
    digest: "a".repeat(64),
    payload: {
      schema_version: "spectrasherpa-node-presentation/1",
      default_presentation: "result",
      presentations: [],
    },
  },
  metadata: {
    scientific_presentation: {
      schema_version: "spectrasherpa-node-presentation/1",
      contract_digest: "a".repeat(64),
      presentation_id: "result",
      label: "Result",
      kind,
      source_port: "result",
      source_ports: ["result"],
      modes: ["plot"],
      description: "",
    },
  },
});

describe("canonical scientific presentation projection", () => {
  it.each(["diagnostics.regression_evaluator", "diagnostics.labeled_regression_evaluator"])("renders the exact multi-target comparison for %s", (nodeType) => {
    const data = [
      {
        sample: "1",
        target: "Moisture",
        reference: 10,
        predicted: 9.8,
        residual: 0.2,
        role: "held_out_test",
      },
      {
        sample: "1",
        target: "Oil",
        reference: 4,
        predicted: 4.1,
        residual: -0.1,
        role: "held_out_test",
      },
      {
        sample: "2",
        target: "Moisture",
        reference: 11,
        predicted: 11.2,
        residual: -0.2,
        role: "held_out_test",
      },
      {
        sample: "2",
        target: "Oil",
        reference: 5,
        predicted: 4.9,
        residual: 0.1,
        role: "held_out_test",
      },
    ];
    const nodeOutput = ref(projectedOutput("regression_comparison", data) as any);
    const plot = useQuickPlotProjection(nodeOutput, ref(nodeType));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_regression_comparison", label: "Predicted vs Reference" },
    ]);
    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual([
      "Moisture",
      "Oil",
      "1:1 Line",
    ]);
    expect(plot.plotData.value[0].x).toEqual([10, 11]);
    expect(plot.plotData.value[0].y).toEqual([9.8, 11.2]);
  });

  it("renders typed explained variance without reading diagnostics", () => {
    const data = [
      [0.6, 0.7],
      [0.2, 0.15],
    ];
    const nodeOutput = ref(projectedOutput("pls_explained_variance", data) as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.fitted_pls"));
    expect(plot.plotData.value.map((trace: any) => trace.y)).toEqual([
      [60, 20],
      [70, 15],
    ]);
  });

  it("renders a one-vector PCA explained-variance result as a scree plot", () => {
    const nodeOutput = ref(
      projectedOutput("pca_explained_variance", [0.73, 0.23, 0.04]) as any,
    );
    const plot = useQuickPlotProjection(nodeOutput, ref("model.pca"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_pca_explained_variance", label: "Scree Plot" },
    ]);
    expect(plot.plotData.value).toEqual([
      expect.objectContaining({ name: "Individual variance", y: [73, 23, 4] }),
      expect.objectContaining({ name: "Cumulative variance", y: [73, 96, 100] }),
    ]);
    expect(plot.dataShape.value).toMatchObject({ rows: 3, cols: 0, rowLabel: "components" });
  });

  it("renders component scores as a selectable PCx-versus-PCy map", () => {
    const output = projectedOutput("pca_scores", [
      [1, 2, 3],
      [4, 5, 6],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      explained_variance_ratio: [0.7, 0.2, 0.1],
      sample_labels: ["sample-a", "sample-b"],
    };
    const plot = useQuickPlotProjection(ref(output), ref("model.pca"));

    expect(plot.showAxisControls.value).toBe(true);
    expect(plot.axisOptions.value.map((option) => option.label)).toEqual([
      "PC1 (70.0%)",
      "PC2 (20.0%)",
      "PC3 (10.0%)",
    ]);
    expect(plot.plotData.value[0]).toMatchObject({ x: [1, 4], y: [2, 5] });
    plot.yAxis.value = 2;
    expect(plot.plotData.value[0]).toMatchObject({ x: [1, 4], y: [3, 6] });
  });

  it("groups PCA scores by persisted classes while retaining sample IDs", () => {
    const output = projectedOutput("pca_scores", [
      [1, 2],
      [3, 4],
      [5, 6],
      [7, 8],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      type: "PCA",
      sample_labels: ["Sample 1", "Sample 2", "Sample 3", "Sample 4"],
      sample_classes: ["0", "1", "0", "1"],
      label_categories: ["0", "1"],
    };
    const plot = useQuickPlotProjection(ref(output), ref("model.pca"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["0", "1"]);
    expect(plot.plotData.value[0]).toMatchObject({
      x: [1, 5],
      y: [2, 6],
      text: ["Sample 1", "Sample 3"],
    });
    expect(plot.plotData.value[1]).toMatchObject({
      x: [3, 7],
      y: [4, 8],
      text: ["Sample 2", "Sample 4"],
    });
  });

  it("keeps the colored PCA score map when live assignments are rehydrated", async () => {
    const data = [[1, 2], [3, 4], [5, 6], [7, 8]];
    const live = projectedOutput("pca_scores", data) as any;
    live.metadata = {
      ...live.metadata,
      type: "PCA",
      sample_labels: ["Sample 1", "Sample 2", "Sample 3", "Sample 4"],
      y_true: ["0", "1", "0", "1"],
      label_categories: ["0", "1"],
    };
    const source = ref(live);
    const plot = useQuickPlotProjection(source, ref("model.pca"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["0", "1"]);

    source.value = {
      ...live,
      metadata: {
        ...live.metadata,
        y_true: undefined,
        sample_classes: ["0", "1", "0", "1"],
      },
    };
    await nextTick();

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["0", "1"]);
    expect(plot.plotData.value.reduce(
      (count: number, trace: any) => count + trace.x.length,
      0,
    )).toBe(4);
  });

  it("falls back to one complete PCA score trace when declared classes lack assignments", () => {
    const output = projectedOutput("pca_scores", [
      [1, 2],
      [3, 4],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      type: "PCA",
      sample_labels: ["Sample 1", "Sample 2"],
      label_categories: ["A", "B"],
    };
    const plot = useQuickPlotProjection(ref(output), ref("model.pca"));

    expect(plot.plotData.value).toHaveLength(1);
    expect(plot.plotData.value[0]).toMatchObject({
      x: [1, 3],
      y: [2, 4],
      text: ["Sample 1", "Sample 2"],
    });
  });

  it("renders PLS scores as an LV map instead of component traces over sample order", () => {
    const output = projectedOutput("pls_scores", [
      [1, 2, 3],
      [4, 5, 6],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      diagnostics: { x_explained_variance: [0.6, 0.25, 0.1] },
    };
    const plot = useQuickPlotProjection(ref(output), ref("model.fitted_pls"));

    expect(plot.showAxisControls.value).toBe(true);
    expect(plot.axisOptions.value.map((option) => option.label)).toEqual([
      "LV1 (60.0%)",
      "LV2 (25.0%)",
      "LV3 (10.0%)",
    ]);
    expect(plot.plotData.value).toHaveLength(1);
    expect(plot.plotData.value[0]).toMatchObject({ x: [1, 4], y: [2, 5] });
  });

  it("uses the producer's component labels for generic score matrices", () => {
    const scores = [
      [1, 2, 3],
      [4, 5, 6],
    ];
    const output = projectedOutput("score_matrix", scores, {
      type: "SherpaDataset",
      data: scores,
      x_axis: { labels: ["IC 1", "IC 2", "IC 3"], title: "Independent Component" },
      y_axis: { labels: ["sample-a", "sample-b"], title: "Sample" },
    }) as any;
    const plot = useQuickPlotProjection(ref(output), ref("model.ica"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual([
      "IC 1",
      "IC 2",
      "IC 3",
    ]);
    expect(plot.plotLayout.value).toMatchObject({
      xaxis: { title: "Sample" },
      yaxis: { title: "Score" },
    });
  });

  it("renders PLS-DA scores by known class while retaining sample identity", () => {
    const output = projectedOutput("plsda_scores", [
      [1, 2],
      [3, 4],
      [5, 6],
      [7, 8],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      sample_labels: ["sample-1", "sample-2", "sample-3", "sample-4"],
      sample_classes: ["A", "B", "A", "B"],
      label_categories: ["A", "B"],
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.showAxisControls.value).toBe(true);
    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["A", "B"]);
    expect(plot.plotData.value[0]).toMatchObject({
      x: [1, 5],
      y: [2, 6],
      text: ["sample-1", "sample-3"],
    });
  });

  it("labels PLS-DA class-response coefficients with variables and classes", () => {
    const output = projectedOutput("regression_coefficients", [
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      target_names: [],
      diagnostics: {
        classes: ["A", "B", "C"],
      },
    };
    output.ports = {
      loadings: {
        value: {
          data: [[0.1, 0.2]],
          x_axis: {
            data: [1001, 1000],
            title: "Wavenumber",
            units: "cm-1",
            quantity: "wavenumber",
          },
        },
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["A", "B", "C"]);
    expect(plot.plotData.value[0].x).toEqual([1001, 1000]);
    expect(plot.plotLayout.value.xaxis).toMatchObject({
      title: "Wavenumber (cm-1)",
      autorange: "reversed",
    });
  });

  it("uses classification metrics as the durable class-label fallback", () => {
    const output = projectedOutput("regression_coefficients", [
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      is_spectra: false,
      data_role: "X_features",
      target_names: [],
      classes: [],
      label_categories: [],
      diagnostics: {
        metrics: { classes: ["class_0", "class_1", "class_2"] },
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual([
      "class_0",
      "class_1",
      "class_2",
    ]);
    expect(plot.plotLayout.value.xaxis.title).toBe("Variable");
  });

  it("reserves label space for feature-table loading axes", () => {
    const output = projectedOutput("pca_loadings", [
      [0.1, 0.2],
      [0.3, 0.4],
    ]) as any;
    output.metadata = { ...output.metadata, feature_names: ["alcohol", "malic acid"] };
    const plot = useQuickPlotProjection(ref(output), ref("model.pca"));

    expect(plot.plotLayout.value.margin.b).toBe(150);
    expect(plot.plotLayout.value.xaxis).toMatchObject({
      automargin: true,
      tickangle: -45,
      title: { text: "Feature", standoff: 24 },
    });
  });

  it("retains PLS-DA class grouping in a persisted score preview", () => {
    const output = projectedOutput("plsda_scores", [
      [1, 2],
      [3, 4],
      [5, 6],
      [7, 8],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      sample_labels: {
        _truncated_sequence: true,
        length: 113,
        preview: ["sample-1", "sample-2", "sample-3", "sample-4"],
        last: "sample-113",
      },
      sample_classes: {
        _truncated_sequence: true,
        length: 113,
        preview: ["A", "B", "A", "B"],
        last: "B",
      },
      label_categories: ["A", "B"],
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["A", "B"]);
    expect(plot.plotData.value[0]).toMatchObject({
      x: [1, 5],
      y: [2, 6],
      text: ["sample-1", "sample-3"],
    });
  });

  it("uses row-aligned dataset annotations over a longer diagnostic preview", () => {
    const output = projectedOutput("plsda_scores", [
      [1, 2],
      [3, 4],
      [5, 6],
      [7, 8],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      sample_labels: {
        _truncated_sequence: true,
        length: 113,
        preview: ["sample-1", "sample-2", "sample-3", "sample-4"],
        last: "sample-113",
      },
      sample_classes: {
        _truncated_sequence: true,
        length: 113,
        preview: ["A", "B", "A", "B"],
        last: "B",
      },
      label_categories: ["A", "B"],
      diagnostics: {
        sample_classes: {
          _truncated_sequence: true,
          length: 113,
          preview: Array.from({ length: 32 }, (_, index) => (index % 2 === 0 ? "A" : "B")),
          last: "B",
        },
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["A", "B"]);
    expect(plot.plotData.value[0].x).toEqual([1, 5]);
    expect(plot.plotData.value[1].x).toEqual([3, 7]);
  });

  it("renders the PLS-DA calibration confusion matrix with real class labels", () => {
    const output = projectedOutput("confusion_matrix", [
      [8, 1],
      [2, 9],
    ]) as any;
    output.metadata = { ...output.metadata, label_categories: ["Control", "Adulterated"] };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value[0]).toMatchObject({
      x: ["Control", "Adulterated"],
      y: ["Control", "Adulterated"],
    });
    expect(plot.plotLayout.value.xaxis.title).toBe("Predicted class");
    expect(plot.plotLayout.value.yaxis.title).toBe("Actual class");
  });

  it("renders joint T²-Q diagnostics with sample identity, flags, and limits", () => {
    const output = projectedOutput("t2_q_diagnostics", [], {
      T2: [1, 9, 2],
      Q: [0.01, 0.08, 0.02],
      flags: [false, true, false],
    }) as any;
    output.metadata = {
      ...output.metadata,
      diagnostics: {
        sample_labels: ["sample-a", "sample-b", "sample-c"],
        t2_limit: 8,
        q_limit: 0.07,
        confidence_level: 0.95,
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("diagnostics.outliers"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_t2_q_diagnostics", label: "T² vs Q" },
    ]);
    expect(plot.plotData.value).toEqual([
      expect.objectContaining({ name: "Calibration sample", text: ["sample-a", "sample-c"] }),
      expect.objectContaining({ name: "Screened outlier", text: ["sample-b"] }),
    ]);
    expect(plot.plotLayout.value.shapes).toHaveLength(2);
    expect(plot.dataShape.value).toMatchObject({ rows: 3, cols: 2, rowLabel: "samples" });
  });

  it.each([
    [
      "pls_loadings",
      [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
      ],
      2,
      3,
    ],
    ["regression_coefficients", [[0.1], [0.2], [0.3]], 1, 3],
  ])(
    "renders a non-empty %s plot with the declared scientific orientation",
    (kind, data, traces, points) => {
      const nodeOutput = ref(projectedOutput(kind as string, data) as any);
      const plot = useQuickPlotProjection(nodeOutput, ref("model.fitted_pls"));

      expect(plot.availablePlots.value).toHaveLength(1);
      expect(plot.plotData.value).toHaveLength(traces as number);
      expect(plot.plotData.value[0].y).toHaveLength(points as number);
    },
  );

  it("renders VIP as a scientific variable profile", () => {
    const output = projectedOutput("variable_profile", [0.4, 1.2, 0.9]) as any;
    output.metadata = {
      ...output.metadata,
      diagnostics: { feature_names: ["sepal length", "sepal width", "petal length"] },
    };
    const nodeOutput = ref(output);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.fitted_pls"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_variable_profile", label: "Variable Profile" },
    ]);
    expect(plot.plotData.value).toHaveLength(1);
    expect(plot.plotData.value[0].x).toEqual(["sepal length", "sepal width", "petal length"]);
    expect(plot.plotData.value[0].y).toEqual([0.4, 1.2, 0.9]);
    expect(plot.dataShape.value).toMatchObject({ rows: 3, cols: 0, rowLabel: "features" });
  });

  it("keeps source units on non-spectral coefficient vectors", () => {
    const output = projectedOutput("regression_coefficients", [[0.1], [0.2]]) as any;
    Object.assign(output.metadata, { is_spectra: false, wavenumbers: [600, 1400], x_units: "cm-1" });
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));
    expect(JSON.stringify(plot.plotLayout.value.xaxis.title)).toContain("cm-1");
    expect(plot.plotData.value[0].x).toEqual([600, 1400]);
  });

  it("inherits input units when retained loadings only declare a generic title", () => {
    const output = projectedOutput("regression_coefficients", [[0.1], [0.2]]) as any;
    output.ports = { loadings: { value: { x_axis: { title: "Variable", data: [600, 1400] } } } };
    const input = ref({ metadata: { x_units: "cm-1", x_title: "Wavenumber" } });
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"), input);
    expect(JSON.stringify(plot.plotLayout.value.xaxis.title)).toContain("cm-1");
    expect(plot.plotData.value[0].x).toEqual([600, 1400]);
  });

  it("reads physical units from retained dataset axes without flattened metadata", () => {
    const output = projectedOutput("regression_coefficients", [[0.1], [0.2]]) as any;
    output.ports = { loadings: { value: { x_axis: { title: "Variable", data: [600, 1400] } } } };
    const inputs = ref({ default: { x_axis: { title: "Wavenumber", units: "cm-1", data: [600, 1400] } } });
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"), undefined, inputs);
    expect(JSON.stringify(plot.plotLayout.value.xaxis.title)).toContain("cm-1");
    expect(plot.plotData.value[0].x).toEqual([600, 1400]);
  });

  it("preserves physical axes on derived X_features coefficient outputs", () => {
    const output = projectedOutput("regression_coefficients", [[0.1], [0.2]]) as any;
    output.metadata.data_role = "X_features";
    output.metadata.x_title = "Latent Variable";
    output.ports = { loadings: { value: { x_axis: { units: "cm-1", data: [600, 1400] } } } };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));
    expect(JSON.stringify(plot.plotLayout.value.xaxis.title)).toContain("cm-1");
    expect(JSON.stringify(plot.plotLayout.value.xaxis.title)).not.toContain("Latent Variable");
    expect(plot.plotData.value[0].x).toEqual([600, 1400]);
  });

  it.each(["X_spectra", "X_features"])("respects %s coordinates when feature names also exist", (role) => {
    const output = projectedOutput("variable_profile", [0.4, 1.2, 0.9]) as any;
    Object.assign(output.metadata, {
      data_role: role, wavenumbers: [600, 1000, 1400],
      feature_names: ["band-a", "band-b", "band-c"], x_units: "cm-1",
    });
    const plot = useQuickPlotProjection(ref(output), ref("model.fitted_pls"));
    expect(plot.plotData.value[0].x).toEqual(role === "X_spectra"
      ? [600, 1000, 1400] : ["band-a", "band-b", "band-c"]);
  });

  it("inherits feature labels from the producing input when a variable profile omits them", () => {
    const output = projectedOutput("variable_profile", [0.4, 1.2, 0.9]) as any;
    output.metadata.feature_names = [];
    const nodeOutput = ref(output);
    const nodeInputs = ref({
      y: { data: [0, 1, 2], metadata: { feature_names: ["wrong target label"] } },
      X: {
        data: [],
        metadata: {},
        value: {
          data: [[1, 2, 3]],
          metadata: { feature_names: ["sepal length", "sepal width", "petal length"] },
        },
      },
    });
    const plot = useQuickPlotProjection(nodeOutput, ref("classification.plsda"), undefined, nodeInputs);

    expect(plot.plotData.value[0].x).toEqual([
      "sepal length",
      "sepal width",
      "petal length",
    ]);
  });

  it("inherits a reversed spectral axis for an ordered variable profile", () => {
    const output = projectedOutput("variable_profile", [0.4, 1.2, 0.9]) as any;
    const nodeInputs = ref({
      X: {
        value: {
          data: [[1, 2, 3]],
          feature_axis: {
            values: [1200, 1100, 1000],
            title: "Wavenumber",
            units: "cm-1",
            quantity: "wavenumber",
          },
          metadata: {},
        },
      },
    });
    const plot = useQuickPlotProjection(ref(output), ref("model.fitted_pls"), undefined, nodeInputs);

    expect(plot.plotData.value[0].x).toEqual([1200, 1100, 1000]);
    expect(plot.plotLayout.value.xaxis).toMatchObject({
      title: "Wavenumber (cm-1)",
      autorange: "reversed",
    });
  });

  it("uses model-input variable labels when the primary output is a latent score matrix", () => {
    const output = projectedOutput("variable_profile", [0.4, 1.2, 0.9]) as any;
    output.metadata = {
      ...output.metadata,
      feature_names: ["LV1", "LV2"],
      diagnostics: {
        feature_names: ["sepal length", "sepal width", "petal length"],
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("classification.plsda"));

    expect(plot.plotData.value[0].x).toEqual([
      "sepal length",
      "sepal width",
      "petal length",
    ]);
  });

  it.each([
    [
      "scores",
      "pls_scores",
      "x_scores",
      {
        _truncated_matrix: true,
        rows: 60,
        preview: [
          { _truncated_sequence: true, length: 3, preview: [1, 2, 3], last: 3 },
          { _truncated_sequence: true, length: 3, preview: [4, 5, 6], last: 6 },
        ],
      },
    ],
    [
      "loadings",
      "pls_loadings",
      "x_loadings",
      [
        { _truncated_sequence: true, length: 700, preview: [0.1, 0.2], last: 0.3 },
        { _truncated_sequence: true, length: 700, preview: [0.4, 0.5], last: 0.6 },
      ],
    ],
    [
      "vip",
      "variable_profile",
      "vip_scores",
      { _truncated_sequence: true, length: 700, preview: [0.8, 1.2, 0.9], last: 0.7 },
    ],
    [
      "coefficients",
      "regression_coefficients",
      "regression_coefficients",
      {
        _truncated_matrix: true,
        rows: 700,
        preview: [
          { _truncated_sequence: true, length: 1, preview: [0.1], last: 0.1 },
          { _truncated_sequence: true, length: 1, preview: [0.2], last: 0.2 },
        ],
      },
    ],
  ])(
    "renders a non-empty persisted %s preview through the complete presentation path",
    (presentationId, kind, sourcePort, compactedValue) => {
      const presentationContract = {
        digest: "a".repeat(64),
        payload: {
          schema_version: "spectrasherpa-node-presentation/1" as const,
          default_presentation: presentationId as string,
          presentations: [
            {
              presentation_id: presentationId as string,
              label: presentationId as string,
              kind: kind as string,
              source_ports: [sourcePort as string],
              modes: ["plot", "table"],
              description: "Persisted PLS result.",
            },
          ],
        },
      };
      const output = buildNodeOutput(
        { [sourcePort as string]: compactedValue },
        [{ name: sourcePort as string }] as NodePortMetadata[],
        null,
        null,
        presentationContract,
      );
      const projected = projectScientificPresentation(
        output,
        resolveScientificPresentation(
          { presentation_contract: presentationContract } as NodeTypeMetadata,
          output,
          presentationId as string,
        ),
      );
      const plot = useQuickPlotProjection(ref(projected as any), ref("model.fitted_pls"));

      expect(projected?.data.length).toBeGreaterThan(0);
      expect(projected?.metadata.persisted_preview).toBe(true);
      expect(plot.availablePlots.value).toHaveLength(1);
      expect(plot.plotData.value.length).toBeGreaterThan(0);
    },
  );

  it("uses the typed scientific descriptor rather than Plotly trace-array shape", () => {
    const traces = [
      { name: "Reference", x: [1, 2], y: [1, 2] },
      { name: "Predicted", x: [1, 2], y: [0.9, 2.1] },
    ];
    const nodeOutput = ref(
      projectedOutput("visualization", traces, traces, {
        shape: [20, 2],
        shape_valid: true,
        dimensions: [
          { role: "observation", size: 20 },
          { role: "comparison_field", size: 2 },
        ],
      }) as any,
    );
    const plot = useQuickPlotProjection(nodeOutput, ref("output.plot"));

    expect(plot.dataShape.value).toMatchObject({
      rows: 20,
      cols: 2,
      rowLabel: "observations",
      colLabel: "comparison fields",
    });
  });

  it("reports Peak Detection evidence as spectra and detections", () => {
    const output = projectedOutput("visualization", [], {
      peak_finding: {
        data: [{ type: "scatter", x: [1, 2], y: [3, 4] }],
        layout: {},
      },
    }) as any;
    output.metadata = {
      ...output.metadata,
      diagnostics: { n_samples: 50, n_peaks: 61 },
      scientific_presentation: {
        ...output.metadata.scientific_presentation,
        presentation_id: "peak_overlay",
        label: "Spectra with Peaks",
      },
    };

    const plot = useQuickPlotProjection(ref(output), ref("analysis.peak_finding"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_visualization:peak_finding", label: "Spectra with Peaks" },
    ]);
    expect(plot.dataShape.value).toEqual({
      rows: 50,
      cols: 61,
      range: null,
      rowLabel: "spectra",
      colLabel: "peak detections",
    });
  });

  it("reports grouped Plotly scores as series and total observations", () => {
    const traces = [
      { name: "Lavandula angustifolia", x: [1, 2], y: [3, 4] },
      { name: "Lavandula x intermedia", x: [5], y: [6] },
      { name: "Lavandula latifolia", x: [7, 8, 9], y: [10, 11, 12] },
    ];
    const plot = useQuickPlotProjection(
      ref(projectedOutput("visualization", traces, traces) as any),
      ref("output.plot"),
    );

    expect(plot.dataShape.value).toMatchObject({
      rows: 3,
      cols: 6,
      rowLabel: "series",
      colLabel: "points",
    });
  });

  it("counts a shared loading coordinate once across component series", () => {
    const axis = [4000, 2000, 500];
    const traces = [
      { name: "PC1", x: axis, y: [0.1, 0.2, 0.3] },
      { name: "PC2", x: axis, y: [0.3, 0.2, 0.1] },
    ];
    const plot = useQuickPlotProjection(
      ref(projectedOutput("visualization", traces, traces) as any),
      ref("output.plot"),
    );

    expect(plot.dataShape.value).toMatchObject({
      rows: 2,
      cols: 3,
      rowLabel: "series",
      colLabel: "points",
    });
  });

  it("reverses a PCA loading axis from spectral semantics even when its role is X_features", () => {
    const axis = [500, 2000, 4000];
    const nodeOutput = ref({
      data: [
        [-1, 0],
        [1, 0],
      ],
      metadata: { type: "PCA", isPCA: true, pc_labels: ["PC1", "PC2"] },
      ports: {
        loadings: {
          data: [
            [0.1, 0.2, 0.3],
            [0.3, 0.2, 0.1],
          ],
          value: {
            data: [
              [0.1, 0.2, 0.3],
              [0.3, 0.2, 0.1],
            ],
            data_role: "X_features",
            x_axis: {
              data: axis,
              title: "Wavenumber",
              units: "cm-1",
              quantity: "wavenumber",
              axis_type: "wavenumber",
            },
          },
        },
      },
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.pca"));

    plot.selectedPlotKey.value = "pca_loadings";

    expect(plot.plotData.value[0].x).toEqual(axis);
    expect(plot.plotData.value[0].type).toBe("scatter");
    expect(plot.plotLayout.value.xaxis.autorange).toBe("reversed");
  });

  it("does not use node-name or shape heuristics for an unprojected contracted output", () => {
    const nodeOutput = ref({
      data: [
        [1, 2],
        [3, 4],
      ],
      metadata: {},
      presentation_contract: {
        digest: "a".repeat(64),
        payload: {
          schema_version: "spectrasherpa-node-presentation/1",
          default_presentation: "scores",
          presentations: [],
        },
      },
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.pca"));

    expect(plot.availablePlots.value).toEqual([]);
    expect(plot.plotData.value).toEqual([]);
  });

  it("presents a feature-table dataset as labeled class distributions", () => {
    const output = projectedOutput("spectral_dataset", [
      [5.1, 3.5],
      [7.0, 3.2],
      [6.3, 3.3],
    ]) as any;
    output.metadata = {
      ...output.metadata,
      data_role: "X_features",
      diagnostics: {
        feature_names: ["sepal length", "sepal width"],
        sample_classes: ["setosa", "versicolor", "virginica"],
      },
    };
    const plot = useQuickPlotProjection(ref(output), ref("data.file_load"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_spectral_overlay", label: "Feature Distributions" },
      { key: "scientific_spectral_heatmap", label: "Feature Heatmap" },
    ]);
    expect(plot.plotData.value.slice(0, 2).map((trace: any) => trace.name)).toEqual([
      "sepal length",
      "sepal width",
    ]);
    expect(plot.dataShape.value).toMatchObject({ rows: 3, cols: 2, rowLabel: "samples", colLabel: "features" });
    expect(plot.plotData.value.slice(2).map((trace: any) => trace.name)).toEqual([
      "setosa",
      "versicolor",
      "virginica",
    ]);
    expect(plot.plotLayout.value.yaxis.title).toBe("Value");
  });

  it("plots component factors with distinct concentration and spectral semantics", async () => {
    const output = projectedOutput("spectral_dataset", [
      [0.8, 0.2, 0.0],
      [0.4, 0.3, 0.3],
      [0.1, 0.2, 0.7],
    ]) as any;
    output.presentation_value = {
      data: output.data,
      units: "relative concentration",
      data_role: "X_features",
      x_axis: { data: [0, 1, 2], labels: ["Component 1", "Component 2", "Component 3"], title: "Component" },
      y_axis: { data: [0, 1, 2], labels: ["Mix A", "Mix B", "Mix C"], title: "Sample" },
    };
    output.metadata = {
      ...output.metadata,
      data_role: "X_features",
      scientific_matrix_role: "component_concentrations",
      feature_names: ["Component 1", "Component 2", "Component 3"],
      sample_labels: ["Mix A", "Mix B", "Mix C"],
      x_title: "Component",
      y_title: "Sample",
      x_units: "cm-1",
      value_units: "relative concentration",
    };
    output.descriptor = {
      shape_valid: true,
      shape: [50, 3],
      dimensions: [
        { role: "sample", size: 50 },
        { role: "component", size: 3 },
      ],
    };
    output.metadata.scientific_presentation.source_port = "concentrations";
    const nodeOutput = ref(output);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.nmf"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_spectral_overlay", label: "Concentration Profiles" },
      { key: "scientific_spectral_heatmap", label: "Concentration Heatmap" },
    ]);
    expect(plot.plotData.value).toHaveLength(3);
    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual([
      "Component 1",
      "Component 2",
      "Component 3",
    ]);
    expect(plot.plotData.value[0]).toMatchObject({
      x: [0, 1, 2],
      y: [0.8, 0.4, 0.1],
      customdata: ["Mix A", "Mix B", "Mix C"],
    });
    expect(plot.plotLayout.value.xaxis.title).toBe("Sample");
    expect(plot.plotLayout.value.yaxis.title).toBe("relative concentration");
    expect(plot.dataShape.value).toMatchObject({
      rows: 50,
      cols: 3,
      rowLabel: "samples",
      colLabel: "components",
    });

    plot.selectedPlotKey.value = "scientific_spectral_heatmap";
    expect(plot.plotData.value).toHaveLength(1);
    expect(plot.plotData.value[0]).toMatchObject({
      type: "heatmap",
      x: ["Component 1", "Component 2", "Component 3"],
      y: ["Mix A", "Mix B", "Mix C"],
      z: output.data,
      colorbar: { title: "relative concentration" },
    });
    expect(plot.plotLayout.value.xaxis.title).toEqual({ text: "Component", standoff: 20 });
    expect(plot.plotLayout.value.yaxis.title).toBe("Sample");
    expect(plot.plotLayout.value.margin.l).toBe(160);
    expect(plot.plotLayout.value.margin.b).toBe(100);
    expect(plot.plotLayout.value.xaxis.automargin).toBe(true);

    const spectra = projectedOutput("spectral_dataset", [
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6],
      [0.7, 0.8, 0.9],
    ]) as any;
    spectra.presentation_value = {
      data: spectra.data,
      units: "absorbance",
      data_role: "X_spectra",
      x_axis: { data: [1200, 1100, 1000], title: "Wavenumber", units: "cm-1" },
      y_axis: {
        data: [0, 1, 2],
        labels: ["Basis Spectrum 1", "Basis Spectrum 2", "Basis Spectrum 3"],
        title: "Component",
      },
    };
    spectra.metadata = {
      ...spectra.metadata,
      data_role: "X_spectra",
      scientific_matrix_role: "component_spectra",
      labels: ["Basis Spectrum 1", "Basis Spectrum 2", "Basis Spectrum 3"],
      wavenumbers: [1200, 1100, 1000],
      x_title: "Wavenumber",
      x_units: "cm-1",
      y_title: "Component",
      value_units: "absorbance",
    };
    spectra.descriptor = {
      shape_valid: true,
      shape: [3, 5401],
      dimensions: [
        { role: "component", size: 3 },
        { role: "spectral_variable", size: 5401 },
      ],
    };
    spectra.metadata.scientific_presentation.source_port = "pure_spectra";
    nodeOutput.value = spectra;
    await nextTick();

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_spectral_overlay", label: "Pure Spectra" },
      { key: "scientific_spectral_heatmap", label: "Pure Spectra Heatmap" },
    ]);
    expect(plot.selectedPlotKey.value).toBe("scientific_spectral_overlay");
    expect(plot.plotData.value).toHaveLength(3);
    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual([
      "Basis Spectrum 1",
      "Basis Spectrum 2",
      "Basis Spectrum 3",
    ]);
    expect(plot.plotLayout.value.yaxis.title).toBe("Absorbance");
    expect(plot.dataShape.value).toMatchObject({
      rows: 3,
      cols: 5401,
      rowLabel: "components",
      colLabel: "spectral variables",
    });

    plot.selectedPlotKey.value = "scientific_spectral_heatmap";
    expect(plot.plotData.value[0].y).toEqual([
      "Basis Spectrum 1",
      "Basis Spectrum 2",
      "Basis Spectrum 3",
    ]);
    expect(plot.plotLayout.value.xaxis.title).toBe("Wavenumber (cm-1)");
    expect(plot.plotLayout.value.yaxis.title).toBe("Component");
    expect(plot.plotLayout.value.margin.l).toBe(160);
    expect(plot.plotData.value[0].colorbar.title.text).toBe("Absorbance");
  });

  it("uses a named X input for preprocessing before/after previews", () => {
    const output = {
      data: [[10, 20, 30], [40, 50, 60]],
      metadata: { is_spectra: true, wavenumbers: [100, 200, 300], x_title: "Wavenumber" },
    };
    const input = {
      data: [[1, 2, 3], [4, 5, 6]],
      metadata: { is_spectra: true, wavenumbers: [100, 200, 300], x_title: "Wavenumber" },
    };
    const plot = useQuickPlotProjection(
      ref(output),
      ref("preprocess.scale"),
      undefined,
      ref({ X: input }),
    );

    expect(plot.availablePlots.value[0]).toEqual({ key: "spectra_overlay", label: "Data Overlay" });
    expect(plot.plotData.value).toHaveLength(4);
    expect(plot.plotLayout.value.xaxis.matches).toBeUndefined();
    expect(plot.plotLayout.value.xaxis2.matches).toBeUndefined();
  });
});
