import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PLSDAPermutationSummary from "@/components/results/PLSDAPermutationSummary.vue";

const complete = {
  schema_version: "spectrasherpa-plsda-response-permutation/1",
  status: "complete",
  scope: "calibration_development_only_no_independent_test",
  metric: "balanced_accuracy",
  model_state_sha256: "a".repeat(64),
  observed: 0.9,
  null: Array.from({ length: 19 }, () => ({
    balanced_accuracy: 0.5,
    selected_components: 1,
    split_digest: "b".repeat(64),
  })),
  permutations_requested: 19,
  permutations_successful: 19,
  exceedances: 0,
  p_value: 1 / 20,
  exchangeability_block_column: "instrument",
  observed_reselected_components: 1,
  saved_model_components: 2,
  component_search_maximum: 2,
  folds: 3,
  seed: 42,
  n_calibration: 30,
  n_classes: 2,
  n_units: 30,
  class_counts: { A: 15, B: 15 },
};

describe("PLSDAPermutationSummary", () => {
  it("shows the null distribution and qualifies its interpretation", () => {
    const view = mount(PLSDAPermutationSummary, { props: { record: complete } });
    expect(view.text()).toContain("19 seeded label shuffles");
    expect(view.text()).toContain("Observed label search selected 1 latent variable");
    expect(view.text()).toContain("connected saved model has 2 latent variables");
    expect(view.text()).toContain("same component search was repeated for every shuffle");
    expect(view.text()).toContain("3 stratified folds, seed 42, 30 calibration rows");
    expect(view.findAll("rect.null-bar")).toHaveLength(10);
    expect(view.find("svg").attributes("aria-label")).toContain("19 shuffled-label");
    expect(view.text()).toContain("does not establish independent external validity");
    expect(view.text()).toContain("CV-ANOVA: unavailable");
    expect(view.text()).toContain("recorded instrument blocks");
  });

  it("refuses partial or inconsistent evidence", async () => {
    const view = mount(PLSDAPermutationSummary, {
      props: { record: { ...complete, exceedances: 5 } },
    });
    expect(view.text()).toContain("unavailable or inconsistent");
    expect(view.find("svg").exists()).toBe(false);
    await view.setProps({ record: { ...complete, seed: null } });
    expect(view.text()).toContain("unavailable or inconsistent");
    await view.setProps({ record: { ...complete, null: [{ balanced_accuracy: 0.5 }] } });
    expect(view.find("svg").exists()).toBe(false);
    expect(mount(PLSDAPermutationSummary, { props: { record: { rmse: 1 } } }).text()).toBe("");
  });
});
