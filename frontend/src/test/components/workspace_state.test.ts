import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import WorkspaceState from "@/components/workspace/WorkspaceState.vue";

describe("shared workspace states", () => {
  it.each([
    ["loading", "status", "true"],
    ["empty", "status", "false"],
    ["unavailable", "status", "false"],
    ["refusal", "alert", "false"],
    ["error", "alert", "false"],
  ] as const)("exposes %s without replacing its actionable content", (kind, role, busy) => {
    const wrapper = mount(WorkspaceState, {
      props: { kind, message: "Result status" },
      slots: { default: '<button type="button">Retry</button>' },
    });
    expect(wrapper.attributes("role")).toBe(role);
    expect(wrapper.attributes("aria-busy")).toBe(busy);
    expect(wrapper.text()).toContain("Result status");
    expect(wrapper.get("button").text()).toBe("Retry");
    wrapper.unmount();
  });
});
