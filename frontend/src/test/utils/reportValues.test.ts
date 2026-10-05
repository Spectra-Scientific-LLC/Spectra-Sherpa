import { describe, expect, it } from "vitest";
import { reportRows } from "@/utils/reportValues";
import { generateProvenanceReport, type ReportData } from "@/utils/reportGenerator";
import { generateMarkdownReport } from "@/utils/reportMarkdownGenerator";

const metrics = {
  rmse: null, empty: "", absent: undefined, no_values: [], no_fields: {},
  not_finite: NaN, infinite: Infinity,
  bias: 0, converged: false,
  per_target: [{ target_name: "protein", units: "mg/L", rmse: 0.00000012 }],
  per_fold_rmse: [0.1, null, 0.3, 0.4, 0.5],
  _model_artifact: { arrays: { secret_weights: [1, 2] } },
  canonical_artifact_manifest: { storage_path: "/private/secret" },
};

function report(): ReportData {
  return {
    workflowName: "Scientific report", workflowDescription: null, integrityHash: null,
    generatedAt: "2026-09-30", nodes: [], edges: [], plotImages: new Map(),
    terminalMetrics: { live: metrics },
    runs: [{
      id: 1, name: "Saved run", status: "completed", executed_at: null,
      results_summary: { model: metrics }, diagnostics: { model: metrics },
      params_snapshot: {}, node_statuses: null, integrity_hash: null, labels: null,
    }],
    sections: {
      pipelineDetails: true, connections: false, executionResults: true,
      diagnostics: true, runComparison: false, aiNarrative: false,
    },
  };
}

describe("scientific report values", () => {
  it("retains small confusion matrices with class labels and original cell indices", () => {
    expect(reportRows({
      classes: ["control", "case"],
      confusion_matrix: [[8, null], [0, 9]],
    })).toEqual([
      ["classes[1]", "control"], ["classes[2]", "case"],
      ["confusion_matrix[1][1]", "8"],
      ["confusion_matrix[2][1]", "0"], ["confusion_matrix[2][2]", "9"],
    ]);
    expect(reportRows(Array.from({ length: 10 }, () => Array(10).fill(1)))).toHaveLength(100);
    expect(reportRows(Array.from({ length: 10 }, () => Array(11).fill(1)))).toEqual([
      ["", "Matrix: 10 rows × 11 columns (values omitted)"],
    ]);
  });

  it("omits empty matrices and large empty arrays instead of rendering size summaries", () => {
    for (const value of [
      [[null, null]],
      Array(101).fill(null),
      Array.from({ length: 20 }, () => Array(20).fill(null)),
      Array(101).fill(""),
      Array(101).fill(NaN),
    ]) {
      expect(reportRows(value)).toEqual([]);
    }
  });

  it("filters reserved roots and omits empty diagnostics, results and comparison sections", () => {
    const data = report();
    const internalOnly = {
      _scientific_values: { model: { type_ref: "PrivateDescriptor" } },
      _scientific_presentations: { model: { renderer: "PrivateRenderer" } },
      _run_summary: { private_state: "PrivateState" },
      empty_node: { rmse: null, unused: [], nested: {} },
    };
    data.terminalMetrics = internalOnly;
    data.runs![0].results_summary = internalOnly;
    data.runs![0].diagnostics = internalOnly;
    data.runs!.push({ ...data.runs![0], id: 2 });
    data.sections!.runComparison = true;
    data.comparison = { metric_keys: ["rmse"], diff: { rmse: { "1": null } } };
    for (const generate of [generateProvenanceReport, generateMarkdownReport]) {
      const output = generate(data);
      for (const hidden of ["PrivateDescriptor", "PrivateRenderer", "PrivateState", "empty_node", "Diagnostics", "Run Comparison", ">Results<", "## Results"]) {
        expect(output).not.toContain(hidden);
      }
    }
  });

  it("retains node context while excluding empty diagnostic cards and matrix cells", () => {
    const data = report();
    data.runs![0].diagnostics = {
      empty_node: { rmse: null },
      cv_node: { per_fold_rmse: [0.1, 0.2], units: "mg/L", n_folds: 2 },
      _scientific_values: { secret: { type_ref: "PrivateDescriptor" } },
    };
    data.runs![0].results_summary = {
      spectra: {
        data: Array.from({ length: 300 }, () => Array(200).fill(987654321)),
        metadata: { rmse: 0.25, target_name: "protein", units: "mg/L" },
        visualization: { data: [987654321] },
      },
    };
    for (const generate of [generateProvenanceReport, generateMarkdownReport]) {
      const output = generate(data);
      expect(output).toContain("300 rows × 200 columns");
      expect(output).toContain("metadata / target");
      expect(output).toContain("protein");
      expect(output).toContain("mg/L");
      expect(output).toContain("0.25");
      expect(output).toContain("0.2");
      expect(output).not.toContain("987654321");
      expect(output).not.toContain("empty_node");
      expect(output).not.toContain("PrivateDescriptor");
    }
    expect(reportRows({ vector: Array(101).fill(987654321) })).toEqual([
      ["vector", "101 entries (values omitted)"],
    ]);
    expect(reportRows({ matrix: [[], []] })).toEqual([]);
  });

  it("retains zero, false, target units, small quantities and original fold indices", () => {
    expect(reportRows(metrics)).toEqual([
      ["bias", "0"], ["converged", "false"],
      ["per_target[1] / target_name", "protein"],
      ["per_target[1] / units", "mg/L"],
      ["per_target[1] / rmse", "1.2e-7"],
      ["per_fold_rmse[1]", "0.1"], ["per_fold_rmse[3]", "0.3"],
      ["per_fold_rmse[4]", "0.4"], ["per_fold_rmse[5]", "0.5"],
    ]);
  });

  for (const [format, generate] of [
    ["HTML/Vue preview", generateProvenanceReport], ["Markdown", generateMarkdownReport],
  ] as const) {
    it(`renders saved, live and diagnostic values meaningfully in ${format}`, () => {
      const output = generate(report());
      expect(output).toContain("protein");
      expect(output).toContain("mg/L");
      expect(output).toContain("1.2e-7");
      expect(output).toContain("0.5");
      for (const unwanted of ["[object Object]", "null", "undefined", "secret_weights", "/private/secret", "not_finite", "no_fields"]) {
        expect(output).not.toContain(unwanted);
      }
      expect(output).toContain("live");
      expect(output).toContain("model");
    });

    it(`omits empty parameters and preserves nested parameter meaning in ${format}`, () => {
      const data = report();
      data.nodes = [{
        nodeId: "model", nodeType: "model.fitted_pls", label: "PLS", positionX: 0, positionY: 0,
        parameters: { unused: null, selection: { target: "protein", units: "mg/L" } },
      }];
      expect(generate(data)).not.toContain("unused");
      expect(generate(data)).toContain("selection / target");
    });
  }

  it("escapes nested text in HTML and Markdown tables", () => {
    const data = report();
    data.terminalMetrics = { live: { target: "<script>bad</script>|protein\nnext" } };
    expect(generateProvenanceReport(data)).toContain("&lt;script&gt;");
    expect(generateMarkdownReport(data)).toContain("&lt;script&gt;bad&lt;/script&gt;\\|protein next");
  });

  it("preserves qualified comparison labels and omits wholly missing quantities", () => {
    const data = report();
    data.runs!.push({ ...data.runs![0], id: 2 });
    data.sections!.runComparison = true;
    data.comparison = {
      metric_keys: ["protein.cv.rmse", "missing"],
      diff: { "protein.cv.rmse": { "1": 0.2, "2": 0.1 }, missing: { "1": null, "2": null } },
    };
    for (const generate of [generateProvenanceReport, generateMarkdownReport]) {
      expect(generate(data)).toContain("protein.cv.rmse");
      expect(generate(data)).not.toContain("missing");
    }
  });
});
