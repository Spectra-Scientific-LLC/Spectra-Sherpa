import { describe, expect, it } from "vitest";
import { bindAdvisorExecutionContext } from "@/utils/advisorExecutionContext";
const context = {
  nodes: [
    {
      node_id: "pca",
      node_type: "model.pca",
      parameters: { n_components: 5 },
      execution_status: "completed",
      plot_states: [{ plot: "Old scores" }],
      result_shape: [10, 2],
    },
  ],
  results_summary: { pca: { variance: 0.9 } },
  diagnostics: { pca: { rmse: 1 } },
  n_samples: 10,
  dataset_context: { n_samples: 10 },
};
describe("XGSC-01 advisor execution gate", () => {
  it.each([true, false])("refuses stale or missing-run result authority (stale=%s)", (stale) => {
    const value = bindAdvisorExecutionContext(context, {
      isWorkflowStale: stale,
      executionEvidenceScope: "live_full",
      restoredRunId: stale ? 10 : null,
    });
    expect(value.result_interpretation_allowed).toBe(false);
    expect(value.results_summary).toBeNull();
    expect(value.diagnostics).toBeNull();
    expect(value.n_samples).toBeNull();
    expect(value.dataset_context).toBeNull();
    expect(value.nodes[0]).toMatchObject({
      parameters: { n_components: 5 },
      execution_status: "draft",
      plot_states: null,
      result_shape: null,
    });
  });
  it("uses saved effective parameters even when draft defaults differ", () => {
    const value = bindAdvisorExecutionContext(context, {
      executionEvidenceScope: "live_full",
      restoredRunId: 10,
      lastExecutionParams: { pca: { n_components: 2, scale: false } },
    });
    expect(value.nodes[0].parameters).toEqual({ n_components: 2, scale: false });
    expect(value.execution_run_id).toBe(10);
  });
  it("leaves unavailable historical parameters unknown", () => {
    expect(
      bindAdvisorExecutionContext(context, {
        executionEvidenceScope: "live_full",
        restoredRunId: 10,
      }).nodes[0].parameters,
    ).toEqual({});
  });
  it.each(["partial", "restored_summary", "unavailable"])(
    "refuses %s with structured qualification",
    (scope) => {
      const result = bindAdvisorExecutionContext(context, {
        restoredRunId: 10,
        executionEvidenceScope: scope,
        restoredEvidenceNotice: "Retained outputs incomplete",
        lastExecutionResults: { source: [[1]] },
      });
      expect(result.result_interpretation_allowed).toBe(false);
      expect(result.execution_evidence_scope).toBe(scope);
      expect(result.execution_returned_nodes).toEqual(["source"]);
      expect(result.execution_notice).toBe("Retained outputs incomplete");
      expect(result.results_summary).toBeNull();
    },
  );
  it("carries loaded input authority through a refused draft without execution-derived evidence", () => {
    // Current input: what the user loaded. n_samples/n_features here describe the
    // dataset, not a run. The top-level 10 in `context` came from lastExecutionResults.
    const result = bindAdvisorExecutionContext(context, {
      executionEvidenceScope: "unavailable",
      restoredRunId: null,
      currentInputContext: {
        dataset_id: "ds_iris_123",
        n_samples: 150,
        n_features: 4,
        x_title: "Feature",
        x_units: "cm",
        target_names: ["setosa", "virginica"],
      },
    });

    expect(result.result_interpretation_allowed).toBe(false);
    // Section 1 input authority survives the refusal.
    expect(result.dataset_context).toMatchObject({
      dataset_id: "ds_iris_123",
      x_units: "cm",
      target_names: ["setosa", "virginica"],
    });
    expect(result.n_samples).toBe(150);
    expect(result.n_features).toBe(4);
    // Sections 4 and 7 still refuse every execution claim, including the stale
    // result-derived dimension that the unrefused payload carried.
    expect(result.results_summary).toBeNull();
    expect(result.diagnostics).toBeNull();
    expect(result.nodes[0].plot_states).toBeNull();
    expect(result.nodes[0].result_shape).toBeNull();
  });

  it("refuses dimensions entirely when the caller cannot qualify an input projection", () => {
    const result = bindAdvisorExecutionContext(context, {
      executionEvidenceScope: "unavailable",
      restoredRunId: null,
      currentInputContext: null,
    });
    expect(result.dataset_context).toBeNull();
    expect(result.n_samples).toBeNull();
    expect(result.n_features).toBeNull();
  });
});
