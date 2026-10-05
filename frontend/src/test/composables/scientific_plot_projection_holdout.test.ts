/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it } from "vitest";
import { ref } from "vue";

import { useQuickPlotProjection } from "@/composables/useScientificPlotProjection";

describe("canonical scientific projection evaluator metrics", () => {
  it("does not offer orphan metrics plots when only the metrics payload is selected", () => {
    const nodeOutput = ref({
      data: [
        { class: "malignant", sensitivity: 0.91, specificity: 0.96, precision: 0.93, f1: 0.92 },
        { class: "benign", sensitivity: 0.96, specificity: 0.91, precision: 0.95, f1: 0.95 },
      ],
      metadata: {
        type: "ClassificationTest",
        n_classes: 2,
        n_samples: 114,
      },
      test_accuracy: 0.9474,
      test_balanced_accuracy: 0.935,
      n_classes: 2,
      n_samples: 114,
      task_type: "classification",
    } as any);
    const nodeType = ref("diagnostics.classification_evaluator");

    const plot = useQuickPlotProjection(nodeOutput, nodeType);

    expect(plot.availablePlots.value).toEqual([]);
    expect(plot.plotData.value).toEqual([]);
  });

  it("uses the canonical classification visualization port as the quick plot", () => {
    const metrics = {
      data: [
        { class: "class_0", sensitivity: 0.9, specificity: 0.95, precision: 0.92, f1: 0.91 },
        { class: "class_1", sensitivity: 0.95, specificity: 0.9, precision: 0.94, f1: 0.945 },
      ],
      metadata: {
        type: "ClassificationTest",
        n_classes: 2,
        n_samples: 40,
      },
      test_accuracy: 0.925,
      test_balanced_accuracy: 0.925,
      test_f1_macro: 0.9275,
      test_precision_macro: 0.93,
      test_recall_macro: 0.925,
      test_sensitivity_macro: 0.925,
      test_specificity_macro: 0.925,
      n_classes: 2,
      labels: ["class_0", "class_1"],
      n_samples: 40,
      task_type: "classification",
    };
    const visualization = {
      data: [
        [18, 2],
        [1, 19],
      ],
      type: "confusion_matrix",
      metadata: {
        type: "ClassificationTest",
        labels: ["class_0", "class_1"],
      },
    };
    const nodeOutput = ref({
      data: metrics.data,
      metadata: metrics.metadata,
      ports: {
        metrics: {
          data: metrics.data,
          metadata: metrics.metadata,
          value: metrics,
          type: "object",
        },
        visualization: {
          data: visualization.data,
          metadata: visualization.metadata,
          value: visualization,
          type: "object",
        },
        predictions: {
          data: ["class_0", "class_1", "class_1", "class_0"],
          metadata: {},
          value: ["class_0", "class_1", "class_1", "class_0"],
          type: "array",
        },
      },
      primary_port: "metrics",
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("diagnostics.classification_evaluator"));

    expect(plot.availablePlots.value).toEqual([
      { key: "holdout_confusion", label: "Evaluation Results" },
    ]);
    expect(plot.plotData.value).toHaveLength(1);
    expect(plot.plotData.value[0].type).toBe("heatmap");
  });

  it("plots canonical regression predictions and direct evaluator metrics", () => {
    const visualization = {
      type: "predicted_vs_actual",
      data: [[4, 3.9], [5, 5.2]],
      metadata: {
        task_type: "regression",
        r2: 0.94,
        rmse: 0.2,
      },
    };
    const nodeOutput = ref({
      data: [
        { R2_test: 0.94, RMSE_test: 0.2, R2_train: 0.99, RMSE_train: 0.05 },
      ],
      metadata: { type: "RegressionTest" },
      ports: {
        visualization: {
          data: visualization.data,
          metadata: visualization.metadata,
          value: visualization,
          type: "object",
        },
      },
      primary_port: "visualization",
    } as any);

    const plot = useQuickPlotProjection(nodeOutput, ref("diagnostics.regression_evaluator"));

    expect(plot.availablePlots.value).toEqual([
      { key: "holdout_regression", label: "Evaluation Results" },
    ]);
    expect(plot.plotData.value.map((trace: any) => trace.name)).toEqual(["Test", "1:1 Line"]);
    expect(plot.plotLayout.value.title.text).toContain("Test R²=0.940");
  });

  it("keeps PLS-DA quick plot options aligned with detailed view sections", () => {
    const nodeOutput = ref({
      data: [
        [0.1, 0.2],
        [0.3, 0.4],
      ],
      metadata: {
        type: "PLS_DA",
        n_components: 2,
        vip_scores: [2.0, 1.0],
        y_true: ["A", "B", "A"],
        y_pred_cv: ["A", "B", "B"],
        label_categories: ["A", "B"],
      },
      plots: {
        scores: { data: [{ type: "scatter", x: [0], y: [0] }], layout: {} },
        loadings_lines: { data: [{ type: "scatter", x: [0], y: [0] }], layout: {} },
        loadings_biplot: { data: [{ type: "scatter", x: [0], y: [0] }], layout: {} },
        vip: { data: [{ type: "bar", x: ["x"], y: [1] }], layout: {} },
        confusion_matrix_train: { data: [{ type: "heatmap", z: [[1]] }], layout: {} },
        confusion_matrix_cv: { data: [{ type: "heatmap", z: [[1]] }], layout: {} },
      },
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("classification.plsda"));

    expect(plot.availablePlots.value.map((p) => p.key)).toEqual([
      "plsda_scores",
      "plsda_loadings",
      "plsda_vip",
      "plsda_cm_train",
      "plsda_cm_cv",
      "classification_accuracy",
    ]);
    expect(plot.availablePlots.value.map((p) => p.key)).not.toContain("plsda_loadings_biplot");
    plot.selectedPlotKey.value = "plsda_vip";
    expect(plot.plotData.value).toEqual([
      { type: "bar", x: ["x"], y: [1] },
    ]);
  });

  it("uses the selected fitted-PLS presentation instead of a node-name plot family", () => {
    const comparison = {
      schema_version: "spectrasherpa-regression-comparison/1",
      data: [
        { sample: "1", target: "Target 1", reference: 1, predicted: 1.1, residual: -0.1, role: "calibration" },
        { sample: "2", target: "Target 1", reference: 2, predicted: 1.9, residual: 0.1, role: "calibration" },
        { sample: "3", target: "Target 1", reference: 3, predicted: 3.2, residual: -0.2, role: "calibration" },
      ],
      metadata: { target_names: ["Target 1"], role: "calibration" },
    };
    const nodeOutput = ref({
      data: [[1.1], [1.9], [3.2]],
      metadata: {
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
      presentation_value: comparison,
    } as any);
    const plot = useQuickPlotProjection(nodeOutput, ref("model.fitted_pls"));

    expect(plot.availablePlots.value).toEqual([
      { key: "scientific_regression_comparison", label: "Predicted vs Reference" },
    ]);
    plot.selectedPlotKey.value = "scientific_regression_comparison";
    expect(plot.plotData.value[0]).toMatchObject({ x: [1, 2, 3], y: [1.1, 1.9, 3.2] });
  });
});
