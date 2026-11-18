import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import api from "@/api/client";
import RetainedArchiveResults from "@/components/RetainedArchiveResults.vue";
import { useAuthStore } from "@/stores/auth";
import { RETAINED_DISPLAY_CHAR_LIMIT } from "@/utils/retainedJson";

vi.mock("@/api/client", () => ({ default: { post: vi.fn(), get: vi.fn() } }));
const inventory = {
  inspection_only: true, prior_unrecorded_history: "unknown", runs: [{
    source_run_id: 42, source_project_id: 3, source_workflow_id: 8,
    record_json: '{"name":"Historical run","identity":9007199254740993}',
    evidence: { qualification: "qualified", outputs: { absent: {
      record: { state: "exact", storage: "file", role: "held_out" },
      missing: { state: "missing", storage: null, reason: "Not retained" },
    } } },
  }],
};
const envelope = '{"format_version":1,"value":{"value":1.234567890123456789,"identity":9007199254740993,"units":"mg/L","role":"held_out","label":"<img src=x onerror=alert(1)>"}}';
let wrapper: VueWrapper;
beforeEach(() => {
  vi.clearAllMocks();
  setActivePinia(createPinia());
  useAuthStore().user = { id: 7, username: "reader", is_active: true };
  vi.mocked(api.post).mockImplementation(async path => ({ data: path.endsWith("inspect-results") ? inventory : envelope }));
  wrapper = mount(RetainedArchiveResults, { props: { file: new File(["fixture"], "retained.sherpa") }, global: { stubs: {
    Button: { props: ["label", "disabled"], template: '<button :disabled="disabled">{{ label }}</button>' },
  } } });
});
afterEach(() => wrapper.unmount());
function view() { return wrapper.findAll("button").find(button => button.text() === "View")!; }
it("renders recorded values without numerical rounding, execution or HTML", async () => {
  await flushPromises();
  await view().trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("9007199254740993");
  expect(wrapper.text()).toContain("1.234567890123456789");
  expect(wrapper.text()).toContain("mg/L");
  expect(wrapper.text()).toContain("held_out");
  expect(wrapper.find("img").exists()).toBe(false);
  expect(wrapper.findAll("button").find(button => button.text() === "Run")).toBeUndefined();
  expect(vi.mocked(api.post).mock.calls[1][2]).toMatchObject({ params: { run_id: 42, node_id: "absent", port: "record" }, responseType: "text" });
  const missing = wrapper.findAll("button").filter(button => button.text() === "View")[1];
  expect(missing.attributes("disabled")).toBeDefined();
});
it("drops old actor responses without uploading their archive again", async () => {
  await flushPromises();
  let resolve!: (value: { data: string }) => void;
  vi.mocked(api.post).mockImplementation(() => new Promise(done => { resolve = done; }));
  await view().trigger("click");
  const calls = vi.mocked(api.post).mock.calls.length;
  useAuthStore().user = { id: 8, username: "other", is_active: true };
  await flushPromises();
  resolve({ data: envelope });
  await flushPromises();
  expect(wrapper.text()).not.toContain("9007199254740993");
  expect(vi.mocked(api.post).mock.calls.length).toBe(calls);
});
it("clears the previous output when a selected read fails", async () => {
  await flushPromises(); await view().trigger("click"); await flushPromises();
  vi.mocked(api.post).mockRejectedValue(new Error("checksum mismatch"));
  await view().trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("failed its integrity check");
  expect(wrapper.text()).not.toContain("1.234567890123456789");
});
it("bounds rendering while retaining an explicit full-value download", async () => {
  await flushPromises();
  vi.mocked(api.post).mockResolvedValue({ data: '{"value":"' + "x".repeat(RETAINED_DISPLAY_CHAR_LIMIT) + '"}' });
  await view().trigger("click"); await flushPromises();
  expect(wrapper.text()).toContain("too large to display");
  expect(wrapper.text()).toContain("Download result (JSON)");
  expect(wrapper.text().length).toBeLessThan(3000);
});
