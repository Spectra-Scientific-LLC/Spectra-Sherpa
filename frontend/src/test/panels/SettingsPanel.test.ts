import { mount } from "@vue/test-utils";
import { describe, it, expect } from "vitest";
import SettingsPanel from "@/views/workflow-builder/node-detail/panels/SettingsPanel.vue";

function factory(props: Partial<InstanceType<typeof SettingsPanel>["$props"]> = {}) {
  return mount(SettingsPanel, {
    props: {
      expanded: true,
      settingsCount: 0,
      params: [],
      localParams: {},
      hasValidationErrors: false,
      displayedValidationErrors: [],
      getParamError: () => null,
      ...props,
    },
    global: {
      stubs: {
        Transition: false,
        InputNumber: true,
        InputText: true,
        InputSwitch: true,
        Dropdown: true,
        Button: {
          props: ["label"],
          template: '<button :aria-label="label" @click="$emit(\'click\')"><slot/></button>',
        },
      },
    },
  });
}

describe("SettingsPanel", () => {
  it("renders empty state when there are no params", () => {
    const w = factory();
    expect(w.text()).toContain("No configurable parameters");
  });

  it("renders the validation error banner when hasValidationErrors is true", () => {
    const w = factory({
      hasValidationErrors: true,
      displayedValidationErrors: [
        { param_name: "n_components", message: "must be >= 1" },
        { param_name: "tol", message: "must be > 0" },
      ],
    });
    expect(w.find(".validation-error-banner").exists()).toBe(true);
    expect(w.text()).toContain("2 validation errors");
    expect(w.text()).toContain("n_components");
    expect(w.text()).toContain("must be >= 1");
  });

  it("renders one param-field per param", () => {
    const w = factory({
      params: [
        { name: "n_components", label: "Components", type: "number", required: true },
        { name: "scale", label: "Auto-scale", type: "boolean" },
        { name: "mode", label: "Mode", type: "select", options: [] },
      ],
      localParams: { n_components: 2, scale: true, mode: "auto" },
    });
    expect(w.findAll(".param-field")).toHaveLength(3);
    expect(w.text()).toContain("Components");
    expect(w.text()).toContain("Auto-scale");
  });

  it("marks a field with `has-error` when getParamError returns a message", () => {
    const w = factory({
      params: [{ name: "x", label: "X", type: "number" }],
      localParams: { x: 0 },
      getParamError: (name: string) => (name === "x" ? "bad" : null),
    });
    expect(w.find(".param-field").classes()).toContain("has-error");
    expect(w.text()).toContain("bad");
  });

  it("emits toggle / reset / updateParam correctly", async () => {
    const w = factory({
      params: [{ name: "x", label: "X", type: "number" }],
      localParams: { x: 1 },
    });
    await w.find(".section-header").trigger("click");
    expect(w.emitted("toggle")).toBeTruthy();

    await w.find('button[aria-label="Reset to Defaults"]').trigger("click");
    expect(w.emitted("reset")).toBeTruthy();

    // InputNumber v-model bridge: simulate update:model-value from the stub
    const input = w.findComponent({ name: "InputNumber" });
    input.vm.$emit("update:model-value", 5);
    expect(w.emitted("updateParam")).toEqual([["x", 5]]);
  });

  it("shows the param count badge when settingsCount > 0", () => {
    const w = factory({ settingsCount: 4 });
    expect(w.find(".section-badge").text()).toBe("4 parameters");
  });
});
