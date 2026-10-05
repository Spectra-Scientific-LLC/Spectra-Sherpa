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
        rows: [{ label: "Target (source)", value: "protein (continuous; units: mg/L)" },
          { label: "Evaluation population", value: "Cross-validation; not an external held-out test." },
          { label: "Saved settings (pls)", value: "verbose settings" },
          { label: "Fold 1", value: "verbose fold rows" }] },
    }],
  };
}

describe("deterministic short scientific report", () => {
  it("excludes authority and provenance unit leaves without losing endpoint metrics", () => {
    const parameters = { target_authority: { units: "wt %" }, dataset_package: {
      annotation_table: { fields: Array.from({ length: 4 }, () => ({ units: "wt %" })) },
    } };
    const payload = { default: { r2: 0.98,
      target_context: { target_units: "wt %", selected_authority: { units: "wt %" } },
      provenance: [{ parameters }, { parameters }],
      metadata: { processing_history: [{ parameters }] },
    } };
    expect(keyResultRows(payload)).toEqual([["default / R²", "0.98"]]);
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
    expect(previewRows).toEqual([["Target preview", expect.stringContaining("Only 20 of 174 target rows")]]);
    expect(keyResultRows({ comparison: { data: Array.from({ length: 4 }, () => ({ target: "Glucose (wt %)", reference: 1, predicted: 2 })) } })).toEqual([]);
    expect(keyResultRows({ calibration_comparison: { metadata: { n_samples: 20 }, data: [{ target: "Glucose" }] } })).toEqual([]);
  });
  it.each([generateProvenanceReport, generateMarkdownReport])("shows one target heading with separate calibration and evaluation populations", generate => {
    const data = fixture();
    data.runs![0].validation_summary!.regression_results = ["calibration", "held_out_test"].map((role, i) => ({
      node_id: "pls", source_port: i ? "comparison" : "calibration_comparison", target: "Glucose (wt %)",
      units: "wt %", role, reference_min: 0, reference_max: 30, reference_sd: 8,
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
    for (const text of ["Reference range", "Reference SD", "0.4321", "not degrees-of-freedom-adjusted SEC", "not an ASTM E1655 compliance assessment"]) expect(output).toContain(text);
    expect(output).not.toContain("train / R²");
  });
  it.each([generateProvenanceReport, generateMarkdownReport])("curates key results and preserves evidence in both formats", generate => {
    const output = generate(fixture());
    for (const text of ["Short summary", "train / R²", "cv / RMSE", "0.1235", "protein", "mg/L", "Components / latent variables", "Scores not retained", "not an external held-out test"]) expect(output).toContain(text);
    for (const text of ["verbose detail", "verbose settings", "verbose fold rows", "987654", "per_fold_rmse", "Pipeline Steps"]) expect(output).not.toContain(text);
  });
  it("rejects another run's validation summary and never substitutes current settings", () => {
    const data = fixture();
    data.runs![0].validation_summary!.run_id = 999;
    data.runs![0].saved_definition = null;
    const output = generateProvenanceReport(data);
    expect(output).not.toContain("Target (source)");
    expect(output).toContain("Validation population was not retained");
    expect(output).toContain("current editor settings were not substituted");
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
    expect(generateProvenanceReport(data)).toContain("No cross-run ranking");
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
