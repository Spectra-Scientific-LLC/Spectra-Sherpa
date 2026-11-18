import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { ref } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import api from "@/api/client";
import RetainedArchiveInspector from "@/components/RetainedArchiveInspector.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

vi.mock("@/api/client", () => ({ default: { post: vi.fn(), get: vi.fn() } }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ config: ref({ limits: { maxFileSizeMB: 200 } }) }) }));
const report = {
  project_name: "Archived study", workflow_index: 0, workflow_count: 1,
  graph: { inspection_only: true, name: "Retained workflow", pack_binding: null,
    nodes: [{ node_id: "p", node_type: "pro.absent.record", label: "<img src=x onerror=alert(1)>",
      parameters: {}, parameters_json: '{"identity":9007199254740993,"unit":"mg/L"}' }], edges: [] },
};
let wrapper: VueWrapper;
beforeEach(() => {
  vi.clearAllMocks(); setActivePinia(createPinia());
  useAuthStore().user = { id: 7, username: "reader", is_active: true };
  vi.mocked(api.post).mockResolvedValue({ data: report });
  wrapper = mount(RetainedArchiveInspector, { global: { stubs: {
    RetainedArchiveResults: true,
    Dialog: { props: ["visible"], template: '<section v-if="visible"><slot /><slot name="footer" /></section>' },
    Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{ label }}</button>' },
  } } });
});
afterEach(() => wrapper.unmount());
async function choose() {
  const input = wrapper.get('input[type="file"]');
  Object.defineProperty(input.element, "files", { configurable: true, value: [new File(["fixture"], "retained.sherpa")] });
  await input.trigger("change");
  await flushPromises();
}
it("renders unknown nodes and exact parameters as escaped, read-only text", async () => {
  await choose();
  expect(wrapper.text()).toContain("pro.absent.record");
  expect(wrapper.text()).toContain("9007199254740993");
  expect(wrapper.text()).toContain("mg/L");
  expect(wrapper.find("img").exists()).toBe(false);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api.post).mock.calls[0][0]).toBe("/projects/objects/inspect-workflow");
  expect(useProjectStore().currentProjectId).toBeNull();
  expect(wrapper.findAll("button").map(button => button.text())).not.toContain("Run workflow");
});
it("discards an in-flight archive response when the actor changes", async () => {
  let resolve!: (value: { data: typeof report }) => void;
  vi.mocked(api.post).mockImplementation(() => new Promise(done => { resolve = done; }));
  await choose();
  useAuthStore().user = { id: 8, username: "other", is_active: true };
  await flushPromises();
  resolve({ data: report });
  await flushPromises();
  expect(wrapper.text()).not.toContain("Archived study");
  expect(wrapper.text()).not.toContain("9007199254740993");
});
