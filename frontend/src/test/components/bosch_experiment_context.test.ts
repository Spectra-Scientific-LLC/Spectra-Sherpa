import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import BoschExperimentContext from "@/views/data/BoschExperimentContext.vue";
import catalog from "../../../../src/spectra_sherpa/data/bosch_netcdf/experiment_context.json";
function context() {
  return {
    ...catalog,
    schema_version: "spectrasherpa.bosch-experiment-context/1",
    selected_lot: {
      ...catalog.lots_by_date["2024-08-05"],
      experiment_date: "2024-08-05",
      wafer_number: 6,
    },
  };
}
describe("BOSCH experiment context", () => {
  it("shows verified lot settings, full recipe and both variable endpoint cleans", () => {
    const wrapper = mount(BoschExperimentContext, { props: { context: context() } });
    expect(wrapper.text()).toContain("Blank SiO₂ wafer");
    expect(wrapper.text()).toContain("6 of 10 planned");
    expect(wrapper.text()).toContain("Dummy BOSCH run: 30 min");
    expect(wrapper.text().match(/variable duration/g)).toHaveLength(2);
    expect(wrapper.text()).toContain("100 BOSCH cycles per wafer");
    expect(wrapper.text()).toContain("Break between repetitions: 4 min");
  });
  it("keeps the reference protocol distinct from an unknown actual lot", () => {
    const wrapper = mount(BoschExperimentContext, {
      props: { context: { ...context(), selected_lot: null } },
    });
    expect(wrapper.text()).toContain("has not been matched");
    expect(wrapper.find(".lot-facts").exists()).toBe(false);
  });
  it("does not render malformed context", () => {
    const wrapper = mount(BoschExperimentContext, {
      props: { context: { schema_version: "spectrasherpa.bosch-experiment-context/1" } },
    });
    expect(wrapper.find("section").exists()).toBe(false);
  });
});
