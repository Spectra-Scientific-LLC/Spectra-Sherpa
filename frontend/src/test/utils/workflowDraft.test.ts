import { beforeEach, describe, expect, it } from "vitest";
import {
  clearMatchingWorkflowDraft,
  editableWorkflowGraph,
  workflowDraftKey,
  workflowDraftSignature,
} from "@/utils/workflowDraft";
import type { WorkflowDraftGraph } from "@/utils/workflowDraft";

const graph = (): WorkflowDraftGraph => ({
  workflowName: "New preprocessing sheet",
  workflowDescription: "",
  nodes: [
    {
      id: "clip_1",
      type: "preprocess.clip_range",
      x: 100,
      y: 100,
      params: { minimum: 600, maximum: 1400 },
    },
  ],
  edges: [],
});

describe("workflow recovery drafts", () => {
  beforeEach(() => localStorage.clear());

  it("clears a saved new-node draft without restoring obsolete execution badges", () => {
    const draft = graph();
    Object.assign(draft.nodes[0], { executionState: { status: "error" } });
    const key = workflowDraftKey(6, 1, 101);
    localStorage.setItem(key, JSON.stringify(draft));
    expect(editableWorkflowGraph(draft).nodes[0]).not.toHaveProperty("executionState");
    clearMatchingWorkflowDraft(key, workflowDraftSignature(graph()));
    expect(localStorage.getItem(key)).toBeNull();
  });

  it("preserves newer parameter edits made while a save was in flight", () => {
    const signature = workflowDraftSignature(graph());
    const newer = graph();
    newer.nodes[0].params.maximum = 1500;
    const key = workflowDraftKey(6, 1, 101);
    const raw = JSON.stringify(newer);
    localStorage.setItem(key, raw);
    clearMatchingWorkflowDraft(key, signature);
    expect(localStorage.getItem(key)).toBe(raw);
  });

  it("ignores serialization order and derived validation state, but retains real edits", () => {
    const original = graph();
    original.edges = [{ from: "load_1", to: "clip_1" }];
    const restored = graph();
    restored.nodes[0].label = "preprocess.clip_range";
    restored.nodes[0].params = { maximum: 1400, minimum: 600 };
    restored.edges = [
      { from: "load_1", to: "clip_1", fromPort: "default", toPort: "default", isValid: false },
    ];
    expect(workflowDraftSignature(restored)).toBe(workflowDraftSignature(original));
    restored.nodes[0].x = 200;
    expect(workflowDraftSignature(restored)).not.toBe(workflowDraftSignature(original));
  });

  it("does not remove another user's or sheet's draft", () => {
    const own = workflowDraftKey(6, 1, 101);
    const other = workflowDraftKey(7, 1, 102);
    localStorage.setItem(own, JSON.stringify(graph()));
    localStorage.setItem(other, JSON.stringify(graph()));
    clearMatchingWorkflowDraft(own, workflowDraftSignature(graph()));
    expect(localStorage.getItem(other)).not.toBeNull();
  });
});
