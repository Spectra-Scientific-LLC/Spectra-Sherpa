import { flushPromises, shallowMount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
const mocks = vi.hoisted(() => ({ project: null as any, get: vi.fn(), push: vi.fn(), list: vi.fn() }));
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/project", async () => {
  const { reactive } = await import("vue");
  mocks.project = reactive({ currentProjectId: 1, currentProject: null, projects: [], recentProjects: [], exportingProjectIds: [], isLoading: false,
    fetchProjects: vi.fn(), fetchProject: vi.fn() });
  return { useProjectStore: () => mocks.project };
});
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({ listWorkflows: mocks.list }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ config: ref({}), appMode: ref("local"), isCapabilityDisabled: () => false }) }));
vi.mock("@/composables/useProjectAvailability", () => ({ useProjectAvailability: () => ({ qualified: ref(false), availability: ref(null) }) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: ref(false), uploadsLastWeek: ref(null), uploadsLimitWeek: ref(0), fetchQuota: vi.fn() }) }));
import ProjectContent from "@/views/project/ProjectContent.vue";
import { installProjectCollections, projectCollectionsLoader } from "@/lib/projectCollections";
const project = (id: number) => ({ id, name: `Project ${id}`, description: "Wide project description", model_count: 60, experiment_count: 1, workflow_count: 1, created_at: "2026-10-01", updated_at: "2026-10-01" });
function mountView() { return shallowMount(ProjectContent, { global: { renderStubDefaultSlot: true } }); }
describe("Project resource workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks(); projectCollectionsLoader.value = null;
    mocks.project.currentProjectId = 1; mocks.project.currentProject = project(1); mocks.project.projects = [project(1)];
    mocks.list.mockResolvedValue([]);
    mocks.get.mockImplementation(async (path: string) => ({ data: path === "/runs" ? { runs: [{ id: 4, name: "Corn run", status: "completed", run_kind: "training", executed_at: "2026-10-01" }], total: 12 } : [] }));
  });
  it("keeps distinct counts, header commands and artifact navigation", async () => {
    const view = mountView(); await flushPromises();
    expect(view.get('[data-testid="project-runs"]').text()).toContain("12");
    expect(view.text()).toContain("Showing 1 of 12 runs");
    expect(view.text()).toContain("60 artifacts");
    const header = view.findComponent({ name: "WorkspaceHeader" });
    expect(header.findAllComponents({ name: "Button" }).map(b => b.attributes("label"))).toEqual(expect.arrayContaining(["Edit", "Export"]));
    const button = view.findAllComponents({ name: "Button" }).find(b => b.attributes("label") === "Artifacts")!;
    button.vm.$emit("click"); expect(mocks.push).toHaveBeenCalledWith("/runs?tab=artifacts"); view.unmount();
  });
  it("distinguishes failure from an empty history", async () => {
    mocks.get.mockRejectedValue(new Error("offline"));
    const view = mountView(); await flushPromises();
    expect(view.get('[role="alert"]').text()).toContain("Runs");
    expect(view.text()).toContain("Runs unavailable"); expect(view.text()).not.toContain("No saved runs"); view.unmount();
  });
  it("discards previous project responses", async () => {
    let release!: (value: any) => void;
    const waiting = new Promise(resolve => { release = resolve; });
    mocks.get.mockImplementation(async (path: string, opts: any) => path === "/runs" && opts.params.project_id === 1 ? waiting : { data: path === "/runs" ? { runs: [], total: 0 } : [] });
    const view = mountView(); await flushPromises();
    mocks.project.currentProjectId = 2; mocks.project.currentProject = project(2); await flushPromises();
    release({ data: { runs: [{ id: 8, name: "Old project run" }], total: 99 } }); await flushPromises();
    expect(view.text()).not.toContain("Old project run"); expect(view.text()).toContain("No saved runs"); view.unmount();
  });
  it("clears optional collections when their extension is removed", async () => {
    const dispose = installProjectCollections(async () => [{ key: "campaigns", label: "Campaigns", total: 7, to: "/campaigns", items: [{ id: "study-1", title: "Draft study", status: "draft", createdAt: "2026-10-01", to: "/campaigns" }] }]);
    const view = mountView(); await flushPromises(); expect(view.text()).toContain("7 campaigns");
    expect(view.get(".collection-summary").attributes("role")).toBeUndefined();
    await view.get(".collection-summary").trigger("click"); expect(mocks.push).not.toHaveBeenCalled();
    dispose(); await flushPromises(); expect(view.text()).not.toContain("7 campaigns"); view.unmount();
  });
});
