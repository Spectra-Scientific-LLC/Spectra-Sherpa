import { describe, expect, it } from "vitest";
import {
  generateProvenanceReport,
  topologicalSort,
  type ReportData,
  type RunReportEntry,
} from "@/utils/reportGenerator";
import { generateMarkdownReport } from "@/utils/reportMarkdownGenerator";

const run = (id: number): RunReportEntry => ({
  id,
  name: `Run ${id}`,
  status: "completed",
  executed_at: null,
  results_summary: {},
  diagnostics: null,
  params_snapshot: {},
  node_statuses: {},
  integrity_hash: null,
  labels: [],
  evidence_notice: "Saved summary; inspect retained evidence.",
  workflow_identity: {
    project_id: 9,
    workflow_id: 17,
    template_name: "Preprocessing Pipeline",
    template_version: "1",
    source_name: "Run-bound atmospheric source",
    source_origin: "current",
  },
  evidence_gaps: [
    {
      node_id: "export_1",
      output: "artifact",
      role: "prepared CSV",
      state: "missing",
      category: "storage_limit",
      reason: "Output exceeds the retained materialization budget.",
      recovery: "Increase retained-output capacity, then rerun the workflow.",
    },
  ],
});
const data = (): ReportData => ({
  workflowName: "Saved comparison",
  workflowDescription: null,
  integrityHash: null,
  generatedAt: "2026-09-11",
  nodes: [],
  edges: [],
  plotImages: new Map(),
  terminalMetrics: {},
  workflowIdentity: {
    project_id: 9,
    workflow_id: 17,
    template_name: "Preprocessing Pipeline",
    template_version: "1",
    source_name: "Synthetic Atmospheric (bundled example)",
    source_origin: "example",
  },
  runs: [run(2), run(1)],
  sections: {
    pipelineDetails: false,
    connections: false,
    executionResults: true,
    diagnostics: false,
    runComparison: true,
    aiNarrative: false,
  },
  comparison: {
    metric_keys: ["accuracy"],
    diff: { accuracy: { "1": 0.9, "2": 0.8588 } },
    rankable_metrics: [],
  },
});

describe("Saved report evidence", () => {
  it("exports a frozen project-evidence snapshot without inventing a linked chain", () => {
    const report = data();
    report.projectEvidence = {
      state: "available", projectId: 9, capturedAt: "2026-10-04T08:00:00Z", reason: null,
      records: [{ kind: "dataset", label: "Dataset", state: "healthy",
        name: "Corn <M5>", digest: "b".repeat(64), record_id: 12,
        detail: "verified", destination: "/data" }],
    };
    for (const output of [generateProvenanceReport(report), generateMarkdownReport(report)]) {
      expect(output).toContain("Project evidence");
      expect(output).toContain("not proof");
      expect(output).toContain("b".repeat(64));
      expect(output).not.toContain("<M5>");
    }
    expect(generateProvenanceReport(report)).toContain("Corn &lt;M5&gt;");
  });
  it("carries the same saved validation facts into preview HTML and Markdown, refusing another run's summary", () => {
    const report = data();
    report.runs![0].validation_summary = {
      schema_version: 'spectrasherpa-readable-validation/1', run_id: 2,
      rows: [{ label: 'Metric denominator', value: '4' }, { label: 'Groups', value: 'Not established' }],
    };
    for (const output of [generateProvenanceReport(report), generateMarkdownReport(report)]) {
      expect(output).toContain('Validation summary');
      expect(output).toContain('Metric denominator');
      expect(output).toContain('Not established');
    }
    report.runs![0].validation_summary.run_id = 999;
    expect(generateProvenanceReport(report)).not.toContain('Metric denominator');
    expect(generateMarkdownReport(report)).not.toContain('Metric denominator');
  });
  it("retains all steps when historical connections are incomplete or cyclic", () => {
    const nodes = ["a", "b"].map((nodeId) => ({
      nodeId,
      nodeType: "test",
      label: nodeId,
      parameters: {},
      positionX: 0,
      positionY: 0,
    }));
    const edge = (fromNodeId: string, toNodeId: string) => ({
      fromNodeId,
      toNodeId,
      fromOutput: "default",
      toInput: "X",
    });
    expect(topologicalSort(nodes, [edge("missing", "a"), edge("a", "b")])).toEqual(nodes);
    expect(topologicalSort(nodes, [edge("a", "b"), edge("b", "a")])).toEqual(nodes);
  });
  it("never prints unqualified improvement claims in HTML or Markdown", () => {
    const html = generateProvenanceReport(data());
    const md = generateMarkdownReport(data());
    expect(html).not.toContain('class="metric-best"');
    expect(html).not.toContain("0.0412");
    expect(md).not.toContain("0.0412");
    expect(html).toContain("Results are not ranked");
    expect(md).toContain("Results are not ranked");
    expect(html).toContain("Saved run 2");
    expect(md).toContain("**Saved run**: 2");
    expect(html).toContain("Run-bound atmospheric source");
    expect(md).toContain("**Run source**: Run-bound atmospheric source (Current project data)");
    expect(html).toContain("Synthetic Atmospheric (bundled example)");
    expect(html).toContain("prepared CSV");
    expect(html).toContain("Increase retained-output capacity");
    expect(md).toContain("**Workflow sheet**: #17");
    expect(md).toContain("export_1 · prepared CSV");
  });
  it("uses displayed run order and lower-is-better direction for qualified RMSE", () => {
    const report = data();
    report.comparison = {
      metric_keys: ["qualified_cv.rmse"],
      diff: { "qualified_cv.rmse": { "1": 0.5, "2": 1 } },
      rankable_metrics: ["qualified_cv.rmse"],
    };
    const html = generateProvenanceReport(report);
    expect(html).toContain('class="delta-positive">-0.5000');
    expect(generateMarkdownReport(report)).toContain("-0.5000");
  });
  it("carries sheet selection revisions and exact executed filters into HTML and Markdown", () => {
    const report = data();
    report.runs = [
      {
        ...run(7),
        selection_provenance: {
          schema_version: 1,
          state: "exact",
          reason: null,
          executor_user_id: 12,
          workflow_version_id: 4,
          revisions: [
            {
              revision_id: 31,
              revision_number: 2,
              source_node_id: "source",
              created_by: 9,
              created_at: "2026-09-20T10:00:00Z",
              origin: "data_page",
              reason: "Exclude failed scans",
              graph_digest: "d".repeat(64),
              selection: {
                dataset_name: "Wine",
                experiment_id: 11,
                stage: "raw",
                selected_file_ids: [22],
                target_authority: {
                  column: "cultivar",
                  target_type: "categorical",
                  units: null,
                  source_digest: "c".repeat(64),
                },
                group_column: "vintage",
                scientific_collection_sha256: "c".repeat(64),
              },
            },
          ],
          scientific_receipts: [
            {
              node_id: "source",
              scientific_digest: "e".repeat(64),
              shape: [2, 6, 13],
              title: "Wine",
              selection_lineage: [
                {
                  node_id: "filter-1",
                  operation: "data.filter_samples",
                  parameters: { field: "sample_index", pattern: "1-2, 5-6" },
                  selected_index_ranges: [
                    [0, 1],
                    [4, 5],
                  ],
                  selected_indices_sha256: "f".repeat(64),
                  input_shape: [9, 13],
                  output_shape: [6, 13],
                },
              ],
            },
          ],
        },
      },
    ];

    const html = generateProvenanceReport(report);
    const markdown = generateMarkdownReport(report);
    expect(html).toContain("selection revision 2");
    expect(html).toContain("Executed sample filters");
    expect(html).toContain("shape 2 × 6 × 13");
    expect(html).not.toContain("rows/features");
    expect(html).toContain("1-2, 5-6");
    expect(html).toContain("f".repeat(64));
    expect(markdown).toContain("Exclude failed scans");
    expect(markdown).toContain("Exact row receipt");
    expect(markdown).toContain("1-2, 5-6");
  });
});
