import { mount } from "@vue/test-utils";
import PrimeVue from "primevue/config";
import { describe, expect, it, vi } from "vitest";
import RowActions from "@/components/RowActions.vue";

describe("row actions", () => {
  it("keeps secondary and destructive actions behind one labelled button, dangerous ones last", () => {
    const remove = vi.fn();
    const download = vi.fn();
    const wrapper = mount(RowActions, {
      props: { subject: "Run #7", actions: [
        { label: "Delete run…", icon: "pi pi-trash", danger: true, command: remove },
        { label: "Download file", icon: "pi pi-download", command: download },
      ] },
      global: { plugins: [PrimeVue] },
    });
    expect(wrapper.findAll("button")).toHaveLength(1);
    expect(wrapper.get("button").attributes("aria-label")).toBe("More actions for Run #7");
    const items = (wrapper.findComponent({ name: "Menu" }).props("model") as Array<{ label: string; class?: string; command: () => void }>);
    expect(items.map((item) => item.label)).toEqual(["Download file", "Delete run…"]);
    expect(items[1].class).toBe("row-actions__danger");
    items[1].command();
    expect(remove).toHaveBeenCalledOnce();
  });
});
