import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import PrimeVue from "primevue/config";
const m = vi.hoisted(() => ({ get: vi.fn(), push: vi.fn(), params: {} as Record<string, string>, query: {} as Record<string, string>, runs: null as any, project: null as any }));
vi.mock("@/api/client", () => ({ default: { get: m.get } }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: m.push, replace: vi.fn() }), useRoute: () => ({ query: m.query, params: m.params }), RouterLink: { template: "<a><slot /></a>" } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => m.project }));
vi.mock("@/stores/runs", () => ({ useRunsStore: () => m.runs }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 1 } }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({ workflowId: null, nodes: [], edges: [] }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ config: ref({}), appMode: ref("local"), isCapabilityDisabled: () => false }) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: ref(false) }) }));
import ModelsContent from "@/views/models/ModelsContent.vue";
function mountView() {
  return mount(ModelsContent, { global: { plugins: [PrimeVue], renderStubDefaultSlot: true,
    stubs: { WorkspaceHeader: true, WorkspaceContext: true, WorkspaceContextItem: true, RunDetailContent: true,
      BatchRunTab: true, ComparisonPanel: true, QualificationApplications: true, QualificationPanel: true,
      Dialog: true, DataTable: true, Dropdown: true, Button: true,
      InputText: true, ProgressSpinner: true, Tag: true, Textarea: true, LabelChips: true },
    directives: { tooltip: () => undefined } } });
}
describe("Runs workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); m.query = {}; m.params = {};
    m.project = { ensureProjectForBrowserTab: vi.fn(), currentProjectId: 1, currentProject: { id: 1, name: "Corn" } };
    m.runs = { runs: [], total: 0, selectedRunIds: new Set(), selectedCount: 0, runsLoading: false, comparison: null, loadError: null,
      fetchProjectRuns: vi.fn(), clearSelection: vi.fn() };
    m.get.mockImplementation(async (path: string) => ({ data: path === "/deploy/capabilities" ? { privateBatchUpload: true } : [] }));
  });
  it.each(["artifacts", "models"])("preserves the %s deep link with Inspect between History and Compare", async (tab) => {
    m.query.tab = tab;
    const view = mountView(); await flushPromises();
    const tabs = view.findAll('[role="tab"]');
    expect(tabs.map(t => t.text())).toEqual(["History", "Inspect", "Compare", "Artifacts", "Batch"]);
    expect(tabs[3].attributes("aria-selected")).toBe("true");
    expect(view.find('[label="Refresh"]').exists()).toBe(false);
    expect(view.find('workspace-context-item-stub').attributes("label")).toBe("Artifacts");
    view.unmount();
  });
  it("keeps History reachable when artifact loading fails", async () => {
    m.get.mockImplementation(async (path: string) => { if (path === "/models") throw new Error("offline"); return { data: {} }; });
    const view = mountView(); await flushPromises();
    expect(view.findAll('[role="tab"]').length).toBe(5);
    expect(view.find('[role="tab"]').attributes("aria-selected")).toBe("true");
    expect(m.runs.fetchProjectRuns).toHaveBeenCalledWith(1, 0, "all", undefined, "executed_at", "desc");
    view.unmount();
  });
  it("opens existing run deep links inside Inspect and retains a return to History", async () => {
    m.params.runId = "42";
    m.query.tab = "run_history"; // Older links used this as their return location.
    const view = mountView(); await flushPromises();
    expect(view.findAll('[role="tab"]')[1].attributes("aria-selected")).toBe("true");
    expect(view.findComponent({ name: "RunDetailContent" }).exists()).toBe(true);
    await view.findAll('[role="tab"]')[0].trigger("click");
    expect(m.push).toHaveBeenCalledWith({ path: "/runs", query: { tab: "run_history" } });
    await view.findAll('[role="tab"]')[1].trigger("click");
    expect(m.push).toHaveBeenCalledWith({ path: "/runs/42", query: { tab: "inspect" } });
    view.unmount();
  });
  it("offers History when Inspect has no selected run", async () => {
    m.query.tab = "inspect";
    const view = mountView(); await flushPromises();
    expect(view.findAll('[role="tab"]')[1].attributes("aria-selected")).toBe("true");
    expect(view.text()).toContain("Select a run name in History");
    expect(view.findComponent({ name: "RunDetailContent" }).exists()).toBe(false);
    view.unmount();
  });
});
