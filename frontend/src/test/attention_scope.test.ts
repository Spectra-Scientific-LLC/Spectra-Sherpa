import { beforeEach, describe, expect, it } from "vitest";
import { activeProjectScope } from "@/stores/projectScopeRegistry";
import { attentionSnapshot, focusPlot, setAttentionWindow } from "@/lib/sherpaAttention";

describe("attention follows project authority", () => {
  beforeEach(() => { activeProjectScope.value = 1; setAttentionWindow("/workflow"); });
  it("clears node and plot focus synchronously when a project changes on the same route", () => {
    focusPlot("old-plot", "node-in-old-project", "scores");
    activeProjectScope.value = 2;
    expect(attentionSnapshot()).toEqual({ window: "workflow", surface: "window" });
  });
  it("clears focus when project authority disappears", () => {
    focusPlot("old-plot", "old-node");
    activeProjectScope.value = null;
    expect(attentionSnapshot()).toEqual({ window: "workflow", surface: "window" });
  });
  it("does not reset the focused plot when the project is unchanged", () => {
    focusPlot("current-plot", "current-node");
    activeProjectScope.value = 1;
    expect(attentionSnapshot().plot_id).toBe("current-plot");
  });
  it("recognizes report and model views as results", () => {
    for (const path of ["/report?run=4", "/models", "/runs/4"]) {
      setAttentionWindow(path);
      expect(attentionSnapshot().window).toBe("results");
    }
  });
});

describe("Optimize focus for the side-chat Advisor", () => {
  beforeEach(() => { activeProjectScope.value = 1; setAttentionWindow("/campaigns"); });
  it("carries only well-formed campaign and candidate identifiers", async () => {
    const { focusOptimization } = await import("@/lib/sherpaAttention");
    focusOptimization("campaign-pls-001", "candidate-012");
    expect(attentionSnapshot()).toEqual({
      window: "optimization", surface: "window", campaign_id: "campaign-pls-001", candidate_id: "candidate-012",
    });
    focusOptimization("campaign-pls-001", "bad id with spaces");
    expect(attentionSnapshot()).toEqual({ window: "optimization", surface: "window", campaign_id: "campaign-pls-001" });
    focusOptimization("<script>");
    expect(attentionSnapshot()).toEqual({ window: "optimization", surface: "window" });
  });
  it("forgets the campaign when the project changes", async () => {
    const { focusOptimization } = await import("@/lib/sherpaAttention");
    focusOptimization("campaign-pls-001");
    activeProjectScope.value = 2;
    expect(attentionSnapshot()).toEqual({ window: "optimization", surface: "window" });
  });
});

it("keeps resource context while focusing a plot or changing section, then clears it on project change", async () => {
  const { focusOptimization, focusSection, releasePlot } = await import("@/lib/sherpaAttention");
  focusOptimization("campaign-owned", "candidate-2");
  focusSection("results");
  focusPlot("diagnostic");
  expect(attentionSnapshot()).toMatchObject({ campaign_id: "campaign-owned", candidate_id: "candidate-2", section: "results", surface: "plot" });
  releasePlot("diagnostic");
  expect(attentionSnapshot()).toMatchObject({ campaign_id: "campaign-owned", section: "results", surface: "window" });
  focusSection("new-round");
  expect(attentionSnapshot().section).toBe("new-round");
  setAttentionWindow("/project");
  expect(attentionSnapshot()).toEqual({ window: "project", surface: "window" });
});
