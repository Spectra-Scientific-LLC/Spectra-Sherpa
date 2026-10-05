import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import WorkbookSheetTabs from "@/components/WorkbookSheetTabs.vue";
import type { WorkbookSheet } from "@/stores/workbook";

const sheets: WorkbookSheet[] = [
  { workflowId: 1, name: "PCA Analysis", tabColor: "#3b82f6", sheetOrder: 0 },
  { workflowId: 2, name: "PLS Model", tabColor: "#22c55e", sheetOrder: 1 },
];

const mountTabs = (
  overrides: Partial<{
    sheets: WorkbookSheet[];
    activeIndex: number;
    activeWorkflowHash: string | null;
  }> = {},
) =>
  mount(WorkbookSheetTabs, {
    props: {
      sheets,
      activeIndex: 0,
      hasUnsavedChanges: false,
      ...overrides,
    },
    global: {
      stubs: {
        Dialog: { template: "<div><slot /><slot name='footer' /></div>" },
        Button: {
          template: "<button type='button'><slot />{{ label }}</button>",
          props: ["label"],
        },
      },
    },
  });

describe("WorkbookSheetTabs", () => {
  it("exports the right-clicked sheet, including an inactive tab, and closes the menu", async () => {
    const wrapper = mountTabs();
    await wrapper.findAll(".sheet-tab")[1].trigger("contextmenu");
    const action = wrapper
      .findAll(".sheet-context-menu button")
      .find((button) => button.text().includes("Save canvas as PNG"));
    expect(action).toBeDefined();
    await action!.trigger("click");
    expect(wrapper.emitted("export-png")).toEqual([[1]]);
    expect(wrapper.find(".sheet-context-menu").exists()).toBe(false);
  });
  it("reverts inline rename on Escape", async () => {
    const wrapper = mountTabs();

    await wrapper.findAll(".sheet-tab")[0].trigger("dblclick");
    const input = wrapper.find(".sheet-rename-input");
    await input.setValue("Changed");
    await input.trigger("keydown", { key: "Escape" });

    expect(wrapper.emitted("rename")).toBeUndefined();
    expect(wrapper.text()).toContain("PCA Analysis");
  });

  it("disables delete when only one sheet remains", async () => {
    const wrapper = mountTabs({ sheets: [sheets[0]] });

    await wrapper.find(".sheet-tab").trigger("contextmenu", {
      clientX: 10,
      clientY: 20,
    });

    expect(wrapper.find(".danger").attributes("disabled")).toBeDefined();
  });

  it("uses the canvas background without a rim for uncolored sheets", () => {
    const wrapper = mountTabs({
      sheets: [{ workflowId: 3, name: "Sheet 3", tabColor: null, sheetOrder: 0 }],
    });

    const style = wrapper.find(".sheet-tab").attributes("style");
    expect(style).toContain("background-color: #1e293b");
    expect(style).not.toContain("box-shadow");
  });

  it("offers the active workflow integrity SHA only in its tab context menu", async () => {
    const hash = "a".repeat(64);
    const wrapper = mountTabs({ activeWorkflowHash: hash });

    await wrapper.findAll(".sheet-tab")[1].trigger("contextmenu");
    expect(wrapper.text()).not.toContain("Copy SHA");

    await wrapper.findAll(".sheet-tab")[0].trigger("contextmenu");
    const copy = wrapper
      .findAll(".sheet-context-menu button")
      .find((button) => button.text().includes("Copy SHA"));
    expect(copy).toBeDefined();
    await copy?.trigger("click");

    expect(wrapper.emitted("copy-integrity")).toEqual([[hash]]);
  });
});
