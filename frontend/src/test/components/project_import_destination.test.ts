import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectImportDestinationDialog from "@/components/ProjectImportDestinationDialog.vue";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/api", () => ({ api: { get } }));
const option = { subscription_id: 42, workspace_id: 21, label: "Lab / Team" };
function mountDialog() {
  return mount(ProjectImportDestinationDialog, { props: { visible: true }, global: { stubs: {
    Dialog: { template: "<div><slot/><slot name='footer'/></div>" },
    Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{ label }}</button>' },
    Dropdown: { name: "Dropdown", props: ["modelValue", "options"], emits: ["update:modelValue"], template: '<select />' },
  } } });
}
describe("Pro archive destination admission", () => {
  beforeEach(() => { get.mockReset(); });
  it("offers a single authorized destination and forwards its exact IDs", async () => {
    get.mockResolvedValue({ data: { options: [option] } });
    const wrapper = mountDialog();
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
    await flushPromises();
    await wrapper.findAll("button")[1].trigger("click");
    expect(get).toHaveBeenCalledWith("/commercial/projects/options");
    expect(wrapper.emitted("choose")?.[0]).toEqual([option]);
  });
  it("requires an explicit selection for multiple destinations", async () => {
    const other = { ...option, subscription_id: 43 };
    get.mockResolvedValue({ data: { options: [option, other] } });
    const wrapper = mountDialog();
    await flushPromises();
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
    wrapper.findComponent({ name: "Dropdown" }).vm.$emit("update:modelValue", other);
    await flushPromises();
    await wrapper.findAll("button")[1].trigger("click");
    expect(wrapper.emitted("choose")?.[0]).toEqual([other]);
  });
  it.each([false, true])("refuses unavailable options (error=%s)", async (failed) => {
    if (failed) get.mockRejectedValue(new Error("Unavailable"));
    else get.mockResolvedValue({ data: { options: [] } });
    const wrapper = mountDialog();
    await flushPromises();
    expect(wrapper.get('[role="alert"]').text()).toContain(failed ? "Unable to load" : "No authorized");
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("choose")).toBeUndefined();
  });
  it("does not retain options when a pending dialog is closed", async () => {
    let resolve!: (value: unknown) => void;
    get.mockReturnValue(new Promise((done) => { resolve = done; }));
    const wrapper = mountDialog();
    await wrapper.setProps({ visible: false });
    resolve({ data: { options: [option] } });
    await flushPromises();
    expect(wrapper.findAll("button")[1].attributes("disabled")).toBeDefined();
    expect(wrapper.emitted("choose")).toBeUndefined();
  });
});
