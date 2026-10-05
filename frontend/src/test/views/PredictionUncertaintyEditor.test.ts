import { describe, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { defineComponent, ref } from "vue";
import Editor from "@/views/deploy/PredictionUncertaintyEditor.vue";
vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const record = { schema_version: "spectrasherpa.prediction-uncertainty/1", record_digest: "a".repeat(64), intended_population: "Summer fuels", alpha: 0.1, reference_method: { method_id: "reference" } };
function setup() {
  return mount(defineComponent({ components: { Editor }, setup() {
    return { value: ref(null), valid: ref(true), model: ref(1) };
  }, template: '<Editor v-model="value" :canonical-artifact-id="model" @valid="valid = $event" />' }));
}
async function select(wrapper: ReturnType<typeof setup>, value: unknown) {
  const input = wrapper.find('input[type="file"]');
  Object.defineProperty(input.element, "files", { configurable: true, value: [{ size: 100, text: async () => JSON.stringify(value) }] });
  await input.trigger("change");
  await flushPromises();
}
describe("uncertainty declaration", () => {
  it("requires acceptance for each imported population and clears back to point only", async () => {
    const wrapper = setup();
    await select(wrapper, record);
    expect(wrapper.vm.valid).toBe(false);
    await wrapper.find('input[type="checkbox"]').setValue(true);
    expect(wrapper.vm.valid).toBe(true);
    await select(wrapper, { ...record, intended_population: "Winter fuels" });
    expect(wrapper.vm.valid).toBe(false);
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await wrapper.findAll("button").find(b => b.text() === "Use point predictions only")!.trigger("click");
    await flushPromises();
    expect(wrapper.vm.value).toBe(null);
    expect(wrapper.vm.valid).toBe(true);
  });
  it("clears population approval when the model changes", async () => {
    const wrapper = setup();
    await select(wrapper, record);
    await wrapper.find('input[type="checkbox"]').setValue(true);
    wrapper.vm.model = 2;
    await flushPromises();
    expect(wrapper.vm.value).toBe(null);
    expect(wrapper.vm.valid).toBe(true);
  });
  it("does not silently retain accepted intervals after a failed selection", async () => {
    const wrapper = setup();
    await select(wrapper, record);
    await wrapper.find('input[type="checkbox"]').setValue(true);
    await select(wrapper, { invalid: true });
    expect(wrapper.vm.valid).toBe(false);
    expect(wrapper.find('[role="alert"]').text()).toContain("Not a prediction interval");
    expect(wrapper.find('input[type="checkbox"]').attributes("disabled")).toBeDefined();
  });
});
