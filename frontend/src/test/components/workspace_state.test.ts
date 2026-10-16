import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";

describe("WorkspaceState", () => {
  it("announces errors as alerts and keeps their actions", () => {
    const view = mount(WorkspaceState, {
      props: { kind: "error", message: "Could not load runs." },
      slots: { default: "<button>Retry</button>" },
    });
    expect(view.attributes("role")).toBe("alert");
    expect(view.attributes("aria-busy")).toBe("false");
    expect(view.text()).toContain("Could not load runs.");
    expect(view.get("button").text()).toBe("Retry");
  });

  it("marks loading as a busy status with a decorative spinner", () => {
    const view = mount(WorkspaceState, { props: { kind: "loading", message: "Loading runs…" } });
    expect(view.attributes("role")).toBe("status");
    expect(view.attributes("aria-busy")).toBe("true");
    expect(view.get(".pi-spinner").attributes("aria-hidden")).toBe("true");
  });

  it("keeps the inline layout by default and stacks hints in the page variant", () => {
    const inline = mount(WorkspaceState, { props: { kind: "empty", message: "Nothing here." } });
    expect(inline.classes()).not.toContain("workspace-state--page");
    expect(inline.find(".workspace-state__icon").exists()).toBe(false);

    const page = mount(WorkspaceState, {
      props: { kind: "empty", variant: "page", icon: "pi pi-eye", message: "No folder watches" },
      slots: { default: "<p>Create a folder watch.</p>" },
    });
    expect(page.attributes("role")).toBe("status");
    expect(page.classes()).toContain("workspace-state--page");
    expect(page.get(".workspace-state__icon").attributes("aria-hidden")).toBe("true");
    expect(page.get(".workspace-state__message").text()).toBe("No folder watches");
    expect(page.text()).toContain("Create a folder watch.");
  });
});
