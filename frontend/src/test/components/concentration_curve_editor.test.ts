import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ConcentrationCurveEditor from "@/components/ConcentrationCurveEditor.vue";
import { seedConcentrationShape } from "@/utils/curve";

const mountEditor = (points = seedConcentrationShape(5)) =>
  mount(ConcentrationCurveEditor, {
    props: { points, color: "#123456", title: "Water" },
    global: { stubs: { InputNumber: true } },
  });

describe("ConcentrationCurveEditor", () => {
  it("renders one draggable handle per control point", () => {
    const wrapper = mountEditor(seedConcentrationShape(7));
    expect(wrapper.findAll("circle.conc-curve-editor__handle")).toHaveLength(7);
  });

  it("keyboard adjusts only y of the focused handle, x fixed", async () => {
    const wrapper = mountEditor([
      { x: 0, y: 0.05 },
      { x: 50, y: 0.5 },
      { x: 100, y: 0.5 },
    ]);
    const handles = wrapper.findAll("circle.conc-curve-editor__handle");

    await handles[1].trigger("keydown", { key: "ArrowUp", shiftKey: true });
    let emitted = wrapper.emitted("update:points")?.at(-1)?.[0] as { x: number; y: number }[];
    expect(emitted[1]).toEqual({ x: 50, y: 0.6 }); // shift = coarse 0.1 step
    expect(emitted[0]).toEqual({ x: 0, y: 0.05 }); // other handles untouched

    // Coarse step from y=0.05 underflows; clamped to 0, x preserved.
    await handles[0].trigger("keydown", { key: "ArrowDown", shiftKey: true });
    emitted = wrapper.emitted("update:points")?.at(-1)?.[0] as { x: number; y: number }[];
    expect(emitted[0]).toEqual({ x: 0, y: 0 });

    // Fine step (no shift) is 0.02.
    await handles[2].trigger("keydown", { key: "ArrowUp" });
    emitted = wrapper.emitted("update:points")?.at(-1)?.[0] as { x: number; y: number }[];
    expect(emitted[2].y).toBeCloseTo(0.52, 6);
  });

  it("ignores non-arrow keys", async () => {
    const wrapper = mountEditor();
    await wrapper.find("circle.conc-curve-editor__handle").trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("update:points")).toBeUndefined();
  });
});

describe("seedConcentrationShape", () => {
  it("clamps point count to [4,60] and pins x endpoints", () => {
    expect(seedConcentrationShape(2)).toHaveLength(4);
    expect(seedConcentrationShape(999)).toHaveLength(60);
    const shape = seedConcentrationShape(11);
    expect(shape[0].x).toBe(0);
    expect(shape[shape.length - 1].x).toBe(100);
    expect(shape.every((p) => p.y >= 0 && p.y <= 1)).toBe(true);
  });

  it("is a monotonic rising sine over the run (parity with backend seed)", () => {
    const shape = seedConcentrationShape(11);
    expect(shape[0].y).toBeCloseTo(0.15, 5);
    expect(shape[shape.length - 1].y).toBeCloseTo(0.85, 5);
    expect(shape[5].y).toBeCloseTo(0.5, 5);
  });
});
