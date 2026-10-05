import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import RepeatedValidationSummary from "@/components/results/RepeatedValidationSummary.vue";

describe("RepeatedValidationSummary", () => {
  it("displays the original population and repeat spread without pooled accuracy", () => {
    const view = mount(RepeatedValidationSummary, { props: { record: {
      schema_version: "spectrasherpa.repeated-nested-validation/1",
      n_repeats: 3, n_rows: 36, n_groups: 12, root_seed: 42,
      interpretation: "Repeated predictions are not independent observations.",
      distributions: { rmsecv: { mean: 2, std_across_repeats: 1, minimum: 1, maximum: 3, per_repeat: [1, 2, 3] } },
    } } });
    expect(view.text()).toContain("36 original rows");
    expect(view.text()).toContain("12 groups");
    expect(view.text()).toContain("SD across repeats");
    expect(view.text()).toContain("not independent observations");
    expect(view.text()).not.toContain("108");
  });
  it("does not interpret ordinary validation as repeated validation", () => {
    expect(mount(RepeatedValidationSummary, { props: { record: { rmse: 1 } } }).text()).toBe("");
  });
});
