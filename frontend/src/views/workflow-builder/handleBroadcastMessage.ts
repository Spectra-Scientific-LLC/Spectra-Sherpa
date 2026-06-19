/**
 * Pure handler for BroadcastChannel `node_params_updated` messages.
 *
 * Extracted so both WorkflowBuilderContent.vue and the integration test
 * exercise the exact same logic — no replicated stubs.
 */
export function handleBroadcastMessage(
  event: MessageEvent,
  nodes: { value: Array<{ id: string; params?: Record<string, unknown> }> },
  updateNode: (nodeId: string, patch: { params: Record<string, unknown> }) => void,
  currentWorkflowId?: number | null,
): { applied: boolean; reason?: string; requestId?: string; nodeId?: string; workflowId?: number | null } {
  const { type, nodeId, params, workflowId, requestId } = event.data;

  if (type === "node_params_updated") {
    if (
      workflowId != null &&
      currentWorkflowId != null &&
      Number(workflowId) !== Number(currentWorkflowId)
    ) {
      return { applied: false, reason: "workflow-mismatch", requestId, nodeId, workflowId };
    }
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node && params) {
      updateNode(nodeId, { params });
      return { applied: true, requestId, nodeId, workflowId };
    }
    return { applied: false, reason: node ? "missing-params" : "node-not-found", requestId, nodeId, workflowId };
  }

  return { applied: false, reason: "ignored-message-type", requestId, nodeId, workflowId };
}
