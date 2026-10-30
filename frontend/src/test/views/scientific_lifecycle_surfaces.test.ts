/* eslint-disable @typescript-eslint/no-explicit-any */
import { mount, flushPromises } from "@vue/test-utils";
import { reactive, ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import ReportContent from "@/views/report/ReportContent.vue";
import DeployContent from "@/views/deploy/DeployContent.vue";
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  download: vi.fn(),
  predictions: vi.fn(),
  toast: vi.fn(),
  audit: {} as Record<string, boolean>,
  profile: null as string | null,
}));
let report: any, project: any, deploy: any, workbook: any;
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
vi.mock("@/utils/download", () => ({
  downloadText: mocks.download,
  downloadJson: vi.fn(),
  downloadBlob: vi.fn(),
}));
vi.mock("@/stores/report", () => ({ useReportStore: () => report }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/workbook", () => ({ useWorkbookStore: () => workbook }));
vi.mock("@/stores/deploy", () => ({ useDeployStore: () => deploy }));
vi.mock("@/stores/runs", () => ({ useRunsStore: () => ({ fetchPredictions: mocks.predictions }) }));
vi.mock("@/stores/advisor", () => ({
  useAdvisorStore: () => ({ switchScope: vi.fn().mockResolvedValue(null) }),
}));
vi.mock("@/composables/useAppConfig", () => ({
  useAppConfig: () => ({ isFeatureEnabled: () => false, appConfig: ref({ audit: mocks.audit, siteProfile: mocks.profile }) }),
}));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toast }) }));
const slot = { template: "<div><slot /></div>" };
const stubs = {
  SavedModelsForDeployment: true,
  Button: { props: ["label"], template: "<button @click=\"$emit('click')\">{{label}}</button>" },
  ResponsiveHeaderActions: slot,
  ContextualActions: true,
  QualificationPanel: true,
  MemoryAttribution: true,
  Dropdown: true,
  Menu: true,
  Tag: true,
  ToggleButton: true,
  ProgressSpinner: true,
  TabView: slot,
  TabPanel: slot,
  Dialog: true,
  InputText: true,
  InputNumber: true,
  Column: true,
  LabelChips: true,
  DataTable: {
    props: ["value", "expandedRows"],
    template:
      '<div><button v-if="expandedRows" @click="$emit(\'update:expandedRows\',Object.fromEntries(value.map(row=>[row.id,true])))">Expand runs</button><div v-for="row in value" :key="row.id"><slot v-if="expandedRows?.[row.id]" name="expansion" :data="row"/><span v-if="!expandedRows">{{row.file_name}}</span></div></div>',
  },
};
async function open(component: any, path = "/report", realTabs = false) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/report", component: ReportContent },
      { path: "/deploy", component: DeployContent },
    ],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(component, { global: { plugins: [router], stubs: { ...stubs, ...(realTabs ? { TabView: false, TabPanel: false } : {}) } } });
  await flushPromises();
  return wrapper;
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.audit = {};
  mocks.profile = null;
  mocks.get.mockResolvedValue({ data: [] });
  mocks.predictions.mockReset();
  project = reactive({
    currentProjectId: 1,
    ensureProjectForBrowserTab: vi.fn().mockResolvedValue(null),
    selectProject: vi.fn().mockResolvedValue(null),
  });
  workbook = reactive({ projectId: null, activeSheet: null });
  report = reactive({
    selectedWorkflowId: 7,
    selectedRunIds: [],
    reportMode: "summary",
    reportData: null,
    isReady: false,
    availableRuns: [],
    workflows: [],
    sections: { aiNarrative: false },
    fetchWorkflows: vi.fn().mockResolvedValue(null),
    fetchReportData: vi.fn().mockResolvedValue(null),
    fetchRunsForWorkflow: vi.fn().mockResolvedValue(null),
  });
  deploy = reactive({
    watches: [],
    deployRuns: [{ id: 42, name: "Synthetic prediction", status: "completed" }],
    loading: false,
    runsLoading: false,
    fetchWatches: vi.fn(),
    fetchDeployRuns: vi.fn(),
  });
});
function executableMenus(w: any) {
  return w.vm.exportMenuItems.filter((item: any) => item.label?.includes("current workflow"));
}
describe("Report configuration layout and scientific summary", () => {
  it("opens on the active sheet and newest completed run without generating a report", async () => {
    report.selectedWorkflowId = null;
    report.workflows = [{ id: 5, name: "Active sheet" }, { id: 7, name: "Other sheet" }];
    workbook.projectId = 1;
    workbook.activeSheet = { workflowId: 5 };
    report.fetchRunsForWorkflow.mockImplementation(async () => {
      report.availableRuns = [
        { id: 3, status: "completed", executed_at: "2026-10-01T00:00:00Z" },
        { id: 4, status: "completed", executed_at: "2026-10-02T00:00:00Z" },
        { id: 5, status: "failed", executed_at: "2026-10-03T00:00:00Z" },
      ];
    });
    const w = await open(ReportContent);
    expect(report.selectedWorkflowId).toBe(5);
    expect(report.selectedRunIds).toEqual([4]);
    expect(report.fetchReportData).not.toHaveBeenCalled();
    w.unmount();
  });
  it("keeps removable runs outside aligned fields and switches preview/export detail", async () => {
    report.selectedRunIds = [42];
    report.availableRuns = [{ id: 42, name: "Long selected execution run" }];
    report.isReady = true;
    report.reportData = { name: "Report", nodes: [], edges: [], runs: [] };
    const w = await open(ReportContent);
    expect(w.find(".config-field .selected-runs-chips").exists()).toBe(false);
    expect(w.get(".report-config > .selected-runs-chips").text()).toContain("Long selected");
    expect(w.get("iframe").attributes("srcdoc")).toContain("Short summary");
    expect(w.get('summary[aria-label="Report length"]').element.closest("details")?.open).toBe(false);
    expect(w.get('summary[aria-label="Report length"]').element.closest("details")?.textContent).toContain("Key retained results and context");
    expect(w.find(".row-level-option").exists()).toBe(true);
    expect(w.get(".row-level-option").text()).toContain("Include figures and individual reference/prediction values");
    report.reportMode = "detailed";
    await flushPromises();
    expect(w.find(".row-level-option").exists()).toBe(true);
    expect(w.get("iframe").attributes("srcdoc")).not.toContain("<h2>Short summary");
    expect(w.get('summary[aria-label="Report length"]').element.closest("details")?.textContent).toContain("All retained results, settings, diagnostics, and execution evidence.");
    await w.get('button[aria-label="Remove Long selected execution run"]').trigger("click");
    expect(report.selectedRunIds).toEqual([]);
    w.unmount();
  });
});
describe("Report workspace generated evidence", () => {
  it("uses the renamed run as the title for a single-run report without changing workflow identity", async () => {
    report.isReady = true;
    report.reportData = {
      workflow_id: 7, name: "Original workflow", nodes: [], edges: [],
      runs: [{ id: 42, name: "Reviewed Iris run", status: "completed", results_summary: {} }],
    };
    const w = await open(ReportContent, "/report?tab=preview");
    const html = w.get("iframe").attributes("srcdoc") || "";
    expect(html).toContain("<h1>Reviewed Iris run</h1>");
    expect(html).not.toContain("<h1>Original workflow</h1>");
    expect((w.vm as any).getExportFilename("pdf")).toBe("reviewed_iris_run_report.pdf");
    w.unmount();
  });
  it("renders and exports a detailed executed graph with optional node labels absent", async () => {
    report.isReady = true;
    report.reportMode = "detailed";
    report.sections.pipelineDetails = true;
    report.reportData = { workflow_id: 7, name: "Unlabelled PCA", nodes: [
      { node_id: "pca", node_type: "model.pca", label: null, parameters: { n_components: "2" } }
    ], edges: [], runs: [] };
    const w = await open(ReportContent);
    expect(w.get("iframe").attributes("srcdoc")).toContain("<strong>model.pca</strong>");
    await (w.vm as any).exportMenuItems.find((item: any) => item.label === "Markdown").command();
    expect(mocks.download.mock.calls[0][0]).toContain("model.pca");
    expect(mocks.download.mock.calls[0][0]).toContain(String.raw`n\_components`);
    w.unmount();
  });
  it("retains the generated narrative and attribution when changing the Setup workflow", async () => {
    report.isReady = true;
    report.reportData = { workflow_id: 7, name: "Report A", nodes: [], edges: [], runs: [] };
    report.generatedSelection = { workflowId: 7, runIds: [], reportMode: "detailed",
      includeRowLevelPlots: false, generatedAt: "2026-10-02T10:00:00Z" };
    report.sections.aiNarrative = true;
    report.narrativeText = "Retained scientific explanation A";
    report.narrativeMemoryScopes = ["report-A"];
    const w = await open(ReportContent);
    report.selectedWorkflowId = 8;
    await (w.vm as any).onWorkflowChange();
    await flushPromises();
    expect(report.narrativeText).toBe("Retained scientific explanation A");
    expect(report.narrativeMemoryScopes).toEqual(["report-A"]);
    expect(w.get("iframe").attributes("srcdoc")).toContain("Retained scientific explanation A");
    expect(report.fetchReportData).not.toHaveBeenCalled();
    w.unmount();
  });
  it("keeps Report to two tabs even when audit is entitled, without changing retained preview", async () => {
    mocks.audit = { localQuery: true, fullPipeline: true, reportPack: true, exportAudited: true };
    report.isReady = true;
    report.isStale = true;
    report.reportMode = "detailed";
    report.generatedSelection = { workflowId: 7, runIds: [42], reportMode: "summary",
      includeRowLevelPlots: false, generatedAt: "2026-10-02T10:00:00Z" };
    report.reportData = { workflow_id: 7, name: "Retained A", nodes: [], edges: [], runs: [] };
    const w = await open(ReportContent, "/report?tab=preview");
    expect(w.findAll("[header]").map(tab => tab.attributes("header")))
      .toEqual(["Setup", "Preview"]);
    expect(w.text()).toContain("Setup has changed");
    const before = w.get("iframe").attributes("srcdoc");
    expect(before).toContain("Short summary");
    expect(before).toContain("2026-10-02T10:00:00Z");
    (w.vm as any).activeTab = "setup";
    report.reportMode = "summary";
    await flushPromises();
    (w.vm as any).activeTab = "preview";
    await flushPromises();
    expect(w.get("iframe").attributes("srcdoc")).toBe(before);
    expect(report.fetchReportData).not.toHaveBeenCalled();
    await (w.vm as any).exportMenuItems.find((item: any) => item.label === "Markdown").command();
    expect(mocks.download.mock.calls[0][0]).toContain("2026-10-02T10:00:00Z");
    expect(mocks.download.mock.calls[0][0]).toContain("Short summary");
    w.unmount();
  });
  it.each([{}, { localQuery: true }, { fullPipeline: true, reportPack: true, exportAudited: true }])(
    "keeps operator rehearsal out of Report and normalizes old deep links %j", async (audit) => {
      mocks.audit = audit;
      const w = await open(ReportContent, "/report?tab=validation");
      expect(w.text()).not.toContain("Validation Walkthrough");
      expect((w.vm as any).activeTab).toBe("setup");
      expect(w.findAll("[header]").map(tab => tab.attributes("header"))).toEqual(["Setup", "Preview"]);
      (w.vm as any).activeTab = "validation";
      await flushPromises();
      expect((w.vm as any).activeTab).toBe("setup");
      w.unmount();
    },
  );
  it.each([false, true])("offers the workflow Audit action only with query capability %s", async (enabled) => {
    mocks.audit = { localQuery: enabled };
    const w = await open(ReportContent);
    const menu = (w.vm as any).reportHeaderActionItems;
    expect(w.findAll('button').some(button => button.text() === 'Audit')).toBe(enabled);
      expect(w.text()).not.toContain("Validation Walkthrough");
    expect(menu.some((item: any) => item.label === 'Audit')).toBe(enabled);
    await (w.vm as any).openWorkflowAudit();
    await flushPromises();
    expect(w.vm.$route.path).toBe(enabled ? '/audit' : '/report');
    w.unmount();
  });
  it("does not offer Audit actions in Demo even when a backend advertises local audit", async () => {
    mocks.profile = "demo";
    mocks.audit = { localQuery: true, fullPipeline: true, reportPack: true, exportAudited: true };
    const w = await open(ReportContent);
    expect(w.findAll("[header]").map(tab => tab.attributes("header"))).toEqual(["Setup", "Preview"]);
    expect(w.findAll("button").some(button => button.text() === "Audit")).toBe(false);
    expect((w.vm as any).reportHeaderActionItems.some((item: any) => item.label === "Audit")).toBe(false);
    await (w.vm as any).openWorkflowAudit();
    await flushPromises();
    expect(w.vm.$route.path).toBe("/report");
    w.unmount();
  });
});
describe("GSC-12 saved-run executable export authority", () => {
  it.each(["one run", "multiple runs", "retained report", "linked run"])(
    "refuses current graph substitution for %s",
    async (kind) => {
      if (kind === "one run") report.selectedRunIds = [42];
      if (kind === "multiple runs") report.selectedRunIds = [42, 43];
      if (kind === "retained report")
        report.reportData = { name: "Saved A", nodes: [], edges: [], runs: [{ id: 42 }] };
      const w = await open(
        ReportContent,
        kind === "linked run" ? "/report?project=1&workflow=7&run=42" : "/report",
      );
      expect(w.get(".execution-export-scope").text()).toContain("original executable code is unavailable");
      for (const item of executableMenus(w)) {
        expect(item.disabled).toBe(true);
        await item.command();
      }
      expect(mocks.get).not.toHaveBeenCalled();
      expect(mocks.download).not.toHaveBeenCalled();
      w.unmount();
    },
  );
  it.each(["Python", "Jupyter"])(
    "still exports the explicitly current %s workflow",
    async (label) => {
      mocks.get.mockResolvedValue({
        data: {
          workflow_name: "Current B",
          python_code: 'print("B")\n',
          notebook: { cells: [], metadata: { name: "B" } },
        },
      });
      const w = await open(ReportContent);
      const item = executableMenus(w).find((i: any) => i.label.startsWith(label));
      expect(item.disabled).toBe(false);
      await item.command();
      expect(mocks.get).toHaveBeenCalledWith(
        `/workflows/7/export/${label === "Python" ? "python" : "notebook"}`,
      );
      expect(mocks.download.mock.calls[0][0]).toContain(
        label === "Python" ? 'print("B")' : '"name": "B"',
      );
      w.unmount();
    },
  );
  it.each(["workflow", "run"])(
    "discards a pending current export after %s selection changes",
    async (kind) => {
      let resolve!: (value: any) => void;
      mocks.get.mockImplementation(
        () =>
          new Promise((r) => {
            resolve = r;
          }),
      );
      const w = await open(ReportContent);
      const pending = executableMenus(w)[0].command();
      if (kind === "workflow") report.selectedWorkflowId = 8;
      else report.selectedRunIds = [42];
      resolve({ data: { python_code: "stale A", workflow_name: "A" } });
      await pending;
      expect(mocks.download).not.toHaveBeenCalled();
      w.unmount();
    },
  );
});
describe("GSC-15 deployment failure is distinct from empty evidence", () => {
  it("shows failed request/run identity and retries to real per-file results", async () => {
    mocks.predictions
      .mockRejectedValueOnce({
        response: { data: { detail: "Retained results service unavailable (503)" } },
      })
      .mockResolvedValueOnce([{ id: 1, file_name: "synthetic.csv", status: "completed" }]);
    const w = await open(DeployContent, "/deploy");
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toContain(
      "Run 42: Retained results service unavailable (503)",
    );
    expect(w.text()).not.toContain("No per-file results available");
    await w.get('[role="alert"] button').trigger("click");
    await flushPromises();
    expect(w.find('[role="alert"]').exists()).toBe(false);
    expect(w.text()).toContain("synthetic.csv");
    expect(mocks.predictions.mock.calls).toEqual([[42], [42]]);
    w.unmount();
  });
  it("a successful empty response remains explicitly empty and is not repeatedly fetched", async () => {
    mocks.predictions.mockResolvedValue([]);
    const w = await open(DeployContent, "/deploy");
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    expect(w.text()).toContain("No per-file results available");
    expect(w.find('[role="alert"]').exists()).toBe(false);
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    expect(mocks.predictions).toHaveBeenCalledTimes(1);
    w.unmount();
  });
  it("refresh retrieves new per-file rows after an earlier running empty or partial response", async () => {
    deploy.deployRuns[0].status = "running";
    mocks.predictions.mockResolvedValueOnce([]).mockResolvedValueOnce([
      { id: 1, file_name: "ready.csv", status: "completed" },
      {
        id: 2,
        file_name: "expired.csv",
        status: "failed",
        error_message: "Retained output expired (410)",
      },
    ]);
    const w = await open(DeployContent, "/deploy");
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    expect(w.text()).toContain("No per-file results available");
    await (w.vm as any).refreshAll();
    await flushPromises();
    expect(mocks.predictions).toHaveBeenCalledTimes(2);
    expect(w.text()).toContain("ready.csv");
    expect((w.vm as any).predictions[42][1]).toMatchObject({
      status: "failed",
      error_message: "Retained output expired (410)",
    });
    w.unmount();
  });
  it("keeps independent pending run results bound to their run IDs", async () => {
    deploy.deployRuns.push({ id: 43, name: "Other", status: "partial" });
    const finish: Record<number, (value: any) => void> = {};
    mocks.predictions.mockImplementation(
      (id) =>
        new Promise((resolve) => {
          finish[id] = resolve;
        }),
    );
    const w = await open(DeployContent, "/deploy");
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    finish[43]([{ id: 2, file_name: "second.csv" }]);
    await flushPromises();
    finish[42]([{ id: 1, file_name: "first.csv" }]);
    await flushPromises();
    expect((w.vm as any).predictions[42][0].file_name).toBe("first.csv");
    expect((w.vm as any).predictions[43][0].file_name).toBe("second.csv");
    w.unmount();
  });
  it.each(["resolve", "reject"])("ignores %s from another project", async (mode) => {
    let finish!: (value: any) => void;
    mocks.predictions.mockImplementation(
      () =>
        new Promise((resolve, reject) => {
          finish = mode === "resolve" ? resolve : reject;
        }),
    );
    const w = await open(DeployContent, "/deploy");
    await w.get(".runs-table button").trigger("click");
    await flushPromises();
    project.currentProjectId = 2;
    await flushPromises();
    finish(
      mode === "resolve"
        ? [{ id: 1, file_name: "private-old.csv" }]
        : new Error("old project error"),
    );
    await flushPromises();
    expect((w.vm as any).predictions).toEqual({});
    expect((w.vm as any).predictionErrors).toEqual({});
    w.unmount();
  });
});

describe("Imported campaign folder-watch selection", () => {
  const target = { canonical_artifact_id: 12, workflow_id: 7, name: "Optimized PLS",
    artifact_digest: "a".repeat(64), deploy_ready: true, refusal: null };
  it("offers the imported solution without inventing a legacy model UID or workflow version", async () => {
    mocks.get.mockImplementation(async (url: string) => ({ data: url === "/deploy/canonical-targets" ? [target] : [] }));
    deploy.createWatch = vi.fn().mockResolvedValue({ id: 5 });
    const w = await open(DeployContent, "/deploy");
    const vm = w.vm as any;
    expect(vm.artifactOptions[0]).toMatchObject({ canonical_artifact_id: 12, workflow_version_id: null, disabled: false });
    Object.assign(vm.newWatch, { artifact_uid: "canonical:12", name: "Instrument", folder_path: "/incoming" });
    await vm.handleCreate();
    expect(deploy.createWatch).toHaveBeenCalledWith(expect.objectContaining({
      workflow_id: 7, canonical_artifact_id: 12, artifact_uid: null, folder_path: "/incoming",
    }));
    w.unmount();
  });
  it("discloses an unavailable runtime and prevents selection", async () => {
    mocks.get.mockImplementation(async (url: string) => ({ data: url === "/deploy/canonical-targets"
      ? [{ ...target, deploy_ready: false, refusal: "Install exact certified runtime" }] : [] }));
    const w = await open(DeployContent, "/deploy");
    const vm = w.vm as any;
    expect(vm.artifactOptions[0].label).toContain("Install exact certified runtime");
    Object.assign(vm.newWatch, { artifact_uid: "canonical:12", name: "Instrument", folder_path: "/incoming" });
    expect(vm.canCreate).toBe(false);
    w.unmount();
  });
  it("reports catalog errors rather than presenting an unexplained empty list", async () => {
    mocks.get.mockImplementation(async (url: string) => {
      if (url === "/deploy/canonical-targets") throw new Error("offline");
      return { data: [] };
    });
    const w = await open(DeployContent, "/deploy");
    expect(mocks.toast).toHaveBeenCalledWith(expect.objectContaining({ summary: "Deployment targets unavailable" }));
    w.unmount();
  });
});

it('keeps Application first and changing the selection never rebinds an existing watch', async () => {
  deploy.applications=[{application_id:'app-a',name:'Application A',workflow_id:7,artifact_uid:'model-a',origin:'saved_run',campaign_validation_recorded:true},
    {application_id:'app-b',name:'Application B',workflow_id:8,artifact_uid:'model-b',origin:'saved_run'}];
  deploy.fetchApplications=vi.fn().mockResolvedValue(null);
  deploy.updateWatch=vi.fn(); deploy.toggleWatch=vi.fn();
  const w=await open(DeployContent,'/deploy');
  expect(w.findAll('[header]').map((panel:any)=>panel.attributes('header')).slice(0,3)).toEqual(['Application','Folder Watches','Prediction History']);
  expect((w.vm as any).activeTab).toBe('application');
  expect(w.find('[title="Refresh"]').exists()).toBe(false);
  await w.findAll('.application-card')[0].trigger('click'); await flushPromises();
  expect(w.find('.workspace-context').text()).toContain('Application A');
  expect(w.find('.campaign-validation-star').exists()).toBe(true);
  await w.findAll('.application-card')[1].trigger('click'); await flushPromises();
  expect((w.vm as any).newWatch.artifact_uid).toBe('model-b');
  expect(deploy.updateWatch).not.toHaveBeenCalled(); expect(deploy.toggleWatch).not.toHaveBeenCalled();
  expect(deploy.fetchWatches).toHaveBeenCalledWith(1);
  expect(deploy.fetchDeployRuns).toHaveBeenCalledWith(undefined,undefined,1);
  w.unmount();
});


it('refreshes applications on focus without replacing an explicit selection or an open watch draft', async () => {
  deploy.applications=[{application_id:'app-a',name:'A',workflow_id:7,artifact_uid:'a',origin:'saved_run'}];
  deploy.fetchApplications=vi.fn().mockResolvedValue(null);
  const w=await open(DeployContent,'/deploy?application=app-a'); const vm=w.vm as any;
  expect(vm.selectedApplicationId).toBe('app-a');
  deploy.applications.push({application_id:'app-b',name:'B',workflow_id:8,artifact_uid:'b',origin:'saved_run'});
  window.dispatchEvent(new Event('focus')); await flushPromises();
  expect(vm.artifactOptions).toHaveLength(2);
  await w.findAll('.application-card')[1].trigger('click');
  window.dispatchEvent(new Event('focus')); await flushPromises();
  expect(vm.selectedApplicationId).toBe('app-b');
  vm.showCreateDialog=true; const calls=deploy.fetchApplications.mock.calls.length;
  window.dispatchEvent(new Event('focus')); await flushPromises();
  expect(deploy.fetchApplications).toHaveBeenCalledTimes(calls);
  expect(vm.newWatch.artifact_uid).toBe('b'); w.unmount();
});

it('does not install polling or focus listeners when initial loading finishes after unmount', async () => {
  let finish!:()=>void; deploy.fetchApplications=vi.fn(()=>new Promise<void>(resolve=>{finish=resolve;}));
  const w=await open(DeployContent,'/deploy');
  const interval=vi.spyOn(window,'setInterval'); const listener=vi.spyOn(window,'addEventListener');
  w.unmount(); finish(); await flushPromises();
  expect(interval).not.toHaveBeenCalled();
  expect(listener.mock.calls.some(([event])=>event === 'focus')).toBe(false);
  interval.mockRestore(); listener.mockRestore();
});


describe('Deploy subtab pages', () => {
  it('keeps saved models and watch actions on their own pages and follows the route', async () => {
    const wrapper = await open(DeployContent, '/deploy?tab=application', true);
    const vm = wrapper.vm as any;
    expect(wrapper.find('saved-models-for-deployment-stub').exists()).toBe(true);
    expect(wrapper.text()).not.toContain('New Watch');
    vm.activeTab = 'watches'; await flushPromises();
    expect(vm.$route.query.tab).toBe('watches');
    expect((wrapper.get('saved-models-for-deployment-stub').element.closest('[role="tabpanel"]') as HTMLElement).style.display).toBe('none');
    expect(wrapper.text()).toContain('New Watch');
    expect(wrapper.get('[aria-label="Deployment context"]').text()).toContain('Process new files');
    await vm.$router.push('/deploy?tab=history'); await flushPromises();
    expect(wrapper.text()).not.toContain('New Watch');
    expect((wrapper.get('saved-models-for-deployment-stub').element.closest('[role="tabpanel"]') as HTMLElement).style.display).toBe('none');
    expect(wrapper.get('[aria-label="Deployment context"]').text()).toContain('Review predictions');
    await vm.$router.push('/deploy?tab=application'); await flushPromises();
    expect(wrapper.find('saved-models-for-deployment-stub').exists()).toBe(true);
    wrapper.unmount();
  });
});
