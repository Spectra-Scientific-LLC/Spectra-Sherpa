import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import Panel from "@/components/ResizableInspectorPanel.vue";

describe("Inspector resizing", () => {
  it("expands leftward and clamps pointer resizing at the default and double widths", async () => {
    const wrapper = mount(Panel, { props: { modelValue: 1 } });
    const handle = wrapper.get('[role="separator"]');
    Object.assign(handle.element, { setPointerCapture: vi.fn(), hasPointerCapture: () => false });
    vi.spyOn(wrapper.element, "getBoundingClientRect").mockReturnValue({ width: 320 } as DOMRect);
    await handle.trigger("pointerdown", { button: 0, pointerId: 1, clientX: 1000 });
    await handle.trigger("pointermove", { pointerId: 1, clientX: 840 });
    await handle.trigger("pointermove", { pointerId: 1, clientX: 0 });
    await handle.trigger("pointermove", { pointerId: 1, clientX: 1200 });
    expect(wrapper.emitted("update:modelValue")).toEqual([[1.5], [2], [1]]);
    await handle.trigger("pointerup", { pointerId: 1 });
    await handle.trigger("pointermove", { pointerId: 1, clientX: 500 });
    expect(wrapper.emitted("update:modelValue")).toHaveLength(3);
  });
  it("supports keyboard limits and reset", async () => {
    const wrapper = mount(Panel, { props: { modelValue: 1 } });
    const handle = wrapper.get('[role="separator"]');
    await handle.trigger("keydown", { key: "ArrowRight" });
    await handle.trigger("keydown", { key: "End" });
    await handle.trigger("keydown", { key: "Home" });
    expect(wrapper.emitted("update:modelValue")).toEqual([[1], [2], [1]]);
  });
});
