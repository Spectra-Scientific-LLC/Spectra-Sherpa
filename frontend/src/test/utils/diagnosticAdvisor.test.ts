import { describe, expect, it, vi } from "vitest";
import { reactive } from "vue";
import {
  diagnosticReference,
  diagnosticCitation,
  restoredDiagnosticScope,
  type DiagnosticScope,
} from "@/utils/diagnosticAdvisor";
import { requestAdvisorPrompt, ADVISOR_PROMPT_REQUEST_EVENT } from "@/lib/advisorPromptActions";
import type { PcaReview } from "@/utils/sampleReview";
const review = {
  run_id: 42,
  graph_digest: "a".repeat(64),
  source_digest: "b".repeat(64),
  revision: 3,
  rows: [{ id: "a" }, { id: "b" }],
} as PcaReview;
const scope = (): DiagnosticScope => ({
  project_id: 7,
  reference: diagnosticReference(review, 8, "pls", ["a"], 1, ["axis:2"], null),
  digest: "c".repeat(64),
  facts: { "S1.predicted": { value: 12.5, units: "g/L", meaning: "Predicted response" } },
  sample_aliases: { S1: "Observation A" },
});
describe("diagnostic Advisor custody on the client", () => {
  it("does not add GUI display labels to Advisor references or replace selected IDs", () => {
    const labeled = {
      ...review,
      rows: review.rows.map((row) => ({ ...row, display_label: "GUI-only private label" })),
    };
    const reference = diagnosticReference(review, 8, "pca", ["a"], 0, [], null);
    expect(diagnosticReference(labeled, 8, "pca", ["a"], 0, [], null)).toEqual(reference);
    expect(reference.selected_ids).toEqual(["a"]);
    expect(JSON.stringify(reference)).not.toContain("GUI-only");
  });
  it("uses complete-cohort references for a large selection and rejects invented or duplicate membership", () => {
    const big = {
      ...review,
      rows: Array.from({ length: 5000 }, (_, i) => ({ id: `row-${i}` })),
    } as PcaReview;
    expect(
      diagnosticReference(
        big,
        8,
        "pca",
        big.rows.map((r) => r.id),
        0,
        [],
        null,
      ),
    ).toMatchObject({ selected_ids: [], select_all: true });
    expect(() =>
      diagnosticReference(
        big,
        8,
        "pca",
        big.rows.slice(0, 1500).map((r) => r.id),
        0,
        [],
        null,
      ),
    ).toThrow("Narrow the selection");
    for (const ids of [[], ["missing"], ["a", "a"]])
      expect(() => diagnosticReference(review, 8, "pca", ids, 0, [], null)).toThrow();
  });
  it("freezes reactive event scope without exposing mutable chart selections", () => {
    const source = reactive(scope());
    const receive = vi.fn();
    window.addEventListener(ADVISOR_PROMPT_REQUEST_EVENT, receive);
    requestAdvisorPrompt(" Explain ", { diagnosticScope: source });
    source.reference.selected_ids.push("b");
    const detail = (receive.mock.calls[0][0] as CustomEvent).detail;
    expect(detail.prompt).toBe("Explain");
    expect(detail.diagnosticScope.reference.selected_ids).toEqual(["a"]);
    window.removeEventListener(ADVISOR_PROMPT_REQUEST_EVENT, receive);
  });
  it("does not resurrect old diagnostic evidence after an ordinary turn or another project", () => {
    const messages = [
      { role: "assistant", diagnostic_scope: scope() },
      { role: "user" },
      { role: "assistant" },
    ];
    expect(restoredDiagnosticScope(messages, 7)).toBeNull();
    expect(restoredDiagnosticScope(messages.slice(0, 1), 99)).toBeNull();
    expect(restoredDiagnosticScope(messages.slice(0, 1), 7)?.reference.run_id).toBe(42);
  });
  it("resolves only exact scope and handle citations, with visible observation labels and safe malformed links", () => {
    expect(diagnosticCitation(`#diagnostic-${"c".repeat(64)}-S1.predicted`, [scope()])).toEqual({
      title: "Predicted response",
      detail: "S1: Observation A · 12.5 g/L · Run 42 · Review 3 · S1.predicted",
    });
    expect(diagnosticCitation(`#diagnostic-${"d".repeat(64)}-S1.predicted`, [scope()])?.title).toBe(
      "Evidence unavailable",
    );
    expect(diagnosticCitation(`#diagnostic-${"c".repeat(64)}-__proto__`, [scope()])?.title).toBe(
      "Evidence unavailable",
    );
    expect(diagnosticCitation(`#diagnostic-${"c".repeat(64)}-%XX`, [scope()])).toBeNull();
    expect(diagnosticCitation("https://example.invalid", [scope()])).toBeNull();
  });
});
