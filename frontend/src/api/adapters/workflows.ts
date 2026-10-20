import type { components } from "@/types/api/v1";
import type {
  BackendWorkflowNode,
  BackendWorkflowEdge,
  WorkflowCreatePayload,
  WorkflowListItem,
  WorkflowPreflightResponse,
} from "@/stores/workflow-types";

type Schemas = components["schemas"];

export function workflowListItem(value: Schemas["WorkflowSummary"]): WorkflowListItem {
  return {
    ...value,
    purpose: value.purpose ?? "analysis",
  };
}

export function workflowNode(value: Schemas["WorkflowNodeOut"]): BackendWorkflowNode {
  return {
    ...value,
    label: value.label ?? null,
    parameters: value.parameters ?? {},
    position_x: value.position_x ?? 100,
    position_y: value.position_y ?? 100,
  };
}

export function workflowEdge(value: Schemas["WorkflowEdgeOut"]): BackendWorkflowEdge {
  return { ...value, from_output: value.from_output ?? "default", to_input: value.to_input ?? "default" };
}

export function workflowCreate(value: WorkflowCreatePayload): Schemas["WorkflowCreate"] {
  return {
    ...value,
    nodes: value.nodes.map((node) => ({
      node_id: node.node_id,
      node_type: node.node_type,
      label: node.label,
      parameters: node.parameters,
      position_x: node.position_x,
      position_y: node.position_y,
    })),
    edges: value.edges.map((edge) => ({ ...edge })),
  };
}

export function workflowPreflight(value: Schemas["WorkflowValidationResponse"]): WorkflowPreflightResponse {
  return { ...value, issues: value.issues ?? [], semantic_edges: value.semantic_edges ?? [] };
}
