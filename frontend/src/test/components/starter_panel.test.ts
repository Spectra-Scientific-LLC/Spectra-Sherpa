import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useGuidanceStore } from "@/stores/guidance";
import type { ProjectSummary, StarterPlan } from "@/types";
import StarterPanel from "@/views/dashboard/StarterPanel.vue";

const adapter = vi.hoisted(() => ({
  fetchStarterOverview: vi.fn(),
  planStarterGoal: vi.fn(),
  fetchStarterProgress: vi.fn(),
}));

vi.mock("@/lib/starterAdapter", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/starterAdapter")>()),
  ...adapter,
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useRoute: () => ({ hash: "" }),
}));

const PLAN: StarterPlan = {
  schema_version: "spectra-starter-plan/1",
  goal: "Predict moisture in my corn NIR spectra",
  intent: "calibrate",
  intent_label: "Predict a value from spectra",
  summary: "Build a PLS calibration that predicts a measured property such as concentration.",
  confidence: 0.8,
  source: "model",
  template_slug: "pls_calibration",
  template_name: "PLS Calibration",
  steps: [
    { key: "project", title: "Create a project for this goal", detail: "Project detail", action_id: null, completion: "has_project" },
    { key: "data", title: "Add your spectra", detail: "Data detail", action_id: "import_data", completion: "has_data" },
    { key: "workflow", title: "Open the PLS Calibration starter", detail: "Workflow detail", action_id: "open_workflow", completion: "has_workflow" },
    { key: "review", title: "Review the results", detail: "Review detail", action_id: "view_results", completion: null },
  ],
  dataset: {
    key: "registered:corn",
    label: "Eigenvector Corn M5",
    kind: "reference",
    source: "registered",
    technique: "NIR",
    availability: "exact_user_acquisition_required",
    experiment_id: null,
    reason: "Corn moisture matches your goal.",
    chosen_by: "model",
  },
  dataset_options: [
    { key: "registered:corn", label: "Eigenvector Corn M5", kind: "reference", source: "registered", technique: "NIR", availability: "exact_user_acquisition_required", experiment_id: null },
    { key: "experiment:7", label: "Grain batch", kind: "experiment", source: "experiment", technique: null, availability: null, experiment_id: 7 },
  ],
};

const overview = (patch = {}) => ({
  is_first_run: true,
  suggested_goal: "Smooth my spectra and correct the baseline so I can compare samples",
  last_goal: null,
  examples: [{ intent: "peaks", label: "Find and measure peaks", goal: "Find the peaks in my spectra" }],
  model_planning_available: true,
  ...patch,
});

const stubs = {
  Button: {
    props: ["label", "disabled", "loading"],
    emits: ["click"],
    template: '<button :disabled="disabled" @click="$emit(\'click\', $event)">{{ label }}</button>',
  },
  Dropdown: {
    props: ["modelValue", "options", "optionLabel", "optionValue", "placeholder"],
    emits: ["update:modelValue"],
    template:
      '<select :value="modelValue || \'\'" @change="$emit(\'update:modelValue\', $event.target.value)"><option value="">{{ placeholder }}</option><option v-for="option in options" :key="option.value" :value="option.value">{{ option.label }}</option></select>',
  },
  Textarea: {
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)"></textarea>',
  },
  InputText: {
    props: ["modelValue"],
    emits: ["update:modelValue"],
    template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
};

function mountPanel(props: Partial<{ activeProject: ProjectSummary | null; isLocalMode: boolean; starting: boolean }> = {}) {
  return mount(StarterPanel, {
    props: { activeProject: null, isLocalMode: true, starting: false, ...props },
    global: { plugins: [PrimeVue], stubs },
  });
}

const project = (goalPlan: StarterPlan): ProjectSummary => ({
  id: 5,
  name: goalPlan.goal,
  description: null,
  parent_id: null,
  technique: null,
  sample_type: null,
  goal: goalPlan.goal,
  goal_plan: goalPlan,
  experiment_count: 0,
  workflow_count: 0,
  script_count: 0,
  model_count: 0,
  children_count: 0,
  version_count: 0,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
});

describe("StarterPanel", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    window.localStorage.clear();
    adapter.fetchStarterOverview.mockResolvedValue(overview());
    adapter.planStarterGoal.mockResolvedValue(PLAN);
    adapter.fetchStarterProgress.mockResolvedValue({
      project_id: 5,
      has_project: true,
      has_data: true,
      has_workflow: false,
      has_preprocessing: false,
      has_executed: false,
      has_model: false,
      next_step: "workflow",
    });
  });

  it("prefills the suggested goal on first run and reports the overview", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toMatch(/^Smooth my spectra/);
    expect(wrapper.emitted("overview")?.[0]?.[0]).toMatchObject({ is_first_run: true });
  });

  it("prefills the user's last goal when there is one", async () => {
    adapter.fetchStarterOverview.mockResolvedValue(overview({ is_first_run: false, last_goal: "Find peaks in Raman" }));
    const wrapper = mountPanel();
    await flushPromises();
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("Find peaks in Raman");
  });

  it("plans a goal, explains the suggested dataset and starts with it", async () => {
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get(".goal-example").trigger("click");
    expect((wrapper.get("textarea").element as HTMLTextAreaElement).value).toBe("Find the peaks in my spectra");
    await wrapper.get("textarea").setValue("Predict moisture in my corn NIR spectra");
    await wrapper.get('[data-test="starter-plan"]').trigger("click");
    await flushPromises();

    expect(adapter.planStarterGoal).toHaveBeenCalledWith("Predict moisture in my corn NIR spectra");
    const result = wrapper.get('[data-test="starter-plan-result"]');
    expect(result.text()).toContain("Predict a value from spectra");
    expect(result.text()).toContain("Starter workflow: PLS Calibration");
    expect(result.text()).toContain("Suggested by the assistant");
    expect(result.text()).toContain("Corn moisture matches your goal.");
    expect(result.text()).toContain("needs the provider's original file");
    const options = result.findAll("select option").map((option) => option.text());
    expect(options).toEqual([
      "Choose a dataset",
      "Eigenvector Corn M5 · Needs file import",
      "Grain batch · Your dataset",
      "I'll import my own files",
    ]);

    // Steps are a click-through: the first is open, the others expand on click.
    const toggles = result.findAll(".goal-plan__step-toggle");
    expect(toggles[0].attributes("aria-expanded")).toBe("true");
    await toggles[2].trigger("click");
    expect(toggles[2].attributes("aria-expanded")).toBe("true");
    expect(toggles[0].attributes("aria-expanded")).toBe("false");

    await result.get("select").setValue("experiment:7");
    await wrapper.get('[data-test="starter-ready"]').trigger("click");
    expect(wrapper.emitted("start")?.[0]?.[0]).toEqual({
      plan: PLAN,
      name: "Predict moisture in my corn NIR spectra",
      dataset: PLAN.dataset_options[1],
    });
  });

  it("requires a dataset outside local mode", async () => {
    adapter.planStarterGoal.mockResolvedValue({ ...PLAN, dataset: null, dataset_options: [] });
    const wrapper = mountPanel({ isLocalMode: false });
    await flushPromises();
    await wrapper.get('[data-test="starter-plan"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-test="starter-ready"]').attributes("disabled")).toBeDefined();
    expect(wrapper.text()).toContain("No compatible dataset is available yet");
  });

  it("starts with own files in local mode when no dataset is chosen", async () => {
    adapter.planStarterGoal.mockResolvedValue({ ...PLAN, dataset: null, dataset_options: [] });
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get('[data-test="starter-plan"]').trigger("click");
    await flushPromises();
    await wrapper.get('[data-test="starter-ready"]').trigger("click");
    expect(wrapper.emitted("start")?.[0]?.[0]).toMatchObject({ dataset: null });
  });

  it("shows a planning error", async () => {
    adapter.planStarterGoal.mockRejectedValue(new Error("Planner offline"));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get('[data-test="starter-plan"]').trigger("click");
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain("Planner offline");
  });

  it("tracks the active project's goal as a live checklist", async () => {
    const runAction = vi.spyOn(useGuidanceStore(), "runAction").mockResolvedValue(true);
    const wrapper = mountPanel({ activeProject: project(PLAN) });
    await flushPromises();

    expect(adapter.fetchStarterProgress).toHaveBeenCalledWith(5);
    const active = wrapper.get('[data-test="starter-active-goal"]');
    expect(active.text()).toContain("Predict moisture in my corn NIR spectra");
    expect(wrapper.get('[data-test="starter-step-data"]').classes()).toContain("goal-step--done");
    const current = wrapper.get('[data-test="starter-step-workflow"]');
    expect(current.classes()).toContain("goal-step--current");
    expect(current.text()).toContain("Workflow detail");
    await current.get("button").trigger("click");
    expect(runAction).toHaveBeenCalledWith("open_workflow");

    // Only the current step offers Go; later steps wait their turn.
    expect(wrapper.get('[data-test="starter-step-review"]').find("button").exists()).toBe(false);
    expect(active.text()).not.toContain("Corn moisture");
  });

  it("finishes a step without a progress signal once the user opens it", async () => {
    adapter.fetchStarterProgress.mockResolvedValue({
      project_id: 5,
      has_project: true,
      has_data: true,
      has_workflow: true,
      has_preprocessing: false,
      has_executed: true,
      has_model: false,
      next_step: "review",
    });
    const runAction = vi.spyOn(useGuidanceStore(), "runAction").mockResolvedValue(true);
    const wrapper = mountPanel({ activeProject: { ...project(PLAN), name: "Corn moisture" } });
    await flushPromises();

    expect(wrapper.get('[data-test="starter-active-goal"]').text()).toContain("Predict a value from spectra · Corn moisture");
    const review = wrapper.get('[data-test="starter-step-review"]');
    expect(review.classes()).toContain("goal-step--current");
    await review.get("button").trigger("click");
    expect(runAction).toHaveBeenLastCalledWith("view_results");
    expect(wrapper.get('[data-test="starter-step-review"]').classes()).toContain("goal-step--done");
    expect(JSON.parse(window.localStorage.getItem("sherpa:starter-visited:5") || "[]")).toEqual(["review"]);
    expect(wrapper.text()).toContain("Every step is done.");
  });
});
