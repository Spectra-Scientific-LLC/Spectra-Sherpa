import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { defineComponent, ref } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PrimeVue from "primevue/config";
import api from "@/api/client";
import ProjectImportAction from "@/components/ProjectImportAction.vue";
import ModelsContent from "@/views/models/ModelsContent.vue";
import { useAuthStore } from "@/stores/auth";
import { useProjectStore } from "@/stores/project";

const mocks = vi.hoisted(() => ({ toast: vi.fn(), fetchQuota: vi.fn(), mode: "local" }));
vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toast }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({
  config: ref({ limits: { maxFileSizeMB: 200 } }), appMode: ref(mocks.mode), siteProfile: ref("local"),
  isCapabilityDisabled: () => false,
}) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({
  isDemoMode: ref(false), uploadsLastWeek: ref(null), uploadsLimitWeek: ref(0),
  uploadsResetWeekAt: ref(null), fetchQuota: mocks.fetchQuota,
}) }));
vi.mock("@/composables/useProjectAvailability", () => ({ useProjectAvailability: () => ({ qualified: ref(false) }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));

const project = {
  id: 42, name: "Imported conclusion", description: "", technique: "FTIR", sample_type: null,
  updated_at: "2026-11-02T00:00:00Z", experiment_count: 0, workflow_count: 1, script_count: 0,
  model_count: 0, children_count: 0, metadata: {}, experiments: [], data_sources: [], workflows: [],
  advisor_channels: [], scripts: [], models: [], children: [],
};
const application = {
  handle: "app:exact-import", origin: "campaign_solution", project_id: 42, workflow_id: 19,
  artifact_digest: "a".repeat(64), status: "awaiting_local_data_binding",
};
let imported: Record<string, unknown>;
let released: Array<Record<string, unknown>>;
let heldRead: Promise<unknown> | null;
let readinessError: boolean;
let wrappers: VueWrapper[];

function routerAt(url = "/project") {
  const empty = { template: "<div />" };
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/project", component: empty }, { path: "/deploy", component: empty },
    { path: "/runs", component: ModelsContent },
  ] });
  return { router, ready: router.push(url).then(() => router.isReady()) };
}

async function browser(url = "/project", pinia = createPinia()) {
  setActivePinia(pinia);
  const auth = useAuthStore();
  auth.user = { id: 7, username: "scientist", is_active: true };
  const { router, ready } = routerAt(url);
  await ready;
  const wrapper = mount(defineComponent({ components: { ProjectImportAction, RouterView },
    template: "<ProjectImportAction /><RouterView />",
  }), { global: { plugins: [pinia, router, PrimeVue], renderStubDefaultSlot: true,
    stubs: {
      Dialog: { template: "<section><slot /><slot name='footer' /></section>" },
      Button: { props: ["label", "disabled"], template: "<button :disabled='disabled'>{{ label }}</button>" },
      ProjectImportDestinationDialog: true,
      WorkspaceHeader: true, WorkspaceContext: true, WorkspaceContextItem: true,
      RunDetailContent: true, BatchRunTab: true, EvidenceComparisonView: true, ComparisonPanel: true,
      QualificationPanel: true, SavedModelProjectTable: true, SavedModelQualification: true,
      ModelPromotionReview: { props: ["canonicalArtifactId", "workflowId", "projectId"],
        template: "<section data-testid='exact-import-review' :data-artifact='canonicalArtifactId' :data-workflow='workflowId' :data-project='projectId' />" },
      DataTable: true, Dropdown: true, InputText: true, ProgressSpinner: true, Tag: true,
      Textarea: true, LabelChips: true,
    }, directives: { tooltip: () => undefined },
  } });
  wrappers.push(wrapper);
  await flushPromises();
  return { wrapper, router, auth, projectStore: useProjectStore() };
}

async function importFile(wrapper: VueWrapper) {
  const input = wrapper.find('input[type="file"]');
  Object.defineProperty(input.element, "files", { configurable: true, value: [new File(["signed"], "conclusion.sherpa")] });
  await input.trigger("change");
  await vi.waitFor(() => expect(useProjectStore().isImporting).toBe(false));
  await flushPromises();
}

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); wrappers = [];
  mocks.mode = "local";
  imported = { ...project, application: { ...application } }; released = []; heldRead = null; readinessError = false;
  mocks.fetchQuota.mockResolvedValue(undefined);
  vi.mocked(api.post).mockImplementation(async (path) => {
    if (path === "/projects/import") return { data: imported } as never;
    throw new Error(`Unexpected write ${path}`);
  });
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === "/projects") return { data: [project] } as never;
    if (path === "/projects/42") return { data: project } as never;
    if (path === "/deploy/applications") {
      if (readinessError) throw new Error("readiness unavailable");
      return (heldRead ? await heldRead : { data: released }) as never;
    }
    if (path === "/deploy/projects/42/qualification-applications") return { data: [
      { canonical_artifact_id: 18, workflow_id: 190, name: "Other", artifact_digest: "b".repeat(64) },
      { canonical_artifact_id: 17, workflow_id: 19, name: "Exact", artifact_digest: "a".repeat(64) },
    ] } as never;
    if (path === "/runs") return { data: { runs: [], total: 0 } } as never;
    if (path === "/deploy/capabilities") return { data: { privateBatchUpload: false } } as never;
    return { data: [] } as never;
  });
});
afterEach(() => { wrappers.forEach(w => w.unmount()); });

describe("normal project import destination", () => {
  it("keeps ordinary projects in the project workspace without checking Deploy", async () => {
    imported = { ...project };
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.fullPath).toBe("/project");
    expect(api.get).not.toHaveBeenCalledWith("/deploy/applications", expect.anything());
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });

  it.each(["enterprise", "hybrid"])("preserves exact formal review and reload for managed %s", async (mode) => {
    mocks.mode = mode;
    const { wrapper, router, projectStore } = await browser();
    await importFile(wrapper);
    expect(projectStore.currentProjectId).toBe(42);
    expect(router.currentRoute.value.path).toBe("/runs");
    expect(router.currentRoute.value.query).toEqual({ project: "42", tab: "models", review_workflow: "19" });
    expect(wrapper.get('[data-testid="exact-import-review"]').attributes()).toEqual(expect.objectContaining({
      "data-project": "42", "data-workflow": "19", "data-artifact": "17",
    }));
    const url = router.currentRoute.value.fullPath;
    wrapper.unmount();
    const reloaded = await browser(url);
    await flushPromises();
    expect(reloaded.projectStore.currentProjectId).toBe(42);
    expect(reloaded.wrapper.get('[data-testid="exact-import-review"]').attributes("data-artifact")).toBe("17");
    expect(reloaded.router.currentRoute.value.query.review_workflow).toBe("19");
    expect(api.post).toHaveBeenCalledTimes(1); // Reload only reads; it does not import or promote again.
  });

  it("keeps a technically unavailable local import inspectable without opening formal review", async () => {
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.path).toBe('/runs');
    expect(router.currentRoute.value.query).toEqual({ project: '42', tab: 'models', review_workflow: '19' });
    expect(wrapper.find('[data-testid="exact-import-review"]').exists()).toBe(false);
    const importedModels = wrapper.findComponent({ name: 'QualificationApplications' });
    expect(importedModels.text()).toContain('Open Deploy');
    expect(importedModels.text()).not.toContain('Review for promotion');
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("refuses unavailable local imported application use without inventing a promotion review", async () => {
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    const importedModels = wrapper.findComponent({ name: 'QualificationApplications' });
    const open = importedModels.findAll('button').find(button => button.text() === 'Open Deploy')!;
    await open.trigger('click'); await flushPromises();
    expect(router.currentRoute.value.path).toBe('/runs');
    expect(importedModels.text()).toContain('Check its saved model compatibility and dependencies.');
    expect(wrapper.find('[data-testid="exact-import-review"]').exists()).toBe(false);
    expect(api.post).toHaveBeenCalledTimes(1);
  });

  it("preserves Deploy for the exact server-released application", async () => {
    released = [{ handle: application.handle, workflow_id: 19, state: "released", origin: "campaign_solution" }];
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.path).toBe("/deploy");
    expect(router.currentRoute.value.query).toEqual({ project: "42", application: application.handle });
  });

  it("does not mistake another released handle for this imported application", async () => {
    released = [{ handle: "app:other", workflow_id: 190, state: "released" }];
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.path).toBe("/runs");
    expect(router.currentRoute.value.query.review_workflow).toBe("19");
  });

  it("does not treat an import's data-binding status as a release decision", async () => {
    imported = { ...project, application: { ...application, status: "ready_for_application" } };
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.path).toBe("/runs");
    expect(router.currentRoute.value.query.review_workflow).toBe("19");
  });

  it.each([
    { ...application, project_id: 99 }, { ...application, workflow_id: 0 },
  ])("refuses a mismatched or missing imported review identity", async (identity) => {
    imported = { ...project, application: identity };
    const { wrapper, router } = await browser();
    await importFile(wrapper);
    expect(router.currentRoute.value.fullPath).toBe("/project");
    expect(api.get).not.toHaveBeenCalledWith("/deploy/applications", expect.anything());
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: "warn", summary: `Imported ${project.name}` }));
  });

  it("preserves import success without inventing readiness when the resolver fails", async () => {
    readinessError = true;
    const { wrapper, router, projectStore } = await browser();
    await importFile(wrapper);
    expect(projectStore.currentProjectId).toBe(42);
    expect(router.currentRoute.value.fullPath).toBe("/project");
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: "warn", summary: `Imported ${project.name}`, detail: "Application readiness could not be checked." }));
  });

  it("does not navigate when the import finishes after this action is unmounted", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.post).mockReturnValueOnce(new Promise(done => { resolve = done; }));
    const { wrapper, router } = await browser();
    const navigate = vi.spyOn(router, "push");
    const input = wrapper.find('input[type="file"]');
    Object.defineProperty(input.element, "files", { configurable: true, value: [new File(["signed"], "conclusion.sherpa")] });
    await input.trigger("change");
    wrapper.unmount();
    resolve({ data: imported });
    await vi.waitFor(() => expect(useProjectStore().isImporting).toBe(false));
    await flushPromises();
    expect(navigate).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalledWith("/deploy/applications", expect.anything());
    expect(mocks.toast).not.toHaveBeenCalled();
  });

  it.each(["project", "session"])("ignores a late readiness result after %s scope changes", async (scope) => {
    let resolve!: (value: unknown) => void;
    heldRead = new Promise(done => { resolve = done; });
    const { wrapper, router, auth, projectStore } = await browser();
    await importFile(wrapper);
    expect(api.get).toHaveBeenCalledWith("/deploy/applications", expect.objectContaining({ params: { project_id: 42 } }));
    if (scope === "project") { projectStore.currentProjectId = 43; projectStore.currentProjectId = 42; }
    else auth.token = "fake";
    resolve({ data: released }); await flushPromises();
    expect(router.currentRoute.value.fullPath).toBe("/project");
    expect(mocks.toast).not.toHaveBeenCalledWith(expect.objectContaining({ severity: "success" }));
  });
});
