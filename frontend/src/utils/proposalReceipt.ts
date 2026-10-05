/** Render the server's retained proposal contract, never current editor state. */
export function summarizeProposalReceipt(value: unknown): string {
  if (!value || typeof value !== "object") return "Proposal authority is unavailable; inspect the saved workflow before running.";
  const receipt = value as Record<string, unknown>;
  if (receipt.schema_version !== "spectrasherpa-scientific-proposal/1" ||
      !Array.isArray(receipt.changes) ||
      !receipt.changes.every((item) => item && typeof item === "object" && typeof item.change === "string") ||
      !Array.isArray(receipt.qualifications) ||
      !receipt.execution || typeof receipt.execution !== "object" ||
      typeof receipt.receipt_digest !== "string") {
    return "Proposal authority is unavailable; inspect the saved workflow before running.";
  }
  const changes = receipt.changes.map((change: Record<string, unknown>) => {
    const label = `${change.node_id ?? "Connections"}: ${change.change}`;
    if (!("before" in change) || !("after" in change)) return label;
    return `${label}\nBefore: ${JSON.stringify(change.before)}\nAfter: ${JSON.stringify(change.after)}`;
  });
  const execution = receipt.execution as Record<string, unknown>;
  return [
    `Proposal receipt: ${receipt.receipt_digest}`,
    ...changes,
    ...receipt.qualifications.filter((item): item is string => typeof item === "string"),
    execution.requested === true
      ? "Execution explicitly requested; completion is reported separately."
      : "Saved as a draft. Execution was not requested.",
  ].join("\n");
}
