import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import Help from "@/components/ParameterHelpLabel.vue";

describe("Parameter help", () => {
  it("opens only on click, toggles closed, and supports Escape dismissal", async () => {
    const wrapper = mount(Help, {
      props: {
        inputId: "method",
        label: "Method",
        description: "Reference-fitted scaling method.",
      },
    });
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    await wrapper.trigger("mouseenter");
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    await wrapper.trigger("mouseleave");
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    const button = wrapper.get("button");
    await button.trigger("focus");
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    await button.trigger("blur");
    await button.trigger("click");
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(true);
    expect(wrapper.get('[role="tooltip"]').text()).toBe("Reference-fitted scaling method.");
    await button.trigger("click");
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
    await button.trigger("click");
    await button.trigger("keydown", { key: "Escape" });
    expect(wrapper.find('[role="tooltip"]').exists()).toBe(false);
  });
});
