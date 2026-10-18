import { describe, expect, it } from "vitest";

import { initialGoalText, starterStepStates, type StarterOverview } from "@/lib/starterAdapter";
import type { StarterPlan } from "@/types";

const plan = (completions: Array<StarterPlan["steps"][number]["completion"]>): StarterPlan => ({
  schema_version: "spectra-starter-plan/1",
  goal: "Smooth my spectra",
  intent: "preprocess",
  intent_label: "Clean up and transform spectra",
  summary: "",
  confidence: 0.8,
  source: "rules",
  template_slug: "preprocessing",
  template_name: "Preprocessing",
  steps: completions.map((completion, index) => ({
    key: `s${index}`,
    title: `Step ${index}`,
    detail: "",
    action_id: null,
    completion,
  })),
  dataset: null,
  dataset_options: [],
});

const overview = (patch: Partial<StarterOverview>): StarterOverview => ({
  is_first_run: false,
  suggested_goal: "Smooth my spectra and correct the baseline so I can compare samples",
  last_goal: null,
  examples: [],
  model_planning_available: false,
  ...patch,
});

describe("starterStepStates", () => {
  it("marks observed steps done and the first remaining step current", () => {
    expect(
      starterStepStates(plan(["has_project", "has_data", "has_workflow"]), { has_project: true }),
    ).toEqual({ s0: "done", s1: "current", s2: "todo" });
  });

  it("treats a step without a signal as done once a later step is", () => {
    const states = starterStepStates(plan(["has_project", null, "has_executed", null]), {
      has_project: true,
      has_executed: true,
    });
    expect(states).toEqual({ s0: "done", s1: "done", s2: "done", s3: "current" });
  });

  it("finishes a step without a signal only when the plan records it as done", () => {
    const unmarked = plan(["has_project", null]);
    expect(starterStepStates(unmarked, { has_project: true })).toEqual({ s0: "done", s1: "current" });
    const marked = { ...unmarked, completed_steps: ["s1"] };
    expect(starterStepStates(marked, { has_project: true })).toEqual({ s0: "done", s1: "done" });
  });

  it("returns nothing without a plan", () => {
    expect(starterStepStates(null, { has_project: true })).toEqual({});
  });
});

describe("initialGoalText", () => {
  it("suggests a goal on first run and otherwise reuses the last one", () => {
    expect(initialGoalText(overview({ is_first_run: true }))).toMatch(/^Smooth my spectra/);
    expect(initialGoalText(overview({ last_goal: "Find peaks" }))).toBe("Find peaks");
    expect(initialGoalText(overview({ is_first_run: true, last_goal: "Find peaks" }))).toBe("Find peaks");
    expect(initialGoalText(overview({}))).toBe("");
    expect(initialGoalText(null)).toBe("");
  });
});
