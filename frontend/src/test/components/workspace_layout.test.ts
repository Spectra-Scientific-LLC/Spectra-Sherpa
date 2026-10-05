import { mount } from "@vue/test-utils";
import { h, nextTick } from "vue";
import PrimeVue from "primevue/config";
import TabPanel from "primevue/tabpanel";
import { describe, expect, it, vi } from "vitest";
import WorkspaceTabs from "@/components/workspace/WorkspaceTabs.vue";
import WorkspaceHeader from "@/components/workspace/WorkspaceHeader.vue";
import WorkspaceContext from "@/components/workspace/WorkspaceContext.vue";
import WorkspaceContextItem from "@/components/workspace/WorkspaceContextItem.vue";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";

describe("workspace presentation contract", () => {
  it("keeps stable tab identity and PrimeVue keyboard/disabled semantics", async () => {
    const select = vi.fn();
    const view = mount(WorkspaceTabs, {
      attachTo: document.body,
      props: {
        modelValue: "import",
        tabIds: ["import", "blocked", "my-dataset"],
        "onUpdate:modelValue": select,
      },
      slots: {
        default: () => [
          h(TabPanel, { header: "Import" }, () => "Sources"),
          h(TabPanel, { header: "Library", disabled: true }, () => "Unavailable"),
          h(TabPanel, { header: "My Dataset" }, () => "Files"),
        ],
      },
      global: { plugins: [PrimeVue] },
    });
    const tabs = view.findAll('[role="tab"]');
    expect(tabs[0].attributes("aria-selected")).toBe("true");
    await tabs[1].trigger("click");
    expect(select).not.toHaveBeenCalled();
    await tabs[0].trigger("keydown", { code: "End" });
    expect(document.activeElement).toBe(tabs[2].element);
    await tabs[2].trigger("keydown", { code: "Enter" });
    expect(select).toHaveBeenLastCalledWith("my-dataset");
    await view.setProps({ modelValue: "my-dataset" });
    expect(tabs[2].attributes("aria-selected")).toBe("true");
    expect(view.get('[role="tabpanel"]:not([style*="display: none"])').text()).toBe("Files");
    view.unmount();
  });

  it("keeps settings and authority badges alongside responsive header commands", async () => {
    const run = vi.fn();
    const view = mount(WorkspaceHeader, {
      props: { title: "Workflow", actions: [{ label: "Run", command: run }] },
      slots: {
        default: () => h("button", { onClick: run }, "Run"),
        badge: "Retained trial",
        after: () => h("button", { "aria-label": "Settings" }, "Settings"),
      },
      global: { plugins: [PrimeVue] },
    });
    expect(view.get("h1").text()).toBe("Workflow");
    expect(view.text()).toContain("Retained trial");
    expect(view.get('[aria-label="Settings"]').exists()).toBe(true);
    await view.get(".responsive-header-actions__full button").trigger("click");
    expect(run).toHaveBeenCalledOnce();
    view.unmount();
  });

  it("replaces resource context when the active sheet changes", async () => {
    const view = mount(WorkspaceContextItem, {
      props: { label: "Active Data", value: "Corn", detail: "Corn m5 · protein" },
    });
    expect(view.get("strong").attributes("title")).toBe("Corn m5 · protein");
    await view.setProps({ value: "Wine", detail: "Wine · classes" });
    expect(view.text()).not.toContain("Corn");
    expect(view.get("strong").text()).toBe("Wine");
    const context = mount(WorkspaceContext, {
      props: { label: "Workflow workspace context", layout: "workflow" },
    });
    expect(context.attributes("aria-label")).toBe("Workflow workspace context");
    context.unmount();
    view.unmount();
  });

  it("distinguishes a retryable error from loading without losing the recovery action", async () => {
    const retry = vi.fn();
    const view = mount(WorkspaceState, {
      props: { kind: "error", message: "Catalog unavailable" },
      slots: { default: () => h("button", { onClick: retry }, "Retry") },
    });
    expect(view.attributes("role")).toBe("alert");
    await view.get("button").trigger("click");
    expect(retry).toHaveBeenCalledOnce();
    await view.setProps({ kind: "loading", message: "Loading catalog" });
    await nextTick();
    expect(view.attributes("aria-busy")).toBe("true");
    view.unmount();
  });
});
