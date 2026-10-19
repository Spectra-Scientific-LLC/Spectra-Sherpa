/** Selected bands establish point values, not interpolation across removed bands. */
export function hasVariableSelectionHistory(metadata: any, payload?: any): boolean {
  const history = payload?.metadata?.processing_history ?? metadata?.processing_history;
  return Array.isArray(history) && history.some(step =>
    typeof step?.op_id === "string" && step.op_id.startsWith("selection."));
}
