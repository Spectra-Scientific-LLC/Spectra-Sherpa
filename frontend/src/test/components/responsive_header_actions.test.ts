import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import ResponsiveHeaderActions from "@/components/ResponsiveHeaderActions.vue";

describe("ResponsiveHeaderActions", () => {
  it.each([false, true])("shows a working menu action on the Actions trigger (%s)", (loading) => {
    const wrapper = mount(ResponsiveHeaderActions, {
      props: { items: [{ label: "Freeze and evaluate", loading }, { label: "Export" }] },
      global: { plugins: [PrimeVue], stubs: { TieredMenu: true } },
    });
    const trigger = wrapper.get(".responsive-header-actions__trigger");
    expect(trigger.text()).toContain("Actions");
    expect(trigger.attributes("data-p-disabled") === "true" || trigger.attributes("disabled") !== undefined).toBe(loading);
    wrapper.unmount();
  });
});
