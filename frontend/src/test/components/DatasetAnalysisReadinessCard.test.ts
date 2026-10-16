import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import DatasetAnalysisReadinessCard from "@/views/data/DatasetAnalysisReadinessCard.vue";

const readiness = {
  profile: null, template_count: 0,
  counts: { compatible: 0, needs_target: 1, needs_source: 0, incompatible: 0, pending: 0, unavailable: 0 },
  decisions: [], diagnostics: [],
};

describe("response-selection readiness", () => {
  it("distinguishes available reference values from a selected response", async () => {
    const wrapper = mount(DatasetAnalysisReadinessCard, {
      props: { readiness, selectedTarget: "", targetOptions: [
        { label: "Carbon dioxide", value: "CO2", type: "continuous", detail: "ppm" },
      ] },
      global: { stubs: { Button: true, Dropdown: true } },
    });
    expect(wrapper.text()).toContain("Reference values are available. Select a response");
    await wrapper.setProps({ selectedTarget: "CO2" });
    expect(wrapper.text()).not.toContain("Reference values are available.");
    await wrapper.setProps({ selectedTarget: "", targetOptions: [] });
    expect(wrapper.text()).not.toContain("Reference values are available.");
  });
});
