/** Fields used to bind a node to an immutable artifact or execution contract. */
export const INTERNAL_NODE_PARAMETER_NAMES = new Set([
  "artifact_digest",
  "state_node_id",
  "state_digest",
  "state_content_digest",
  "serializer",
  "source_contract_digest",
  "fitted_state_serializer",
  "application_contract_digest",
]);

export function isUserEditableNodeParameter(param: { name?: unknown; category?: unknown }): boolean {
  if (param.category === "internal") return false;
  const name = typeof param.name === "string" ? param.name.trim().toLowerCase() : "";
  return !INTERNAL_NODE_PARAMETER_NAMES.has(name);
}
