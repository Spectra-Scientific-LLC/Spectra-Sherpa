import { mount, flushPromises, enableAutoUnmount } from "@vue/test-utils";
import { reactive, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SavedModelsForDeployment from "@/views/deploy/SavedModelsForDeployment.vue";
enableAutoUnmount(afterEach);
const mocks = vi.hoisted(() => ({ get: vi.fn(), push: vi.fn() }));
const project = reactive({ currentProjectId: 1 as number | null });
const auth = reactive({ user: { id: 1 }, sessionRevision: 0 });
const mode = ref("enterprise");
const deploy = reactive({ applications: [] as Array<{ artifact_uid: string; application_handle: string; deploy_ready: boolean }> });
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ appMode: mode }) }));
vi.mock("@/stores/deploy", () => ({ useDeployStore: () => deploy }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
const model = { artifact_uid: "retained-pls", name: "Corn PLS", model_type: "PLS", is_deploy_ready: false };
const render = () => mount(SavedModelsForDeployment, { global: { stubs: {
  Panel: { template: "<section><slot/></section>" },
  Button: { props: ["label", "disabled"], template: '<button :disabled="disabled" @click="$emit(\'click\')">{{label}}</button>' },
} } });
beforeEach(() => { vi.clearAllMocks(); mode.value = "enterprise"; deploy.applications = []; project.currentProjectId = 1; auth.sessionRevision = 0; mocks.get.mockResolvedValue({ data: [model] }); });
describe("saved models on Deploy", () => {
  it("opens the exact model for review without claiming promotion or executing it", async () => {
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain("Corn PLS");
    expect(wrapper.text()).toContain("Review the model and its validation");
    await wrapper.get('button[aria-label="Make application: Corn PLS"]').trigger("click");
    expect(mocks.push).toHaveBeenCalledWith({ path: "/runs", query: { tab: "models", project: "1", artifact: "retained-pls" } });
  });
  it("uses local inspection copy without formal promotion review", async () => {
    mode.value = "local";
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain("Inspect fitted models and their recorded validation");
    expect(wrapper.text()).not.toContain("before promotion");
    expect(wrapper.find('button[aria-label="Make application: Corn PLS"]').exists()).toBe(true);
  });
  it("offers model inspection instead of remaking an already released local import", async () => {
    mode.value = "local";
    // The durable released projection owns availability, not the imported model's compatibility flag.
    deploy.applications = [{ artifact_uid: model.artifact_uid, application_handle: "app-imported", deploy_ready: true }];
    const wrapper = render(); await flushPromises();
    expect(wrapper.find('button[aria-label="Make application: Corn PLS"]').exists()).toBe(false);
    await wrapper.get('button[aria-label="View model: Corn PLS"]').trigger("click");
    expect(mocks.push).toHaveBeenCalledWith({ path: "/runs", query: { tab: "models", project: "1", artifact: model.artifact_uid } });
  });
  it("reacts to the released projection without another model request or an unrelated identity match", async () => {
    mode.value = "local";
    deploy.applications = [{ artifact_uid: "other", application_handle: "app-other", deploy_ready: true }];
    const wrapper = render(); await flushPromises();
    expect(wrapper.find('button[aria-label="Make application: Corn PLS"]').exists()).toBe(true);
    deploy.applications.push({ artifact_uid: model.artifact_uid, application_handle: "app-exact", deploy_ready: true });
    await flushPromises();
    expect(wrapper.find('button[aria-label="View model: Corn PLS"]').exists()).toBe(true);
    expect(mocks.get).toHaveBeenCalledOnce();
  });
  it("keeps hosted review copy and actions even when a local-style release projection exists", async () => {
    deploy.applications = [{ artifact_uid: model.artifact_uid, application_handle: "app-exact", deploy_ready: true }];
    mocks.get.mockResolvedValue({ data: [{ ...model, is_deploy_ready: true }] });
    const wrapper = render(); await flushPromises();
    expect(wrapper.text()).toContain("before promotion");
    expect(wrapper.find('button[aria-label="Review application: Corn PLS"]').exists()).toBe(true);
    expect(wrapper.find('button[aria-label="View model: Corn PLS"]').exists()).toBe(false);
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
