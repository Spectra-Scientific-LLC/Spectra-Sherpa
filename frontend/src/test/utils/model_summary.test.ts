import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import ModelSummaryCard from "@/components/ModelSummaryCard.vue";
import { buildModelSummary, preprocessingChain, summarySources, type SavedDefinition } from "@/utils/modelSummary";

// Shapes captured from the shipped PLS and PLS-DA starters on synthetic data.
const plsDefinition: SavedDefinition = {
  nodes: [
    { node_id: "data_1", node_type: "data.file_load", parameters: {} },
    { node_id: "snv_1", node_type: "preprocess.normalize", label: "SNV", parameters: {} },
    { node_id: "sg_1", node_type: "preprocess.derivative", label: "Savitzky-Golay 1st derivative", parameters: {} },
    { node_id: "partition_1", node_type: "data.train_test_split", parameters: {} },
    { node_id: "model_1", node_type: "model.fitted_pls", label: "Train PLS Regression", parameters: { n_components: 5, scale: true } },
    { node_id: "predict_1", node_type: "model.predict_regression", parameters: {} },
    { node_id: "eval_1", node_type: "diagnostics.labeled_regression_evaluator", parameters: {} },
  ],
  edges: [
    { from_node_id: "data_1", from_output: "default", to_node_id: "snv_1", to_input: "default" },
    { from_node_id: "snv_1", from_output: "default", to_node_id: "sg_1", to_input: "default" },
    { from_node_id: "sg_1", from_output: "default", to_node_id: "partition_1", to_input: "X" },
    { from_node_id: "partition_1", from_output: "X_train", to_node_id: "model_1", to_input: "default" },
    { from_node_id: "model_1", from_output: "fitted_state", to_node_id: "predict_1", to_input: "fitted_state" },
    { from_node_id: "predict_1", from_output: "default", to_node_id: "eval_1", to_input: "default" },
  ],
};
const contracts = {
  model_1: { contract: { presentations: [
    { presentation_id: "calibration_fit", kind: "regression_comparison", source_ports: ["calibration_comparison"] },
    { presentation_id: "scores", kind: "pls_scores", source_ports: ["x_scores"] },
  ] } },
  eval_1: { contract: { presentations: [
    { presentation_id: "held_out_comparison", kind: "regression_comparison", source_ports: ["comparison"] },
    { presentation_id: "metrics", kind: "metric_record", source_ports: ["default"] },
  ] } },
};
const comparison = (role: string, target: string, metrics: Record<string, number>) => ({
  schema_version: "spectrasherpa-regression-comparison/1", data: [], metadata: { role },
  statistics: { schema_version: "spectrasherpa-regression-statistics/1", targets: [{ target, metrics }] },
});
const calibration = comparison("calibration", "Target 1", { n_samples: 30, rmse: 0.2894209886803024, r2: 0.9999035761513079, bias: 1.16e-14, sep: 0.2943687144089471, slope: 0.9999 });
const test = comparison("held_out_test", "Moisture", { n_samples: 10, rmse: 0.3974920466885316, r2: 0.9991506638934449, bias: -0.1411081585168226, sep: 0.39170342349598725, slope: 0.9897439737800676 });

describe("model summary from retained records", () => {
  it.each([null, "%"])("preserves declared target units %s and shows the recorded holdout protocol", (units) => {
    const value = { ...test, metadata: { role: "held_out_test", target_units: [units] } };
    const summary = buildModelSummary(plsDefinition, {}, [{
      source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value,
    }]);
    expect(summary.regression[0].target_units).toBe(units);
    const wrapper = mount(ModelSummaryCard, { props: { summary } });
    expect(wrapper.text()).toContain(`RMSEP (${units ?? "units not declared"})`);
    expect(wrapper.text()).toContain("Protocol: Held-out test");
    expect(wrapper.text()).not.toContain("Protocol: Cross-validation");
  });
  it("reads only model and evaluator comparison and metric records", () => {
    const sources = summarySources(plsDefinition, contracts, "model_1");
    expect(sources.map((item) => `${item.nodeId}/${item.port}`)).toEqual([
      "model_1/component_curve", "model_1/calibration_comparison", "eval_1/comparison", "eval_1/default",
    ]);
  });

  it("orders pretreatment from the data toward the model", () => {
    expect(preprocessingChain(plsDefinition, "model_1")).toEqual(["SNV", "Savitzky-Golay 1st derivative"]);
  });

  it("keeps each statistic's recorded population and prefers effective parameters", () => {
    const summary = buildModelSummary(plsDefinition, { model_1: { n_components: 3, scale: false } }, [
      { source: { nodeId: "model_1", port: "calibration_comparison", kind: "regression_comparison" }, value: calibration },
      { source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value: test },
      { source: { nodeId: "eval_1", port: "default", kind: "metric_record" }, value: { task_type: "regression", rmse: 0.4 } },
    ]);
    expect(summary.model).toMatchObject({ method: "PLS regression", settings: [["Components", "3 latent variables"], ["X scaling", "Mean-centred"]] });
    expect(summary.regression.map((item) => [item.role, item.n, item.rmse])).toEqual([
      ["calibration", 30, 0.2894209886803024], ["held_out_test", 10, 0.3974920466885316],
    ]);
  });

  it("refuses a comparison without a recorded population rather than guessing one", () => {
    const unlabelled = { ...test, metadata: {} };
    const summary = buildModelSummary(plsDefinition, null, [
      { source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value: unlabelled },
    ]);
    expect(summary.regression).toEqual([]);
  });

  it("uses the exact retained component curve, its executed split and its unavailable reason", () => {
    const base = {
      schema_version: "spectrasherpa-pls-component-curve/1", selected_components: 2, selected_in_curve: true,
      n_calibration: 12, response_names: ["Moisture"], response_units: ["%"], scaling: "fold_fitted_autoscale",
      calibration: [
        { components: 1, rmsec: [0.8], r2x_cumulative: 0.4, r2y_cumulative: [0.7] },
        { components: 2, rmsec: [0.5], r2x_cumulative: 0.6, r2y_cumulative: [0.9] },
      ],
    };
    const source = { nodeId: "model_1", port: "component_curve", kind: "component_selection" };
    const available = buildModelSummary(plsDefinition, null, [{ source, value: { ...base, cross_validation: {
      status: "available", method: "group_kfold", n_folds: 3, n_groups: 4, split_digest: "abc123",
      rows: [{ components: 1, rmsecv: [1.0], q2: [0.6] }, { components: 2, rmsecv: [0.7], q2: [0.8] }],
      suggestions: [{ minimum_mean_fold_rmse: 2, one_standard_error: 1 }],
    } } }]);
    expect(available.componentSelection?.responses[0].rows[1]).toMatchObject({ rmsec: 0.5, rmsecv: 0.7, r2x: 0.6, q2: 0.8 });
    const card = mount(ModelSummaryCard, { props: { summary: available } });
    expect(card.get('[aria-label="PLS component selection"]').text()).toMatch(/3-fold group kfold\s+across 4 independent groups/);
    expect(card.text()).toContain("one-standard-error suggestion: 1 LV");
    expect(card.findAll(".model-summary__selected-row")).toHaveLength(1);
    const unavailable = buildModelSummary(plsDefinition, null, [{ source, value: { ...base, cross_validation: {
      status: "unavailable", reason: "Upstream scaling was not replayed inside each fold."
    } } }]);
    expect(mount(ModelSummaryCard, { props: { summary: unavailable } }).text()).toContain("Cross-validation unavailable: Upstream scaling");
  });

  it("uses a matching retained PLS response unit when a comparison omitted its unit", () => {
    const comparisonWithoutUnit = { ...test, metadata: { role: "held_out_test", target_units: [null] } };
    const curve = { schema_version: "spectrasherpa-pls-component-curve/1", selected_components: 1,
      n_calibration: 12, response_names: ["Moisture"], response_units: ["%"],
      calibration: [{ components: 1, rmsec: [0.2] }],
      cross_validation: { status: "unavailable", reason: "Not retained" } };
    const summary = buildModelSummary(plsDefinition, null, [
      { source: { nodeId: "model_1", port: "component_curve", kind: "component_selection" }, value: curve },
      { source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value: comparisonWithoutUnit },
    ]);
    expect(summary.regression[0].target_units).toBe("%");
  });

  it("keeps PCA reconstruction distinct from regression validation", () => {
    const definition: SavedDefinition = { nodes: [{ node_id: "pca", node_type: "model.pca", parameters: { n_components: "2" } }], edges: [] };
    expect(summarySources(definition, null, "pca")).toEqual([{ nodeId: "pca", port: "component_curve", kind: "component_selection" }]);
    const summary = buildModelSummary(definition, null, [{ source: { nodeId: "pca", port: "component_curve", kind: "component_selection" }, value: {
      schema_version: "spectrasherpa-pca-component-curve/1", selected_components: 2, n_calibration: 24,
      reconstruction_space: "mean_centered_X",
      calibration: [{ components: 1, explained_x_incremental: 0.6, explained_x_cumulative: 0.6, reconstruction_rmse: 0.4 }],
      cross_validation: { status: "available", method: "group_kfold", n_folds: 4,
        rows: [{ components: 1, pooled_reconstruction_rmse: 0.5 }] },
    } }]);
    expect(summary.regression).toEqual([]);
    const text = mount(ModelSummaryCard, { props: { summary } }).text();
    expect(text).toContain("Principal components");
    expect(text).toContain("CV reconstruction RMSE");
    expect(mount(ModelSummaryCard, { props: { summary } }).find('a[href$="#component-selection"]').exists()).toBe(true);
  });

  it("shows PLS-DA class performance by LV without calling it RMSECV", () => {
    const definition: SavedDefinition = { nodes: [{ node_id: "da", node_type: "classification.plsda", parameters: { n_components: 2 } }], edges: [] };
    expect(summarySources(definition, null, "da")).toEqual([{ nodeId: "da", port: "component_curve", kind: "component_selection" }]);
    const summary = buildModelSummary(definition, null, [{ source: { nodeId: "da", port: "component_curve", kind: "component_selection" }, value: {
      schema_version: "spectrasherpa-plsda-component-curve/1", selected_components: 2, n_calibration: 30,
      classes: ["A", "B"],
      calibration: [{ components: 1, balanced_accuracy: 0.83 }, { components: 2, balanced_accuracy: 0.9 }],
      cross_validation: { status: "available", method: "stratified_group_kfold", n_folds: 3,
        rows: [{ components: 1, balanced_accuracy: 0.7, accuracy: 0.73, f1_macro: 0.71 },
          { components: 2, balanced_accuracy: 0.8, accuracy: 0.83, f1_macro: 0.81 }],
        suggestion: { maximum_balanced_accuracy: 2 } },
    } }]);
    const text = mount(ModelSummaryCard, { props: { summary } }).get('[aria-label="PLS-DA component selection"]').text();
    expect(text).toContain("CV balanced accuracy");
    expect(text).toContain("80%");
    expect(text).toContain("suggests 2 LV");
    expect(text).not.toContain("RMSECV");
  });

  it("does not rank classification components from calibration accuracy when CV is unavailable", () => {
    const definition: SavedDefinition = { nodes: [{ node_id: "da", node_type: "classification.plsda", parameters: { n_components: 3 } }], edges: [] };
    const summary = buildModelSummary(definition, null, [{ source: { nodeId: "da", port: "component_curve", kind: "component_selection" }, value: {
      schema_version: "spectrasherpa-plsda-component-curve/1", selected_components: 3, n_calibration: 9,
      classes: ["A", "B", "C"], calibration: [
        { components: 1, balanced_accuracy: 0.67 }, { components: 2, balanced_accuracy: 0.89 }, { components: 3, balanced_accuracy: 1 },
      ], cross_validation: { status: "unavailable", reason: "Classification CV is unavailable: every classification class must contain at least n_splits samples" },
    } }]);
    const card = mount(ModelSummaryCard, { props: { summary } }).get('[aria-label="PLS-DA component selection"]');
    expect(card.text()).toContain('Cross-validation needs at least one independent specimen from each class');
    expect(card.text()).toContain('Calibration fit cannot rank component choices');
    expect(card.text()).not.toContain('n_splits');
    expect(card.text()).not.toContain('100%');
    expect(card.find('table').exists()).toBe(false);
  });

  it("reads classification calibration and test statistics with their confusion matrices", () => {
    const definition: SavedDefinition = {
      nodes: [
        { node_id: "model_1", node_type: "classification.plsda", parameters: { n_components: 2, scale: false } },
        { node_id: "eval_1", node_type: "diagnostics.classification_evaluator", parameters: {} },
      ], edges: [],
    };
    const summary = buildModelSummary(definition, null, [
      { source: { nodeId: "model_1", port: "metrics", kind: "statistics_summary" }, value: {
        task_type: "classification", classes: ["A", "B"], splits: { train: { accuracy: 1, balanced_accuracy: 1 } },
        confusion_matrices: { train: [[15, 0], [0, 15]] } } },
      { source: { nodeId: "eval_1", port: "default", kind: "metric_record" }, value: {
        task_type: "classification", n_samples: 10, accuracy: 0.9, balanced_accuracy: 0.9, labels: ["A", "B"],
        confusion_matrix: [[5, 0], [1, 4]], population_authority: { role: "held_out_test" } } },
    ]);
    expect(summary.model?.method).toBe("PLS-DA");
    expect(summary.classification.map((item) => [item.role, item.n, item.accuracy])).toEqual([
      ["calibration", 30, 1], ["held_out_test", 10, 0.9],
    ]);
  });
});

describe("model summary card", () => {
  it("shows calibration and test statistics side by side under their chemometric names", () => {
    const summary = buildModelSummary(plsDefinition, null, [
      { source: { nodeId: "model_1", port: "calibration_comparison", kind: "regression_comparison" }, value: calibration },
      { source: { nodeId: "eval_1", port: "comparison", kind: "regression_comparison" }, value: test },
    ]);
    const wrapper = mount(ModelSummaryCard, { props: { summary } });
    const text = wrapper.text();
    expect(text).toContain("PLS regression");
    expect(text).toContain("5 latent variables");
    expect(text).toContain("Autoscaled");
    expect(text).toContain("SNV → Savitzky-Golay 1st derivative");
    expect(wrapper.findAll("thead th").map((cell) => cell.text())).toEqual(["Statistic", "Protocol: Calibration fit", "Protocol: Held-out test"]);
    expect(text).toContain("RMSEC (units not declared) 0.2894");
    expect(text).toContain("RMSEP (units not declared) 0.3975");
    expect(text).toContain("30 calibration fit");
    expect(text).not.toContain("Only calibration-fit statistics");
  });

  it("says so when a run has no validation statistics", () => {
    const summary = buildModelSummary(plsDefinition, null, [
      { source: { nodeId: "model_1", port: "calibration_comparison", kind: "regression_comparison" }, value: calibration },
    ]);
    expect(mount(ModelSummaryCard, { props: { summary } }).get('[role="note"]').text()).toContain("no retained CV or test predictions");
  });

  it("shows the most independent confusion matrix and marks misclassifications", () => {
    const summary = buildModelSummary({ nodes: [{ node_id: "m", node_type: "classification.plsda", parameters: {} }], edges: [] }, null, [
      { source: { nodeId: "e", port: "default", kind: "metric_record" }, value: {
        task_type: "classification", n_samples: 10, accuracy: 0.9, balanced_accuracy: 0.9, labels: ["A", "B"],
        confusion_matrix: [[5, 0], [1, 4]], population_authority: { role: "held_out_test" } } },
    ]);
    const wrapper = mount(ModelSummaryCard, { props: { summary } });
    expect(wrapper.text()).toContain("Accuracy");
    expect(wrapper.text()).toContain("90%");
    expect(wrapper.get("figcaption").text()).toContain("test set");
    expect(wrapper.findAll("td.off").map((cell) => cell.text())).toEqual(["1"]);
  });

  it("renders nothing for a run without a model or statistics", () => {
    const summary = buildModelSummary({ nodes: [{ node_id: "d", node_type: "data.file_load", parameters: {} }], edges: [] }, null, []);
    expect(mount(ModelSummaryCard, { props: { summary } }).find("section").exists()).toBe(false);
  });
});
