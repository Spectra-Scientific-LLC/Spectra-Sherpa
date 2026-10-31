import { describe, expect, it } from "vitest";
import { keyResultRows, scientificSummaryGroups } from "@/utils/scientificReportSummary";
import { generateProvenanceReport, type ReportData } from "@/utils/reportGenerator";
import { generateMarkdownReport } from "@/utils/reportMarkdownGenerator";

function fixture(): ReportData {
  return {
    reportMode: "summary", workflowName: "Protein PLS", workflowDescription: null,
    generatedAt: "2026-09-30", integrityHash: null, nodes: [], edges: [],
    plotImages: new Map(), terminalMetrics: {},
    runs: [{
      id: 7, name: "Saved PLS", status: "completed", executed_at: null,
      results_summary: { pls: { train: { r2: 0.99876 }, cv: { rmse: 0.123456 },
        per_target: [{ target_name: "protein", units: "mg/L", bias: 0 }],
        per_fold_rmse: [1, 2, 3], coefficients: [987654], arbitrary_detail: "verbose detail" } },
      diagnostics: null, params_snapshot: { pls: { n_components: 3 } },
      node_statuses: {}, integrity_hash: null, labels: [],
      saved_definition: { nodes: [{ node_id: "pls", label: "PLS", node_type: "model.fitted_pls" }] },
      evidence_notice: "Saved evidence only", evidence_gaps: [{ node_id: "pls", output: "scores", state: "missing",
        category: "unavailable", reason: "Scores not retained", recovery: "Rerun to recover" }],
      validation_summary: { schema_version: "spectrasherpa-readable-validation/1", run_id: 7,
        summary_rows: [{ label: "Target (source)", value: "protein (continuous; units: mg/L)" },
          { label: "Evaluation population", value: "Cross-validation; not an external held-out test." }],
        rows: [{ label: "Target (source)", value: "protein (continuous; units: mg/L)" },
          { label: "Evaluation population", value: "Cross-validation; not an external held-out test." },
          { label: "Saved settings (pls)", value: "verbose settings" },
          { label: "Fold 1", value: "verbose fold rows" }] },
    }],
  };
}

// Run692's retained KNN calibration shape: the dataset metadata and extra
// carry a sklearn class report beside core_utils.classification_metrics_contract.
// Only public aggregate values are needed; no sample rows or model state.
function wineClassificationFixture() {
  const train = { accuracy: 0.9925373134328358, balanced_accuracy: 0.9938271604938271,
    f1_macro: 0.9931394168504323, precision_macro: 0.9925925925925926, recall_macro: 0.9938271604938271 };
  const classificationReport = {
    class_0: { precision: 44 / 45, recall: 1, "f1-score": 88 / 89, support: 44 },
    class_1: { precision: 1, recall: 53 / 54, "f1-score": 106 / 107, support: 54 },
    class_2: { precision: 1, recall: 1, "f1-score": 1, support: 36 },
    accuracy: train.accuracy,
    "macro avg": { precision: train.precision_macro, recall: train.recall_macro, "f1-score": train.f1_macro, support: 134 },
    "weighted avg": { precision: 0.9927031509121061, recall: train.accuracy, support: 134 },
  };
  const metrics = { schema_version: 1, task_type: "classification", primary_split: "train",
    evidence_scope: "calibration_fit_diagnostics_not_validation_evidence", classes: ["class_0", "class_1", "class_2"],
    splits: { train } };
  const metadata = { metrics, classification_report: classificationReport, train_accuracy: train.accuracy,
    train_balanced_accuracy: train.balanced_accuracy, train_precision_macro: train.precision_macro,
    train_recall_macro: train.recall_macro, train_f1_macro: train.f1_macro };
  const data = fixture();
  data.workflowName = "Wine KNN";
  const run = data.runs![0];
  run.id = 692;
  run.name = "Wine KNN run692";
  run.evidence_gaps = [];
  run.validation_summary = { schema_version: "spectrasherpa-readable-validation/1", run_id: 692,
    rows: [{ label: "Training samples", value: "134" }, { label: "Test samples", value: "44" }] };
  run.saved_definition = { nodes: [{ node_id: "model_1", node_type: "classification.knn", label: "Train KNN" },
    { node_id: "eval_1", node_type: "diagnostics.classification_evaluator", label: "Held-out evaluation" }] };
  run.params_snapshot = { model_1: { scale: true } };
  run.results_summary = { model_1: { default: { metadata, extra: structuredClone(metadata) }, metrics },
    eval_1: { metrics: { schema_version: "spectrasherpa.classification-evaluation/1",
      accuracy: 41 / 44, macro_precision: 0.9278846153846154, macro_recall: 0.9330065359477123,
      labels: ["class_0", "class_1", "class_2"], confusion_matrix: [[15, 0, 0], [0, 15, 2], [0, 1, 11]] } } };
  run.diagnostics = { model_1: { classification_metrics: metrics } };
  return { data, metadata, metrics, train };
}

it("projects run692 training aggregate aliases once, preserving classes, weighted averages and held-out evidence", () => {
  const { data } = wineClassificationFixture();
  const original = JSON.stringify(data);
  const groups = scientificSummaryGroups(data);
  const rows = groups.flatMap(group => group.rows);
  expect(rows).not.toContainEqual(["classification_report / Accuracy", "0.9925"]);
  expect(rows.some(([label]) => label.startsWith("classification_report / macro avg / ") && label !== "classification_report / macro avg / Class support")).toBe(false);
  for (const label of ["Training Accuracy", "Training Macro precision", "Training Macro recall", "Training Macro F1", "Training Balanced accuracy"]) {
    expect(rows.filter(row => row[0] === label)).toHaveLength(1);
  }
  expect(rows).toContainEqual(["classification_report / class_1 / Recall", "0.9815"]);
  expect(rows).toContainEqual(["classification_report / macro avg / Class support", "134"]);
  expect(rows).toContainEqual(["classification_report / weighted avg / Recall", "0.9925"]);
  expect(rows).toContainEqual(["Accuracy", "0.9318"]);
  expect(groups.some(group => group.table?.rows.some(row => JSON.stringify(row) === JSON.stringify(["class_1", "0", "15", "2"])))).toBe(true);
  for (const generate of [generateProvenanceReport, generateMarkdownReport]) {
    const output = generate(data).replaceAll("\\_", "_");
    expect(output).not.toContain("classification_report / Accuracy");
    expect(output).toContain("class_1");
    expect(output).toContain("Autoscaled");
  }
  expect(JSON.stringify(data)).toBe(original);
  data.reportMode = "detailed";
  for (const generate of [generateProvenanceReport, generateMarkdownReport]) expect(generate(data).replaceAll("\\_", "_")).toContain("classification_report / accuracy");
});

it.each(["missing", "wrong-scope", "owner-scope", "wrong-task", "wrong-version", "wrong-primary", "different-classes", "multiple-populations", "other-producer", "other-output", "missing-metric", "conflicting-value"])(
  "retains classification report aggregates with %s authority even when displayed values coincide", condition => {
    const { data, metadata, metrics } = wineClassificationFixture();
    // Isolate one metadata occurrence, so a different producer/container cannot qualify it.
    data.runs![0].results_summary = { model_1: { default: { metadata } } };
    data.runs![0].diagnostics = null;
    if (condition === "missing" || condition === "other-producer" || condition === "other-output") {
      delete (metadata as Partial<typeof metadata>).metrics;
      if (condition === "other-producer") data.runs![0].results_summary.other = { metrics };
      if (condition === "other-output") data.runs![0].results_summary.model_1.other_output = { metrics };
    } else if (condition === "wrong-scope") metrics.evidence_scope = "held_out_test";
    else if (condition === "owner-scope") Object.assign(metadata, { evidence_scope: "held_out_test" });
    else if (condition === "wrong-task") metrics.task_type = "regression";
    else if (condition === "wrong-version") metrics.schema_version = 2;
    else if (condition === "wrong-primary") metrics.primary_split = "test";
    else if (condition === "different-classes") metrics.classes = ["class_0", "class_1", "unassigned"];
    else if (condition === "multiple-populations") Object.assign(metrics.splits, { test: { ...metrics.splits.train } });
    else if (condition === "missing-metric") delete (metrics.splits.train as Partial<typeof metrics.splits.train>).accuracy;
    else metadata.classification_report.accuracy += 0.00000001; // Still rounds to 0.9925.
    expect(scientificSummaryGroups(data).flatMap(group => group.rows)).toContainEqual(["classification_report / Accuracy", "0.9925"]);
  },
);

it("keeps numerically equal training, weighted and held-out metrics distinct", () => {
  const { data, train } = wineClassificationFixture();
  data.runs![0].results_summary.eval_1.metrics.accuracy = train.accuracy;
  const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
  expect(rows).toContainEqual(["Training Accuracy", "0.9925"]);
  expect(rows).toContainEqual(["Accuracy", "0.9925"]);
  expect(rows).toContainEqual(["classification_report / weighted avg / Recall", "0.9925"]);
  expect(rows).toContainEqual(["Training Balanced accuracy", "0.9938"]);
  expect(rows).toContainEqual(["Training Macro recall", "0.9938"]);
});

it.each(["root", "metadata"])("keeps report aggregates when %s training scalars contradict their canonical copy", location => {
  const { data, metadata } = wineClassificationFixture();
  const model = { default: { metadata }, ...(location === "root" ? { train_accuracy: 0.75, train_precision_macro: 0.8 } : {}) };
  if (location === "metadata") Object.assign(metadata, { train_accuracy: 0.75, train_precision_macro: 0.8 });
  data.runs![0].results_summary = { model_1: model };
  data.runs![0].diagnostics = null;
  const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
  expect(rows).toContainEqual(["Training Accuracy", "0.75"]);
  expect(rows).toContainEqual(["classification_report / Accuracy", "0.9925"]);
  expect(rows).toContainEqual(["Training Macro precision", "0.8"]);
  expect(rows).toContainEqual(["classification_report / macro avg / Precision", "0.9926"]);
});

describe("deterministic short scientific report", () => {
  it("keeps fitted PCR component count beside requested settings and regression metrics", () => {
    const data = fixture();
    const run = data.runs![0];
    run.saved_definition = { nodes: [{ node_id: "pls", label: "PCR", node_type: "model.fitted_pcr" }] };
    run.results_summary = { pls: { n_components: 2 } };
    run.validation_summary!.regression_results = [{ node_id: "pls", source_port: "comparison", target: "protein",
      role: "held_out_test", units: "mg/L", metrics: { n_samples: 30, rmse: 0.5 }, bias_definition: "predicted_minus_reference" }];
    const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
    expect(rows).toContainEqual(["Components (A)", "2"]);
    expect(rows).toContainEqual(["Requested components", "3"]);
  });
  it("omits a declared scree alias only when the retained diagnostic vector agrees", () => {
    const data = fixture();
    const run = data.runs![0];
    run.results_summary = { pls: { explained_variance: [0.7, 0.2] } };
    run.diagnostics = { pls: { explained_variance_ratio: [0.7, 0.2] }, _scientific_presentations: { pls: { contract: {
      presentations: [{ kind: "pca_explained_variance", source_ports: ["explained_variance"] }],
    } } } };
    const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
    expect(rows).toContainEqual(["Explained variance ratio by component[1]", "0.7"]);
    expect(rows).not.toContainEqual(["Explained variance[1]", "0.7"]);
    run.results_summary.pls.explained_variance = [0.6, 0.3];
    expect(scientificSummaryGroups(data).flatMap(group => group.rows)).toContainEqual(["Explained variance[1]", "0.6"]);
  });
  it("uses the exact saved input edge to label a score-summary dimension", () => {
    const data = fixture();
    const run = data.runs![0];
    run.saved_definition = { nodes: [{ node_id: "stats", node_type: "stats.summary", label: "Score summary" }],
      edges: [{ from_node_id: "pca", from_output: "scores", to_node_id: "stats", to_input: "default" }] };
    run.results_summary = { stats: { default: { n_samples: 150, n_features: 2 } } };
    run.params_snapshot = {};
    run.diagnostics = { _scientific_values: { pca: { scores: { shape_valid: true,
      dimensions: [{ role: "sample", size: 150 }, { role: "component", size: 2 }] } } } };
    const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
    expect(rows).toContainEqual(["Components (A)", "2"]);
    expect(rows).not.toContainEqual(["Variables (p)", "2"]);
  });
  it("labels score dimensions from the retained descriptor, not n_features spelling", () => {
    const rows = keyResultRows({ scores: { n_samples: 150, n_features: 2 },
      default: { n_samples: 150, n_features: 2 } }, {
      default: { shape_valid: true, dimensions: [{ role: "sample", size: 150 }, { role: "component", size: 2 }] },
    } as never);
    expect(rows).toContainEqual(["Samples (n)", "150"]);
    expect(rows).toContainEqual(["Components (A)", "2"]);
    expect(rows).not.toContainEqual(["Variables (p)", "2"]);
  });

  it("omits implementation-state and evaluation aliases from the short report only", () => {
    const payload = { n_components: 2, fitted_state: { state: { n_components: 2 } },
      model: { n_components: 2 }, diagnostic_state: { n_components: 2 },
      quality: { evaluations: [{ n_components: 2 }] },
      variable_correlations: { n_samples: 2, n_features: 4 } };
    expect(keyResultRows(payload)).toEqual([["Components (A)", "2"]]);
    const data = fixture();
    data.runs![0].results_summary = { pls: payload };
    data.reportMode = "detailed";
    expect(generateProvenanceReport(data)).toContain("fitted_state");
  });
  it("omits projection metadata and irrelevant CV context from a preparation-only short report", () => {
    const data = fixture();
    const run = data.runs![0];
    run.saved_definition = { nodes: [{ node_id: "snv", label: "SNV", node_type: "preprocess.normalize" }] };
    run.results_summary = { snv: { n_samples: 33, n_features: 1868,
      scientific_projection: { units: "dimensionless", axes: [{ projection: { units: "cm^-1" } }] } } };
    run.validation_summary!.rows = run.validation_summary!.summary_rows = [
      { label: "Spectral axis (X)", value: "Wavenumber; units: cm^-1" },
      { label: "Spectral intensity", value: "dimensionless" },
    ];
    run.params_snapshot = { snv: { method: "snv" } };
    for (const output of [generateProvenanceReport(data), generateMarkdownReport(data)]) {
      expect(output).not.toContain("scientific_projection");
      expect(output).not.toContain("CV configuration");
      expect(output).toContain("dimensionless");
      expect(output).toContain("33");
      expect(output).toContain("1868");
    }
    data.reportMode = "detailed";
    expect(generateProvenanceReport(data)).toContain("scientific_projection");
  });
  it("collapses metric metadata copies while excluding score payload copies", () => {
    const data = fixture();
    data.runs![0].results_summary = { pls: { train_accuracy: 0.95,
      metadata: { train_accuracy: 0.95 }, extra: { train_accuracy: 0.95 },
      X_scores: { metadata: { train_accuracy: 0.95 } } } };
    const rows = scientificSummaryGroups(data).flatMap(group => group.rows);
    expect(rows.filter(row => row[0].includes("Training Accuracy"))).toHaveLength(1);
  });
  it("excludes authority and provenance unit leaves without losing endpoint metrics", () => {
    const parameters = { target_authority: { units: "wt %" }, dataset_package: {
      annotation_table: { fields: Array.from({ length: 4 }, () => ({ units: "wt %" })) },
    } };
    const payload = { default: { r2: 0.98,
      target_context: { target_units: "wt %", selected_authority: { units: "wt %" } },
      provenance: [{ parameters }, { parameters }],
      metadata: { processing_history: [{ parameters }] },
    } };
    expect(keyResultRows(payload)).toEqual([["R²", "0.98"]]);
    const data = fixture();
    data.runs![0].results_summary = { source: payload };
    expect(generateProvenanceReport(data)).not.toContain("annotation_table");
    data.reportMode = "detailed";
    expect(generateProvenanceReport(data)).toContain("annotation_table");
  });
  it("keeps population-specific units when a target has mixed or missing units", () => {
    const data = fixture();
    data.runs![0].validation_summary!.regression_results = ["mg/L", "Not recorded"].map(units => ({
      node_id: "pls", source_port: "comparison", target: "Protein", units, role: "calibration",
      reference_min: 0, reference_max: 1, reference_sd: 0.2, metrics: { n_samples: 10 },
      bias_definition: "predicted_minus_reference",
    }));
    const groups = scientificSummaryGroups(data);
    expect(groups.find(group => group.table)?.table?.headers).toContain("Units");
    expect(groups[0].rows).toContainEqual(["Response (Y): Protein", expect.stringContaining("Units differ or are not recorded")]);
  });
  it("shows saved PLS scaling and avoids a rounded claim of complete explained variance", () => {
    const data = fixture();
    data.runs![0].params_snapshot = { pls: { scale: false } };
    data.runs![0].diagnostics = { pls: { effective_n_components: 1, y_explained_variance: [0.999999] } };
    data.runs![0].results_summary = { pls: { default: { r2: 0.98 }, r2: 0.98 } };
    const groups = scientificSummaryGroups(data);
    const text = JSON.stringify(groups);
    expect(text).toContain("Mean-centred; no variable scaling");
    expect(text).toContain("<100%");
    expect(text).not.toContain("0.8745");
    expect(groups.flatMap(group => group.rows).filter(row => row[0] === "R²")).toHaveLength(1);
  });
  it("explains latent components separately from saved CV settings upfront", () => {
    const data = fixture();
    data.runs![0].diagnostics = { pls: { effective_n_components: 3, requested_n_components: 3,
      x_explained_variance: [0.8745, 0.1202, 0.001991] } };
    data.runs![0].params_snapshot = { pls: { n_components: 3, cv_folds: 4, random_seed: 42 } };
    const context = scientificSummaryGroups(data)[0].rows.map(row => row.join(": ")).join("\n");
    expect(context).toContain("3 fitted; requested 3");
    expect(context).toContain("not CV folds");
    expect(context).toContain("4 folds requested");
    expect(context).toContain("seed 42");
    expect(context).toContain("not fold k");
  });
  it("shows an executed component CV design retained in the run without claiming it is absent", () => {
    const data = fixture();
    data.runs![0].validation_summary!.summary_rows!.push({
      label: "Component CV design (pls)",
      value: "5 folds; grouped by specimen identity; 3 candidate component counts",
    });
    const context = scientificSummaryGroups(data)[0].rows.map(row => row.join(": ")).join("\n");
    expect(context).toContain("5 folds; grouped by specimen identity");
    expect(context).not.toContain("No executed CV fold design is retained");
  });
  it("reports held-out classification CV from the retained design rather than claiming no fold count", () => {
    const data = fixture();
    data.runs![0].validation_summary!.summary_rows!.push({
      label: "Cross-validation design (plsda)", value: "5 executed folds; grouped validation",
    });
    const context = scientificSummaryGroups(data)[0].rows.map(row => row.join(": ")).join("\n");
    expect(context).toContain("5 executed folds; grouped validation");
    expect(context).not.toContain("No executed CV fold design is retained");
  });
  it.each([generateProvenanceReport, generateMarkdownReport])("shows complete opted-in lists and reference means without a 20-row limit", generate => {
    const data = fixture();
    data.runs![0].validation_summary!.regression_results = [{
      node_id: "pls", source_port: "calibration_comparison", target: "Glucose", role: "calibration", units: "wt %",
      reference_min: 0, reference_max: 173, reference_mean: 86.5, reference_sd: 50,
      metrics: { n_samples: 174 }, bias_definition: "predicted_minus_reference",
      observations: Array.from({ length: 174 }, (_, i) => ({ sample: `sample-${i + 1}`, reference: i, predicted: i + 0.1 })),
    }];
    const output = generate(data);
    expect(output).toContain("Reference mean");
    expect(output).toContain("86.5");
    expect(output).toContain("sample-174");
    expect(output).toContain("174 of 174 observations");
  });
  it("never treats sample comparison targets as aggregate result rows", () => {
    const previewRows = keyResultRows({ target: Array.from({ length: 20 }, (_, i) => i),
      target_truncated: true, target_original_rows: 174 });
    // Summary metrics use the full retained population, not the target preview.
    // The complete-list option and detailed report retain row-level scope.
    expect(previewRows).toEqual([]);
    expect(keyResultRows({ comparison: { data: Array.from({ length: 4 }, () => ({ target: "Glucose (wt %)", reference: 1, predicted: 2 })) } })).toEqual([]);
    expect(keyResultRows({ calibration_comparison: { metadata: { n_samples: 20 }, data: [{ target: "Glucose" }] } })).toEqual([]);
  });
  it.each([generateProvenanceReport, generateMarkdownReport])("shows one target heading with separate calibration and evaluation populations", generate => {
    const data = fixture();
    data.runs![0].validation_summary!.regression_results = ["calibration", "held_out_test"].map((role, i) => ({
      node_id: "pls", source_port: i ? "comparison" : "calibration_comparison", target: "Glucose (wt %)",
      units: "wt %", role, reference_min: 0, reference_max: 30, reference_sd: 8,
      unit_context: { state: "recorded" as const, value: "wt %" },
      metrics: { n_samples: i ? 20 : 80, r2: 0.95, rmse: 0.4321, bias: 0, sep: 0.2, slope: 1, intercept: 0 },
      bias_definition: "predicted_minus_reference",
    }));
    const output = generate(data).replace(/\\([()])/g, "$1");
    const groups = scientificSummaryGroups(data);
    expect(groups.filter(group => group.title.endsWith("Glucose"))).toHaveLength(1);
    expect(groups[0].rows).toContainEqual(["Response (Y): Glucose", "wt %; reference and predictions share this unit."]);
    expect(groups.find(group => group.table)?.table?.headers).not.toContain("Units");
    expect(output).toContain("Calibration / training");
    expect(output).toContain("Held-out test (recorded role)");
    expect(output).toContain("RMSEC (wt %): 0.4321");
    expect(output).toContain("RMSEP (wt %): 0.4321");
    expect(output).toContain("Bias (wt %): 0");
    expect(output).toContain("SEP (wt %): 0.2");
    for (const text of ["Reference range", "Reference SD", "0.4321", "not degrees-of-freedom-adjusted SEC", "not an ASTM E1655 compliance assessment"]) expect(output).toContain(text);
    expect(output).not.toContain("train / R²");
  });
  it.each([generateProvenanceReport, generateMarkdownReport])("curates key results and preserves evidence in both formats", generate => {
    const output = generate(fixture());
    for (const text of ["Short summary", "train / R²", "cv / RMSE", "0.1235", "protein", "mg/L", "Requested components", "Scores not retained", "not an external held-out test"]) expect(output).toContain(text);
    for (const text of ["verbose detail", "verbose settings", "verbose fold rows", "987654", "per_fold_rmse", "Pipeline Steps"]) expect(output).not.toContain(text);
  });
  it("rejects another run's validation summary and never substitutes current settings", () => {
    const data = fixture();
    data.runs![0].validation_summary!.run_id = 999;
    data.runs![0].saved_definition = null;
    const output = generateProvenanceReport(data);
    expect(output).not.toContain("Target (source)");
    expect(output).toContain("Validation population unavailable");
    expect(output).toContain("current editor settings were not substituted");
  });
  it("uses producer summary facts regardless of their English heading", () => {
    const data = fixture();
    data.runs![0].validation_summary!.summary_rows = [{ label: "Renamed context", value: "Retained scientific fact" }];
    const output = generateProvenanceReport(data);
    expect(output).toContain("Retained scientific fact");
    expect(output).not.toContain("verbose settings");
  });
  it("preserves legacy facts when no structured summary was retained", () => {
    const data = fixture();
    delete data.runs![0].validation_summary!.summary_rows;
    expect(generateProvenanceReport(data)).toContain("verbose settings");
  });
  it("keeps zero, nonconvergence, PCA variance and explicitly scoped classifier metrics", () => {
    expect(keyResultRows({ converged: false, lof_percent: 0, explained_variance_ratio: [0.6, 0.3],
      train_accuracy: 0.99, cv_balanced_accuracy: 0.8, test_f1_macro: 0.7, rmse: null })).toEqual([
      ["Converged", "false"], ["Lack of fit (%)", "0"],
      ["Explained variance ratio by component[1]", "0.6"], ["Explained variance ratio by component[2]", "0.3"],
      ["Training Accuracy", "0.99"], ["CV Balanced accuracy", "0.8"], ["Test Macro F1", "0.7"],
    ]);
  });
  it("does not merge distinct run populations or rank them", () => {
    const data = fixture();
    data.runs!.push({ ...data.runs![0], id: 8, name: "Failed run", status: "failed" });
    const groups = scientificSummaryGroups(data);
    expect(groups.some(g => g.title === "Failed run" && g.notices.some(n => n.includes("incomplete")))).toBe(true);
    expect(generateProvenanceReport(data)).toContain('aria-label="Summary methodology (opens documentation)"');
    expect(generateProvenanceReport(data)).not.toContain("No cross-run ranking");
  });
  it("AI is absent unless explicitly opted in, and detailed results remain available", () => {
    const data = fixture();
    data.narrativeMarkdown = "paid AI narrative";
    expect(generateProvenanceReport(data)).not.toContain("paid AI narrative");
    data.reportMode = "detailed";
    expect(generateProvenanceReport(data)).toContain("verbose detail");
  });
  it("escapes report text and does not fabricate metrics when no run exists", () => {
    const data = fixture();
    data.runs![0].name = "<script>alert(1)</script>";
    expect(generateProvenanceReport(data)).not.toContain("<script>");
    data.runs = [];
    expect(generateMarkdownReport(data)).toContain("workflow definition alone is not a result");
  });
});


it.each([generateProvenanceReport, generateMarkdownReport])("retains classification labels, confusion counts and scaling", generate => {
  const data = fixture();
  data.runs![0].saved_definition = { nodes: [{ node_id: "model", node_type: "classification.plsda", label: "PLS-DA" }] };
  data.runs![0].params_snapshot = { model: { scale: true } };
  data.runs![0].diagnostics = null;
  data.runs![0].results_summary = { evaluation: { default: {
    schema_version: "spectrasherpa.classification-evaluation/1", labels: ["benign", "malignant"],
    confusion_matrix: [[9, 1], [2, 8]], per_class: [{ label: "benign", support: 10, recall: 0.9, precision: 9/11 }],
  } } };
  const output = generate(data);
  expect(output).toContain("Autoscaled");
  expect(output).toContain("benign");
  expect(output).toContain("malignant");
  expect(output).toContain("Reference / predicted");
  expect(output).toContain("per-class performance");
});


it("deduplicates classification aliases without collapsing training, test or contradictory values", () => {
  const data = fixture();
  data.runs![0].saved_definition = { nodes: [{ node_id: "model", node_type: "classification.plsda", label: "PLS-DA" }] };
  data.runs![0].diagnostics = { model: { train_accuracy: 0.97, test_accuracy: 0.97 } };
  data.runs![0].results_summary = { model: { metrics: { task_type: "classification",
    splits: { train: { accuracy: 0.97 }, test: { accuracy: 0.97 } },
  } } };
  let rows = scientificSummaryGroups(data).flatMap(group => group.rows);
  expect(rows.filter(row => row[0] === "Training Accuracy")).toEqual([["Training Accuracy", "0.97"]]);
  expect(rows.filter(row => row[0] === "Test Accuracy")).toEqual([["Test Accuracy", "0.97"]]);
  data.runs![0].diagnostics.model.train_accuracy = 0.75;
  rows = scientificSummaryGroups(data).flatMap(group => group.rows);
  expect(rows.filter(row => row[0] === "Training Accuracy")).toHaveLength(2);
});

it.each([generateProvenanceReport, generateMarkdownReport])("renders per-class metrics once while retaining their complete table", generate => {
  const data = fixture();
  data.runs![0].diagnostics = null;
  data.runs![0].results_summary = { evaluation: { default: {
    schema_version: "spectrasherpa.classification-evaluation/1", labels: ["A", "B"],
    confusion_matrix: [[9, 1], [2, 8]],
    per_class: [{ label: "A", support: 10, precision: 9/11, recall: 0.9, specificity: 0.8, f1: 0.86 }],
  } } };
  const groups = scientificSummaryGroups(data);
  expect(groups.flatMap(group => group.rows).some(row => row[0].includes("per_class"))).toBe(false);
  expect(groups.find(group => group.title.endsWith("per-class performance"))?.table?.rows[0]).toEqual(["A", "10", "0.8182", "0.9", "0.8", "0.86"]);
  expect(generate(data)).toContain("per-class performance");
  // Malformed confusion evidence must not silently hide its surviving class values.
  (data.runs![0].results_summary.evaluation.default as any).confusion_matrix = [];
  expect(scientificSummaryGroups(data).flatMap(group => group.rows).some(row => row[0].includes("per_class"))).toBe(true);
});
