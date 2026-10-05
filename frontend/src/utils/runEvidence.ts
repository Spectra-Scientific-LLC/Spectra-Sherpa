export type EvidenceGap = {
  node_id: string;
  output: string;
  role?: string | null;
  state: "reduced" | "missing" | "unverified";
  category: "reduced" | "session_only" | "storage_limit" | "unavailable" | "unverified";
  reason: string;
  recovery: string;
};

export function visibleEvidenceGapLabel(
  gap: EvidenceGap,
  nodeLabels: Record<string, string> = {},
): string {
  const node = nodeLabels[gap.node_id] || gap.node_id;
  const output = gap.role || gap.output;
  return `${node} · ${output}`;
}

export function evidenceScopeLabel(category: EvidenceGap["category"]): string {
  if (category === "session_only") return "Session-only output";
  if (category === "storage_limit") return "Storage limit";
  if (category === "reduced") return "Retained preview";
  if (category === "unverified") return "Unverified history";
  return "Unavailable output";
}
