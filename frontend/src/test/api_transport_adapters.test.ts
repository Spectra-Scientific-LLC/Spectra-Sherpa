import { describe, expect, it } from "vitest";
import type { components } from "@/types/api/v1";
import { experimentFile, experimentSummary, experimentFileAssets, workflowSelectionStage } from "@/api/adapters/datasets";
import { runSummary, runListItem, batchPrediction } from "@/api/adapters/runs";
import { folderWatch } from "@/api/adapters/deploy";
import { workflowCreate, workflowNode, workflowListItem, workflowPreflight } from "@/api/adapters/workflows";

type Schemas = components["schemas"];
const instant = "2026-10-20T12:00:00Z";

const run: Schemas["ExecutionRunOut"] = {
  id: 42, workflow_id: 9, workflow_version_id: 1, user_id: 1,
  name: "Corn moisture", status: "completed", created_at: instant, executed_at: instant,
  params_snapshot: { pls: { n_components: 3 } },
  results_summary: { eval: { rmsep: 0.17, n: 19, units: "wt %", population_role: "held_out_test" } },
  diagnostics: null, node_statuses: null, error: null, integrity_hash: "digest",
  notes: null, evidence_gaps: [],
};

describe("generated transport to view-model boundaries", () => {
  it("narrows stages only for exact workflow submissions, preserving readable legacy metadata", () => {
    for (const stage of ["raw", "preprocessed", "synthetic"]) {
      expect(workflowSelectionStage(stage)).toBe(stage);
    }
    for (const stage of ["legacy-stage", "RAW", "", "toString", "__proto__"]) {
      expect(() => workflowSelectionStage(stage)).toThrow("Choose raw, preprocessed, or synthetic");
    }
  });

  it("retains dataset dimensions, units and target declarations without inference", () => {
    const file: Schemas["ExperimentFileOut"] = {
      id: 3, file_path: "corn.csv", file_type: "csv", stage: "raw",
      file_size_bytes: 100, created_at: instant, shape: [80, 700],
      n_samples: 80, n_features: 700, x_title: "Wavelength", x_units: "nm",
      target_names: ["moisture"], target_types: { moisture: "continuous" },
    };
    expect(experimentFile(file)).toEqual(file);
    expect(experimentFile({ ...file, x_units: null, target_types: null }).x_units).toBeNull();
    // These are open strings in the API. Reading a legacy/future record is not admission.
    expect(experimentFile({ ...file, stage: "legacy-stage" }).stage).toBe("legacy-stage");
    expect(experimentFile({ ...file, target_types: { moisture: "ordinal" } }).target_types).toEqual({ moisture: "ordinal" });
  });

  it("supplies only declared presentation defaults, not scientific values", () => {
    expect(experimentSummary({ id: 1, name: "Iris", created_at: instant }).file_count).toBe(0);
    const assets = experimentFileAssets({
      format_id: "mat", variant: "matrix", parser_id: "mat", parser_version: "1",
      source_sha256: "source",
      assets: [{ asset_id: "X", shape: [80, 700], dimension_roles: ["sample", "feature"], data_role: "X_spectra" }],
    });
    expect(assets.assets[0].warnings).toEqual([]);
    expect(assets.assets[0].value_units).toBeUndefined();
  });

  it("keeps retained metrics, population, identity and absent fields distinct", () => {
    const projected = runSummary(run);
    expect(projected.results_summary).toEqual(run.results_summary);
    expect(projected.params_snapshot).toEqual(run.params_snapshot);
    expect(projected.workflow_id).toBe(9);
    expect(projected.project_id).toBeNull();
    expect(projected.labels).toBeNull();
    expect(projected.run_kind).toBe("other");
    const legacy = { eval: [0.17, null], scalar: 1, absent: null };
    expect(runSummary({ ...run, results_summary: legacy }).results_summary).toEqual(legacy);
  });

  it("does not turn a lightweight run list into retained evidence", () => {
    const item: Schemas["RunListItem"] = {
      id: 42, project_id: 3, workflow_id: 9, workflow_version_id: 1,
      name: "Corn moisture", display_name: "Moisture sheet", workflow_name: "Moisture sheet",
      status: "completed", run_kind: "training", executed_at: instant, created_at: instant,
      labels: null, produced_artifact_uids: ["artifact"], attempted_artifact_uids: null,
      succeeded_artifact_uids: null,
    };
    expect(runListItem(item)).toEqual(item);
    expect(runListItem(item)).not.toHaveProperty("results_summary");
  });

  it("preserves deployment watches and batch refusal evidence", () => {
    const watch: Schemas["FolderWatchOut"] = {
      id: 1, user_id: 1, workflow_id: 9, name: "Incoming", folder_path: "/incoming",
      file_pattern: "*.csv", poll_interval_sec: 60, settle_time_seconds: 2,
      asset_id: null, is_enabled: false, processed_files: { "a.csv": "sha" },
      last_poll_at: null, last_error: "Missing model authority", created_at: instant, updated_at: null,
      artifact_uid: "model", uncertainty_record: { qualification: "unavailable" },
    };
    expect(folderWatch(watch)).toEqual(watch);
    const prediction = batchPrediction({
      id: 2, run_id: 42, file_name: "a.csv", file_path: "/incoming/a.csv",
      status: "error", results: null, error_message: "Feature axis mismatch",
      processing_time_ms: null, created_at: instant,
    });
    expect(prediction.results).toBeNull();
    expect(prediction.error_message).toBe("Feature axis mismatch");
    expect(prediction.model_id).toBeNull();
  });

  it("keeps workflow save transport separate from editable canvas fields", () => {
    const payload = workflowCreate({
      name: "PCA", status: "draft", project_id: 3,
      nodes: [{ node_id: "pca", node_type: "model.pca", label: "Train PCA",
        parameters: { n_components: 3 }, position_x: 0, position_y: 40 }],
      edges: [{ from_node_id: "load", to_node_id: "pca", from_output: "default", to_input: "X" }],
    });
    expect(payload.purpose).toBeUndefined(); // The server owns this default.
    expect(payload.nodes?.[0].position_x).toBe(0);
    expect(payload.nodes?.[0].parameters).toEqual({ n_components: 3 });
    expect(payload.edges?.[0].to_input).toBe("X");
  });

  it("adapts workflow metadata and preflight without rewriting warnings", () => {
    const summary: Schemas["WorkflowSummary"] = {
      id: 9, user_id: 1, folder_id: null, name: "PCA",
      created_at: instant, updated_at: instant, last_executed_at: null,
      purpose: "managed_candidate_authority", color_source: "data",
    };
    expect(workflowListItem(summary).purpose).toBe("managed_candidate_authority");
    expect(workflowListItem({ ...summary, color_source: "legacy-color-source" }).color_source).toBe("legacy-color-source");
    const issue = { level: "error", message: "Reference values not connected", code: "missing_input" } satisfies Schemas["WorkflowValidationIssue"];
    expect(workflowPreflight({ workflow_id: 9, is_valid: false, issues: [issue] }).issues).toEqual([issue]);
    expect(workflowPreflight({ workflow_id: 9, is_valid: true }).semantic_edges).toEqual([]);
    expect(workflowNode({
      id: 1, workflow_id: 9, node_id: "pca", node_type: "model.pca",
      position_x: 0, position_y: null,
      created_at: instant, updated_at: instant, execution_order: null, status: "pending",
    }).position_x).toBe(0);
  });
});
