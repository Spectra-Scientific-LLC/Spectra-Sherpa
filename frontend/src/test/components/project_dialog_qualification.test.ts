import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectDialog from "@/components/ProjectDialog.vue";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api", () => ({ api: { get } }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({
  appMode: { value: "enterprise" }, siteProfile: { value: "pro" },
}) }));
const option = { subscription_id: 42, workspace_id: 21, label: "Lab / Team" };
function mountDialog() {
  return mount(ProjectDialog, { props: { visible: true }, global: { stubs: {
    Dialog: { template: "<div><slot/><slot name='footer'/></div>" },
    Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{ label }}</button>' },
    Dropdown: { props: ["modelValue", "options"], template: '<select />' },
    InputText: { props: ["modelValue"], emits: ["update:modelValue"], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
    Textarea: true,
  } } });
}
describe("project creation workspace admission", () => {
  beforeEach(() => { get.mockReset(); });
  it("sends the server-issued authority with a single available workspace", async () => {
    get.mockResolvedValue({ data: { options: [option] } });
    const wrapper = mountDialog();
    await flushPromises();
    await wrapper.get("input").setValue("New scientific project");
    await wrapper.findAll("button")[1].trigger("click");
    expect(wrapper.emitted("create")?.[0]?.[0]).toMatchObject({
      commercial_subscription_id: 42, commercial_workspace_id: 21, name: "New scientific project",
    });
  });
  it("requires an explicit choice when two workspaces are available", async () => {
    get.mockResolvedValue({ data: { options: [option, { ...option, subscription_id: 43 }] } });
    const wrapper = mountDialog();
    await flushPromises();
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("create")).toBeUndefined();
  });
  it("does not enable creation when workspace retrieval fails", async () => {
    get.mockRejectedValue(new Error("unavailable"));
    const wrapper = mountDialog();
    await flushPromises();
    expect(wrapper.text()).toContain("Unable to load workspaces");
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
  });
});
