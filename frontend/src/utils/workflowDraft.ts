import type { WorkflowEdge, WorkflowNode } from "@/stores/workflow-types";
import { requestScopedSingleFlightKey } from "@/utils/idempotency";

export interface WorkflowDraftGraph {
  workflowName: string;
  workflowDescription: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

export const workflowDraftKey = (
  userId: number | string | null | undefined,
  projectId: number,
  workflowId: number,
): string => `spectra_sherpa_workflow_draft_v1:${userId ?? "local"}:${projectId}:${workflowId}`;

// Recovery stores editable graph state, never execution or validation results.
export function editableWorkflowGraph(graph: WorkflowDraftGraph): WorkflowDraftGraph {
  return {
    workflowName: graph.workflowName,
    workflowDescription: graph.workflowDescription || "",
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      label: node.label || node.type,
      x: node.x,
      y: node.y,
      params: node.params,
    })),
    edges: graph.edges.map((edge) => ({
      from: edge.from,
      to: edge.to,
      fromPort: edge.fromPort || "default",
      toPort: edge.toPort || "default",
    })),
  };
}

export function workflowDraftSignature(graph: WorkflowDraftGraph): string {
  const editable = editableWorkflowGraph(graph);
  editable.nodes.sort((a, b) => a.id.localeCompare(b.id));
  editable.edges.sort((a, b) =>
    JSON.stringify([a.from, a.to, a.fromPort, a.toPort]).localeCompare(
      JSON.stringify([b.from, b.to, b.fromPort, b.toPort]),
    ),
  );
  return requestScopedSingleFlightKey("workflow-draft", editable);
}

export function clearMatchingWorkflowDraft(key: string, savedSignature: string): void {
  try {
    const raw = localStorage.getItem(key);
    if (raw && workflowDraftSignature(JSON.parse(raw)) === savedSignature) {
      localStorage.removeItem(key);
    }
  } catch {
    // Unavailable storage or malformed recovery data must not fail a server save.
  }
}
