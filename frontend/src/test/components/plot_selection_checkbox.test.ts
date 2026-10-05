import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import PlotSelectionCheckbox from "@/components/data/PlotSelectionCheckbox.vue";

describe("PlotSelectionCheckbox", () => {
  it("exposes a real mixed checkbox state for a partial dataset selection", () => {
    const wrapper = mount(PlotSelectionCheckbox, {
      props: { checked: false, partial: true, label: "Plot some files" },
    });
    const input = wrapper.get("input").element as HTMLInputElement;

    expect(input.indeterminate).toBe(true);
    expect(input.getAttribute("aria-checked")).toBe("mixed");
    expect(wrapper.find(".pi-minus").exists()).toBe(true);
  });

  it("emits the next checked state", async () => {
    const wrapper = mount(PlotSelectionCheckbox, {
      props: { checked: false, label: "Plot file" },
    });

    await wrapper.get("input").setValue(true);
    expect(wrapper.emitted("toggle")).toEqual([[true]]);
  });
});
