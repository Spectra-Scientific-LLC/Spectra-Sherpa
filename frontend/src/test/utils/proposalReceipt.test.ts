import { describe, expect, it } from "vitest";
import { summarizeProposalReceipt } from "@/utils/proposalReceipt";

describe("server proposal presentation", () => {
  it("preserves exact admitted changes and qualifications", () => {
    const result = summarizeProposalReceipt({
      schema_version: "spectrasherpa-scientific-proposal/1", receipt_digest: "a".repeat(64),
      changes: [{ node_id: "scale", change: "modified", before: { method: "center" }, after: { method: "autoscale" } }],
      qualifications: ["Runtime missing-value checks remain required."], execution: { requested: false },
    });
    expect(result).toContain('Before: {"method":"center"}');
    expect(result).toContain('After: {"method":"autoscale"}');
    expect(result).toContain("Runtime missing-value checks remain required.");
    expect(result).toContain("Execution was not requested");
  });
  it("does not invent authority for legacy or unknown receipts", () => {
    expect(summarizeProposalReceipt(null)).toContain("authority is unavailable");
    expect(summarizeProposalReceipt({ schema_version: "future" })).toContain("authority is unavailable");
    expect(summarizeProposalReceipt({ schema_version: "spectrasherpa-scientific-proposal/1", changes: [null] })).toContain("authority is unavailable");
  });
});
