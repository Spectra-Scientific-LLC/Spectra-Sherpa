import { describe, expect, it } from "vitest";
import {
  retainedScientificResultRoute,
  scientificPlotImageTargets,
} from "@/composables/useScientificPlotProjection";

describe("canonical scientific projection surface boundary", () => {
  it("builds retained-result routes for Compare and Run details", () => {
    expect(retainedScientificResultRoute({
      runId: 42,
      projectId: 7,
      nodeId: "pca",
      presentationId: "scores",
    })).toEqual({
      path: "/runs/42",
      query: {
        project: 7,
        node: "pca",
        presentation: "scores",
        view: "Results",
      },
    });
  });

  it("preserves report image identity without re-projecting plot payloads", () => {
    const first = document.createElement("div");
    const second = document.createElement("div");
    const targets = scientificPlotImageTargets(new Map([
      ["node-b", second],
      ["node-a", first],
    ]));

    expect(targets).toEqual([
      { nodeId: "node-b", element: second },
      { nodeId: "node-a", element: first },
    ]);
  });
});
