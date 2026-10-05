import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import PlateMap96Well from "@/components/PlateMap96Well.vue";

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("PlateMap96Well", () => {
  it("shows structured sample-table properties beside an assigned well", async () => {
    const wrapper = mount(PlateMap96Well, {
      attachTo: document.body,
      props: {
        showLegend: true,
        wells: [
          {
            well_position: "B03",
            label: "corn-001",
            assigned: true,
            details: [
              { label: "Source row", value: "0" },
              { label: "Included", value: "Yes" },
              { label: "moisture (continuous)", value: "10.0" },
              { label: "batch", value: "pilot-1" },
            ],
          },
        ],
      },
    });

    const assignedWell = wrapper.find(".well-assigned");
    vi.spyOn(assignedWell.element, "getBoundingClientRect").mockReturnValue({
      x: 380,
      y: 280,
      top: 280,
      right: 400,
      bottom: 300,
      left: 380,
      width: 20,
      height: 20,
      toJSON: () => ({}),
    });
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 400 });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 300 });
    expect(assignedWell.attributes("tabindex")).toBe("0");
    await assignedWell.trigger("mouseenter");

    const card = document.body.querySelector<HTMLElement>(".plate-well-hover-card");
    expect(card).not.toBeNull();
    expect(card?.textContent).toContain("B03");
    expect(card?.textContent).toContain("corn-001");
    expect(card?.textContent).toContain("Source row");
    expect(card?.textContent).toContain("moisture (continuous)");
    expect(card?.textContent).toContain("10.0");
    expect(card?.textContent).toContain("pilot-1");
    expect(card?.style.left).toBe("70px");
    expect(Number.parseInt(card?.style.top ?? "0", 10)).toBeGreaterThanOrEqual(12);
    expect(Number.parseInt(card?.style.top ?? "300", 10)).toBeLessThan(280);

    await assignedWell.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("well-click")).toEqual([["B03"]]);

    await assignedWell.trigger("mouseleave");
    expect(document.body.querySelector(".plate-well-hover-card")).toBeNull();
    wrapper.unmount();
  });

  it("renders duplicate physical assignments as an explicit collision", async () => {
    const wrapper = mount(PlateMap96Well, {
      attachTo: document.body,
      props: {
        showLegend: true,
        wells: [
          { well_position: "A01", label: "sample-1", assigned: true },
          { well_position: "A01", label: "sample-2", assigned: true },
        ],
      },
    });

    const collision = wrapper.find(".well-collision");
    expect(collision.exists()).toBe(true);
    expect(collision.text()).toContain("2 samples");
    expect(wrapper.text()).toContain("1 collision");
    await collision.trigger("mouseenter");

    const card = document.body.querySelector<HTMLElement>(".plate-well-hover-card");
    expect(card?.textContent).toContain("2 conflicting samples");
    expect(card?.textContent).toContain("sample-1");
    expect(card?.textContent).toContain("sample-2");
    wrapper.unmount();
  });

  it("lets an author select an empty well with the keyboard", async () => {
    const wrapper = mount(PlateMap96Well, {
      props: { wells: [], interactive: true },
    });

    const emptyWell = wrapper.find('[aria-label="A01"]');
    expect(emptyWell.attributes("tabindex")).toBe("0");
    await emptyWell.trigger("keydown", { key: " " });
    expect(wrapper.emitted("well-click")).toEqual([["A01"]]);
  });
});
