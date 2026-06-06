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
): void {
  const { type, nodeId, params, workflowId } = event.data;

  if (type === "node_params_updated") {
    if (
      workflowId != null &&
      currentWorkflowId != null &&
      Number(workflowId) !== Number(currentWorkflowId)
    ) {
      return;
    }
    const node = nodes.value.find((n) => n.id === nodeId);
    if (node && params) {
      updateNode(nodeId, { params });
    }
  }
}
