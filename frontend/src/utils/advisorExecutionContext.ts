/** One execution gate shared by ordinary chat and Sherpa. Drafts are not result authority.
 *
 * A refused draft still carries contract section 1 input authority. `currentInputContext`
 * is the caller's input-only projection of the loaded dataset — catalog/file inspection
 * and the data store's own capture — and never the identity or dimensions derived from
 * `lastExecutionResults`, which stay refused with the rest of the execution evidence.
 * Callers that cannot separate the two must pass null rather than the merged context.
 */
const toDimension = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

export function bindAdvisorExecutionContext<T extends { nodes: Array<Record<string, unknown>> }>(
  context: T,
  execution: {
    isWorkflowStale?: boolean;
    executionEvidenceScope?: string;
    restoredEvidenceNotice?: string | null;
    lastExecutionResults?: Record<string, unknown> | null;
    restoredRunId?: number | null;
    lastExecutionParams?: Record<string, Record<string, unknown>>;
    // Structural rather than Record<string, unknown>: SherpaDatasetContext is an
    // interface, so it has no implicit index signature and would not assign.
    // Only the dimensions are read here; the rest passes through untouched.
    currentInputContext?: ({ n_samples?: unknown; n_features?: unknown } & object) | null;
  },
) {
  const runId = execution.restoredRunId;
  const scope = execution.executionEvidenceScope ?? "unavailable";
  const allowed =
    scope === "live_full" &&
    !execution.isWorkflowStale &&
    Number.isInteger(runId) &&
    Number(runId) > 0;
  const notice = allowed
    ? "Results belong to the displayed execution. Effective parameters are included only when retained; missing parameters are unknown."
    : "Draft workflow only. Execution results are unavailable for interpretation because the draft changed or its producing run identity is missing. Inspect the saved run or execute the current draft.";
  return {
    ...context,
    execution_run_id: Number.isInteger(runId) && Number(runId) > 0 ? runId : null,
    result_interpretation_allowed: allowed,
    execution_notice: execution.restoredEvidenceNotice || notice,
    execution_evidence_scope: scope,
    execution_returned_nodes: Object.keys(execution.lastExecutionResults ?? {}),
    nodes: context.nodes.map((node) =>
      allowed
        ? { ...node, parameters: execution.lastExecutionParams?.[String(node.node_id)] ?? {} }
        : {
            node_id: node.node_id,
            node_type: node.node_type,
            label: node.label,
            parameters: node.parameters,
            execution_status: "draft",
            result_shape: null,
            result_statistics: null,
            plot_states: null,
            output_type: null,
          },
    ),
    ...(!allowed
      ? {
          results_summary: null,
          diagnostics: null,
          // Top-level dimensions are derived from lastExecutionResults or a node's
          // output_shape, so they are execution evidence. Any dimension a refused
          // draft may state comes from the input projection instead.
          n_samples: toDimension(execution.currentInputContext?.n_samples),
          n_features: toDimension(execution.currentInputContext?.n_features),
          dataset_context: execution.currentInputContext ?? null,
        }
      : {}),
  };
}
