import { mount, flushPromises, enableAutoUnmount } from "@vue/test-utils";
import { reactive } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SavedModelsForDeployment from "@/views/deploy/SavedModelsForDeployment.vue";
enableAutoUnmount(afterEach);
const mocks = vi.hoisted(() => ({ get: vi.fn(), push: vi.fn() }));
const project = reactive({ currentProjectId: 1 as number | null });
const auth = reactive({ user: { id: 1 }, sessionRevision: 0 });
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
const model = { artifact_uid: "retained-pls", name: "Corn PLS", model_type: "PLS", is_deploy_ready: false };
const render = () => mount(SavedModelsForDeployment, { global: { stubs: {
  Panel: { template: "<section><slot/></section>" },
  Button: { props: ["label", "disabled"], template: '<button :disabled="disabled" @click="$emit(\'click\')">{{label}}</button>' },
} } });
beforeEach(() => { vi.clearAllMocks(); project.currentProjectId = 1; auth.sessionRevision = 0; mocks.get.mockResolvedValue({ data: [model] }); });
describe("saved models on Deploy", () => {
  it("opens the exact model for review without claiming promotion or executing it", async () => {
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain("Corn PLS");
    expect(wrapper.text()).toContain("Review the model and its validation");
    await wrapper.get('button[aria-label="Make application: Corn PLS"]').trigger("click");
    expect(mocks.push).toHaveBeenCalledWith({ path: "/runs", query: { tab: "models", project: "1", artifact: "retained-pls" } });
  });
  it("rejects a late model catalog from a previous project", async () => {
    let release!: (value: { data: typeof model[] }) => void;
    mocks.get.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const wrapper = render(); await flushPromises();
    project.currentProjectId = 2; mocks.get.mockResolvedValue({ data: [] }); await flushPromises();
    release({ data: [model] }); await flushPromises();
    expect(wrapper.text()).not.toContain("Corn PLS");
    expect(wrapper.text()).toContain("No saved models");
  });
  it("keeps a load failure distinct from an empty model catalog", async () => {
    mocks.get.mockRejectedValueOnce(new Error("network"));
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain("Saved models could not be loaded");
    expect(wrapper.text()).not.toContain("No saved models");
    await wrapper.get("button").trigger("click"); await flushPromises();
    expect(wrapper.text()).toContain("Corn PLS");
  });
});
