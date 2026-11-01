import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import { reactive } from "vue";
import PrimeVue from "primevue/config";
const m = vi.hoisted(() => ({ get: vi.fn(), runs: null as any, project: null as any }));
vi.mock("@/api/client", () => ({ default: { get: m.get } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: vi.fn() }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => m.project }));
vi.mock("@/stores/runs", () => ({ useRunsStore: () => m.runs }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => ({ user: { id: 1 } }) }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({ workflowId: null, nodes: [], edges: [] }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ config: { value: {} }, appMode: { value: "local" }, isCapabilityDisabled: () => false }) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: { value: false } }) }));
import ModelsContent from "@/views/models/ModelsContent.vue";

// Real history: the defect only appears when Back returns to a run-free address.
async function mountAt(start: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/runs", component: ModelsContent }, { path: "/runs/:runId", component: ModelsContent },
  ] });
  await router.push(start);
  await router.isReady();
  const view = mount(RouterView, { global: { plugins: [router, PrimeVue], renderStubDefaultSlot: true,
    stubs: { WorkspaceHeader: true, WorkspaceContext: true, WorkspaceContextItem: true, RunDetailContent: true,
      BatchRunTab: true, EvidenceComparisonView: true, ComparisonPanel: true, QualificationApplications: true,
      QualificationPanel: true, SavedModelProjectTable: true, SavedModelQualification: true, Dialog: true,
      DataTable: true, Dropdown: true, Button: true, InputText: true, ProgressSpinner: true, Tag: true,
      Textarea: true, LabelChips: true },
    directives: { tooltip: () => undefined } } });
  await flushPromises();
  return { router, view };
}
const selectedTab = (view: ReturnType<typeof mount>) =>
  view.findAll('[role="tab"]').find(tab => tab.attributes("aria-selected") === "true")?.text();

describe("Runs → retained exclusions → Back", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear();
    m.project = reactive({ ensureProjectForBrowserTab: vi.fn(), currentProjectId: 1, currentProject: { id: 1, name: "Corn" } });
    m.runs = reactive({ runs: [], total: 0, selectedRunIds: new Set([41, 42]), selectedCount: 2, runsLoading: false,
      comparison: { runs: [], metric_keys: [], diff: {} }, loadError: null, fetchProjectRuns: vi.fn(), clearSelection: vi.fn() });
    m.get.mockImplementation(async (path: string) => ({ data: path === "/runs" ? { runs: [], total: 0 } : [] }));
  });

  it.each([
    ["History opened from the sidebar", "/runs", "History"],
    ["History", "/runs?tab=run_history", "History"],
    ["Compare", "/runs?tab=compare", "Compare"],
  ])("returns from a retained map to %s with its selections", async (_name, start, tab) => {
    const { router, view } = await mountAt(start);
    expect(selectedTab(view)).toBe(tab);
    await router.push("/runs/42?project=1&tab=inspect&view=Summary#retained-observation-exclusions");
    await flushPromises();
    expect(selectedTab(view)).toBe("Inspect");
    router.back();
    await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe(start);
    expect(selectedTab(view)).toBe(tab);
    expect(m.runs.clearSelection).not.toHaveBeenCalled();
    view.unmount();
  });

  it.each([["batch", "Batch"], ["compare", "Compare"]])(
    "returns from a retained map to the remembered %s tab of a bare /runs address", async (remembered, tab) => {
      localStorage.setItem("spectra_sherpa_runs_active_tab_v4_1_1", remembered);
      const { router, view } = await mountAt("/runs");
      expect(selectedTab(view)).toBe(tab);
      await router.push("/runs/42?project=1&tab=inspect&view=Summary#retained-observation-exclusions");
      await flushPromises();
      expect(selectedTab(view)).toBe("Inspect");
      router.back();
      await flushPromises();
      expect(router.currentRoute.value.fullPath).toBe("/runs");
      expect(selectedTab(view)).toBe(tab);
      view.unmount();
    },
  );

  it("still clears History/Compare selections when leaving for Models", async () => {
    const { router, view } = await mountAt("/runs?tab=run_history");
    await router.push("/runs?tab=models");
    await flushPromises();
    expect(selectedTab(view)).toBe("Models");
    expect(m.runs.clearSelection).toHaveBeenCalled();
    view.unmount();
  });
});
