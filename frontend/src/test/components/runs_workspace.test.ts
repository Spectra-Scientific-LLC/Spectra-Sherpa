import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, reactive, ref, type Ref } from "vue";
import PrimeVue from "primevue/config";
const m = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), toast: vi.fn(), mode: "local", auth: null as any, push: vi.fn(), replace: vi.fn(), params: {} as Record<string, string>, query: {} as Record<string, string>, runs: null as any, project: null as any }));
vi.mock("@/api/client", () => ({ default: { get: m.get, patch: m.patch } }));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: m.push, replace: m.replace }), useRoute: () => ({ query: m.query, params: m.params }), RouterLink: { props: ['to'], template: "<a :href=\"to\"><slot /></a>" } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: m.toast }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => m.project }));
vi.mock("@/stores/runs", () => ({ useRunsStore: () => m.runs }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => m.auth }));
vi.mock("@/stores/workflow", () => ({ useWorkflowStore: () => ({ workflowId: null, nodes: [], edges: [] }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ config: ref({}), appMode: ref(m.mode), isCapabilityDisabled: () => false }) }));
vi.mock("@/composables/useDemoMode", () => ({ useDemoMode: () => ({ isDemoMode: ref(false) }) }));
import ModelsContent from "@/views/models/ModelsContent.vue";
type RetainedIdentity = { runId: number; projectId: number; workflowSha: string | null; buildSha: string | null };
function mountView(realTables = false, identity?: Ref<RetainedIdentity | null>) {
  return mount(ModelsContent, { global: { plugins: [PrimeVue], renderStubDefaultSlot: true,
    stubs: { WorkspaceHeader: true, WorkspaceContext: true, WorkspaceContextItem: identity ? false : true,
      RunDetailContent: identity ? defineComponent({ setup(_props, { expose }) {
        expose({ retainedIdentity: identity }); return () => h('div');
      } }) : true,
      BatchRunTab: true, EvidenceComparisonView: true, ComparisonPanel: true, QualificationApplications: true, QualificationPanel: true,
      SavedModelProjectTable: true, SavedModelQualification: true, ModelPromotionReview: true,
      Dialog: true, DataTable: !realTables, Dropdown: true, Button: identity ? false : true,
      InputText: true, ProgressSpinner: true, Tag: true, Textarea: true, LabelChips: true },
    directives: { tooltip: () => undefined } } });
}
describe("Runs workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); m.query = {}; m.params = {}; m.mode = "local";
    m.auth = reactive({ user: { id: 1 }, sessionRevision: 0 });
    m.project = { ensureProjectForBrowserTab: vi.fn(), currentProjectId: 1, currentProject: { id: 1, name: "Corn" } };
    m.runs = { runs: [], total: 0, selectedRunIds: new Set(), selectedCount: 0, runsLoading: false, comparison: null, loadError: null,
      fetchProjectRuns: vi.fn(), clearSelection: vi.fn(), resetProjectScope: vi.fn() };
    m.get.mockImplementation(async (path: string) => ({ data: path === "/deploy/capabilities" ? { privateBatchUpload: true } : path === "/runs" ? { runs: [], total: 0 } : [] }));
  });
  const fitted = { project_id: 1, artifact_uid: 'fitted-1', name: 'Saved PLS', model_type: 'pls', n_features: 13,
    n_components: 3, workflow_id: 7, workflow_version_id: 9, source_run_id: 42, is_deploy_ready: false };
  const recordedBuild = 'a673352c6a4102123547781126c90569129bcd35';
  function inspectionContext(value: RetainedIdentity | null = {
    runId: 42, projectId: 1, workflowSha: 'a'.repeat(64), buildSha: recordedBuild,
  }) {
    m.params = reactive({ runId: '42' }); m.query = reactive({ tab: 'inspect', project: '1' });
    m.project = reactive(m.project);
    const identity = ref(value);
    return { view: mountView(false, identity), identity };
  }
  it('shows retained hashes in the second context item with full accessible values and copies complete identity', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const { view } = inspectionContext(); await flushPromises();
    const items = view.findAll('.workspace-context-item');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain('Run #42');
    const item = items[1];
    expect(item.text()).toContain(`Workflow SHA ${'a'.repeat(12)}`);
    expect(item.text()).toContain(`Build SHA ${recordedBuild.slice(0, 12)}`);
    expect(item.get('strong').attributes('title')).toBe(`Workflow SHA-256: ${'a'.repeat(64)}`);
    expect(item.attributes('aria-label')).toContain(recordedBuild);
    expect(item.get('.run-identity-build > span').attributes('title')).toBe(`Build SHA-1: ${recordedBuild}`);
    await item.get('button[aria-label="Copy run identity for Run #42"]').trigger('click'); await flushPromises();
    expect(writeText).toHaveBeenCalledExactlyOnceWith(`Run #42\nWorkflow SHA-256: ${'a'.repeat(64)}\nBuild SHA-1: ${recordedBuild}`);
    expect(m.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: 'success' }));
    view.unmount();
  });
  it('hides stale context on route/project changes and when Inspect is left', async () => {
    const { view, identity } = inspectionContext(); await flushPromises();
    expect(view.findAll('.workspace-context-item')).toHaveLength(2);
    m.query.project = '2'; await flushPromises();
    expect(view.findAll('.workspace-context-item')).toHaveLength(1);
    m.query.project = '1'; await flushPromises();
    m.params.runId = '43'; await flushPromises();
    expect(view.findAll('.workspace-context-item')).toHaveLength(1);
    identity.value = { runId: 43, projectId: 1, workflowSha: 'b'.repeat(64), buildSha: recordedBuild };
    await flushPromises(); expect(view.findAll('.workspace-context-item')).toHaveLength(2);
    m.project.currentProjectId = 2; await flushPromises();
    expect(view.findAll('.workspace-context-item')).toHaveLength(1);
    m.project.currentProjectId = 1; delete m.params.runId; m.query.tab = 'run_history'; await flushPromises();
    expect(view.findAll('.workspace-context-item')).toHaveLength(1);
    view.unmount();
  });
  it('shows missing recorded hashes without substitution and disables copy', async () => {
    const { view } = inspectionContext({ runId: 42, projectId: 1, workflowSha: null, buildSha: null });
    await flushPromises();
    const item = view.findAll('.workspace-context-item')[1];
    expect(item.text()).toContain('Workflow SHA Not recorded');
    expect(item.text()).toContain('Build SHA Not recorded');
    expect(item.get('button').attributes('disabled')).toBeDefined();
    expect(item.attributes('aria-label')).not.toContain(recordedBuild);
    view.unmount();
  });
  it('reports clipboard failure without claiming success', async () => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    const { view } = inspectionContext(); await flushPromises();
    await view.get('button[aria-label="Copy run identity for Run #42"]').trigger('click'); await flushPromises();
    expect(m.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'Copy failed' }));
    expect(m.toast).not.toHaveBeenCalledWith(expect.objectContaining({ severity: 'success' }));
    view.unmount();
  });
  async function selectedModelView(listed = true) {
    m.query = { tab: 'models' };
    m.project = reactive(m.project);
    m.get.mockImplementation(async (path: string) => ({ data: path === '/models' ? (listed ? [fitted] : [])
      : path === '/models/fitted-1' ? fitted
      : path === '/deploy/applications' ? [{ handle: 'app-exact', model_artifact_uid: 'fitted-1', workflow_id: 7 }]
      : path === '/deploy/capabilities' ? { privateBatchUpload: true } : {} }));
    m.patch.mockResolvedValue({ data: { ...fitted, is_deploy_ready: true } });
    const view = mountView(); await flushPromises();
    if (listed) await view.get('.object-row').trigger('click');
    else await (view.vm as unknown as { selectOverviewModel: (uid: string) => Promise<void> }).selectOverviewModel('fitted-1');
    await flushPromises();
    return view;
  }
  it('makes a local application without a promotion decision and opens the exact released application', async () => {
    const view = await selectedModelView();
    expect(view.get('#selected-model-detail [label="Make Application"]').exists()).toBe(true);
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click'); await flushPromises();
    expect(m.patch).toHaveBeenCalledExactlyOnceWith('/models/fitted-1', { is_deploy_ready: true });
    expect(m.push).toHaveBeenCalledWith({ path: '/deploy', query: { project: 1, artifact: 'fitted-1', application: 'app-exact' } });
    expect(view.findComponent({ name: 'ModelPromotionReview' }).exists()).toBe(false);
    expect(view.findComponent({ name: 'SavedModelQualification' }).exists()).toBe(true);
    view.unmount();
  });
  it('copies only the selected model metadata as text instead of downloading a model-list file', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const view = await selectedModelView();
    await (view.vm as unknown as { exportActiveTab: () => Promise<void> }).exportActiveTab();
    expect(writeText).toHaveBeenCalledOnce();
    expect(JSON.parse(writeText.mock.calls[0][0])).toEqual(fitted);
    expect(m.patch).not.toHaveBeenCalled();
    view.unmount();
  });
  it('makes the exact selected model available even when it is outside the current catalog page', async () => {
    const view = await selectedModelView(false);
    expect(m.get).toHaveBeenCalledWith('/models/fitted-1');
    expect(view.findAll('.object-row')).toHaveLength(0);
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click'); await flushPromises();
    expect(m.patch).toHaveBeenCalledExactlyOnceWith('/models/fitted-1', { is_deploy_ready: true });
    expect(m.push).toHaveBeenCalledWith({ path: '/deploy', query: { project: 1, artifact: 'fitted-1', application: 'app-exact' } });
    view.unmount();
  });
  it.each(['enterprise', 'hybrid'])('retains the formal review flow for %s without a lightweight PATCH', async mode => {
    m.mode = mode;
    const view = await selectedModelView();
    expect(view.find('[label="Make Application"]').exists()).toBe(false);
    await view.get('#selected-model-detail [label="Review for promotion"]').trigger('click'); await flushPromises();
    expect(view.findComponent({ name: 'ModelPromotionReview' }).exists()).toBe(true);
    expect(m.patch).not.toHaveBeenCalled(); expect(m.push).not.toHaveBeenCalled();
    view.unmount();
  });
  it('keeps local withdrawal explicit rather than reopening or automatically remaking the application', async () => {
    const view = await selectedModelView();
    (view.vm as any).selectedModel = { ...fitted, is_deploy_ready: true }; await flushPromises();
    m.patch.mockResolvedValue({ data: { ...fitted, is_deploy_ready: false } });
    await view.get('#selected-model-detail [label="Withdraw deploy-ready"]').trigger('click'); await flushPromises();
    expect(m.patch).toHaveBeenCalledExactlyOnceWith('/models/fitted-1', { is_deploy_ready: false });
    expect(m.push).not.toHaveBeenCalled();
    view.unmount();
  });
  it.each(['project', 'session', 'selection', 'unmount'])('ignores a late local application response after %s changes', async scope => {
    const view = await selectedModelView();
    let finish!: (value: unknown) => void;
    m.patch.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click');
    if (scope === 'project') { m.project.currentProjectId = 2; m.project.currentProjectId = 1; }
    if (scope === 'session') m.auth.sessionRevision++;
    if (scope === 'selection') (view.vm as any).selectedModel = null;
    if (scope === 'unmount') view.unmount();
    finish({ data: { ...fitted, is_deploy_ready: true } }); await flushPromises();
    expect(m.push).not.toHaveBeenCalled(); expect(m.toast).not.toHaveBeenCalled();
    if (scope !== 'unmount') view.unmount();
  });
  it.each(['wrong_project', 'wrong_artifact', 'not_ready', 'missing_release'])('refuses a mismatched or unavailable local result: %s', async reason => {
    const view = await selectedModelView();
    if (reason === 'missing_release') m.get.mockImplementation(async () => ({ data: [] }));
    else m.patch.mockResolvedValueOnce({ data: { ...fitted, is_deploy_ready: reason !== 'not_ready',
      ...(reason === 'wrong_project' ? { project_id: 99 } : {}), ...(reason === 'wrong_artifact' ? { artifact_uid: 'other' } : {}) } });
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click'); await flushPromises();
    expect(m.push).not.toHaveBeenCalled(); expect(m.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error' }));
    expect(view.findComponent({ name: 'ModelPromotionReview' }).exists()).toBe(false);
    view.unmount();
  });
  it('does not navigate from a late released-application lookup after project A to B to A', async () => {
    const view = await selectedModelView();
    let finish!: (value: unknown) => void;
    const prior = m.get.getMockImplementation();
    m.get.mockImplementation((path: string) => path === '/deploy/applications'
      ? new Promise(resolve => { finish = resolve; }) : prior!(path));
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click'); await flushPromises();
    m.project.currentProjectId = 2; m.project.currentProjectId = 1;
    finish({ data: [{ handle: 'app-exact', model_artifact_uid: 'fitted-1', workflow_id: 7 }] }); await flushPromises();
    expect(m.push).not.toHaveBeenCalled(); view.unmount();
  });

  it('keeps a rejected local application out of Deploy and does not create a review decision', async () => {
    const view = await selectedModelView();
    m.patch.mockRejectedValueOnce(new Error('Saved artifact incompatible'));
    await view.get('#selected-model-detail [label="Make Application"]').trigger('click'); await flushPromises();
    expect(m.push).not.toHaveBeenCalled();
    expect(m.toast).toHaveBeenCalledWith(expect.objectContaining({ severity: 'error', summary: 'Application unavailable' }));
    expect(view.findComponent({ name: 'ModelPromotionReview' }).exists()).toBe(false);
    view.unmount();
  });

  it("offers a History map link without reading individual output payloads", async () => {
    m.query = { tab: "run_history" };
    m.runs.runs = [{ id: 42, name: "Saved run", status: "completed", run_kind: "data", executed_at: "2026-10-31", labels: [] }];
    m.runs.total = 1;
    const view = mountView(true); await flushPromises();
    expect(view.get('a.retained-map-link').attributes('href')).toBe('/runs/42?project=1&tab=inspect&view=Summary#retained-observation-exclusions');
    expect(m.get.mock.calls.some(([url]) => String(url).includes('/outputs/'))).toBe(false);
    view.unmount();
  });
  it("clears campaign evidence references when comparing newly selected saved runs", async () => {
    m.query = {tab: "run_history", evidence: "old-campaign-references", project: "1"};
    m.runs.selectedCount = 2; m.runs.selectedRunIds = new Set([41, 42]);
    m.runs.compareProjectRuns = vi.fn().mockImplementation(async () => {
      m.runs.comparison = {runs: [], metric_keys: [], diff: {}};
    });
    const view = mountView(); await flushPromises();
    await (view.vm as unknown as {handleCompareRuns: () => Promise<void>}).handleCompareRuns(); await flushPromises();
    expect(m.runs.compareProjectRuns).toHaveBeenCalledWith(1, [41, 42]);
    expect(m.replace).toHaveBeenCalledWith({query: {tab: "compare", project: "1"}});
    view.unmount();
  });
  it("replaces old project deep links when the active project changes", async () => {
    m.query = { project: "1", artifact: "old-model", evidence: "old-evidence", tab: "models" };
    m.project = reactive(m.project);
    m.runs.resetProjectScope = vi.fn();
    const view = mountView(); await flushPromises();
    m.replace.mockClear();
    m.project.currentProjectId = 2;
    m.project.currentProject = { id: 2, name: "Iris" };
    await flushPromises();
    expect(m.replace).toHaveBeenCalledWith({
      path: "/runs", query: { project: "2", tab: "run_history" },
    });
    expect(m.runs.fetchProjectRuns).toHaveBeenLastCalledWith(2, 0, "all", undefined, "executed_at", "desc");
    view.unmount();
  });
  it.each(["artifacts", "models"])("preserves the %s deep link with Inspect between History and Compare", async (tab) => {
    m.query.tab = tab;
    const view = mountView(); await flushPromises();
    const tabs = view.findAll('[role="tab"]');
    expect(tabs.map(t => t.text())).toEqual(["History", "Inspect", "Compare", "Models", "Batch"]);
    expect(tabs[3].attributes("aria-selected")).toBe("true");
    expect(view.find('[label="Refresh"]').exists()).toBe(false);
    expect(view.find('workspace-context-item-stub').attributes("label")).toBe("Models");
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
    expect(view.text()).toContain("Choose a run in History");
    expect(view.findAll('h2').some(heading => heading.text() === 'Inspect')).toBe(false);
    expect(view.findComponent({ name: "RunDetailContent" }).exists()).toBe(false);
    view.unmount();
  });
  it("uses the same canonical empty-state presentation for Inspect and Compare", async () => {
    for (const tab of ["inspect", "compare"]) {
      m.query = { tab };
      const view = mountView(); await flushPromises();
      const message = tab === "inspect" ? "Choose a run in History." : "Select 2–10 runs in History to compare.";
      const state = view.findAllComponents({ name: "WorkspaceState" })
        .find(component => component.props("message") === message)!;
      expect(state.props("kind")).toBe("empty");
      expect(state.props("variant")).toBe("page");
      expect(state.classes()).toContain("workspace-state--page");
      view.unmount();
    }
  });
  it("groups model history, saved evidence and imports without duplicate inner titles", async () => {
    m.query = { tab: "models" };
    const view = mountView(); await flushPromises();
    const panels = view.findAllComponents({ name: "Panel" });
    expect(panels.map(panel => panel.props("header"))).toEqual(["Local Model History", "Saved Models"]);
    expect(panels.every(panel => panel.props("toggleable"))).toBe(true);
    expect(panels.map(panel => panel.props("collapsed"))).toEqual([false, true]);
    expect(view.getComponent({ name: "QualificationApplications" }).exists()).toBe(true);
    view.unmount();
  });
  it("reopens exact source-run component evidence for a saved model", async () => {
    m.query.tab = "artifacts";
    const model = { artifact_uid: "model-1", name: "PLS moisture", display_name: "PLS moisture",
      model_type: "PLS", n_features: 8, n_components: 2, source_run_id: 42, node_id: "fit",
      workflow_id: 7, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
    const curve = { schema_version: "spectrasherpa-pls-component-curve/1", selected_components: 2,
      requested_components: 2, selected_in_curve: true, selection_rule: "manual_parameter",
      n_calibration: 12, response_names: ["Moisture"], response_units: ["%"],
      calibration: [{ components: 1, rmsec: [0.8] }, { components: 2, rmsec: [0.5] }],
      cross_validation: { status: "unavailable", reason: "Too few independent groups." } };
    m.get.mockImplementation(async (path: string) => {
      if (path === "/models") return { data: [model] };
      if (path === "/runs/42/evidence") return { data: { evidence: { outputs: {
        fit: { component_curve: { state: "exact", storage: "file" } },
      } } } };
      if (path === "/runs/42/outputs/fit/component_curve") return { data: { value: curve } };
      return { data: {} };
    });
    for (let reopen = 0; reopen < 2; reopen++) {
      const view = mountView(); await flushPromises();
      await view.get(".object-row").trigger("click"); await flushPromises();
      expect(view.get('a.retained-map-link').attributes('href')).toBe('/runs/42?project=1&tab=inspect&view=Summary#retained-observation-exclusions');
      expect(view.get('[aria-label="Saved model component evidence"]').text()).toContain("Latent variables");
      expect(view.get('[aria-label="Saved model component evidence"]').text()).toContain("Too few independent groups");
      expect(m.get).toHaveBeenCalledWith("/runs/42/outputs/fit/component_curve", { params: { project_id: 1 } });
      view.unmount();
    }
  });
  it.each([true, false])("opens the exact artifact deep link, including beyond the current page: listed=%s", async listed => {
    m.query = { tab: "models", project: "1", artifact: "requested-model" };
    const requested = { project_id: 1, artifact_uid: "requested-model", name: "Requested PCA", model_type: "pca" };
    m.get.mockImplementation(async (path: string) => {
      if (path === "/models") return { data: listed ? [requested] : [] };
      if (path === "/models/requested-model") return { data: requested };
      return { data: {} };
    });
    const view = mountView(); await flushPromises();
    (view.vm as any).localModelsCollapsed = true;
    await (view.vm as any).applyArtifactDeepLink(); await flushPromises();
    expect(view.findAll('[role="tab"]')[3].attributes('aria-selected')).toBe('true');
    expect(view.findAllComponents({ name: "Panel" })[0].props('collapsed')).toBe(false);
    expect((view.vm as any).selectedModel.artifact_uid).toBe('requested-model');
    expect(view.get('#selected-model-detail').isVisible()).toBe(true);
    expect((view.vm as any).selectedArtifactUids.size).toBe(0);
    if (!listed) expect(m.get).toHaveBeenCalledWith('/models/requested-model');
    view.unmount();
  });
  it("keeps the latest saved-model overview selection when an earlier lookup resolves late", async () => {
    m.query.tab = "artifacts";
    let resolveFirst!: (value: {data: unknown}) => void;
    const first = new Promise<{data: unknown}>(resolve => { resolveFirst = resolve; });
    m.get.mockImplementation(async (path: string) => {
      if (path === "/models") return {data: []};
      if (path === "/models/model-a") return first;
      if (path === "/models/model-b") return {data: {
        project_id: 1, artifact_uid: "model-b", name: "Second model", model_type: "pca",
      }};
      return {data: {}};
    });
    const view = mountView(); await flushPromises();
    const table = view.findComponent({name: "SavedModelProjectTable"});
    table.vm.$emit("select", "model-a");
    table.vm.$emit("select", "model-b");
    await flushPromises();
    expect((view.vm as any).selectedModel?.artifact_uid).toBe("model-b");
    resolveFirst({data: {project_id: 1, artifact_uid: "model-a", name: "First model", model_type: "pca"}});
    await flushPromises();
    expect((view.vm as any).selectedModel?.artifact_uid).toBe("model-b");
    view.unmount();
  });
  it('rejects a delayed artifact deep link after a manual selection and clears unrelated details on failure', async () => {
    let finish!: (value: { data: unknown }) => void;
    const delayed = new Promise<{ data: unknown }>(resolve => { finish = resolve; });
    const chosen = { project_id: 1, artifact_uid: 'chosen', name: 'Chosen PCA', model_type: 'pca' };
    m.query = { tab: 'models' };
    m.get.mockImplementation(async (path: string) => {
      if (path === '/models') return { data: [chosen] };
      if (path === '/models/slow') return delayed;
      if (path === '/models/missing') throw new Error('Model not found');
      return { data: {} };
    });
    const view = mountView(); await flushPromises();
    m.query.artifact = 'slow';
    const pending = (view.vm as any).applyArtifactDeepLink();
    await view.get('.object-row').trigger('click'); await flushPromises();
    finish({ data: { project_id: 1, artifact_uid: 'slow', name: 'Old PCA', model_type: 'pca' } });
    await pending; await flushPromises();
    expect((view.vm as any).selectedModel.artifact_uid).toBe('chosen');
    m.query.artifact = 'missing';
    await (view.vm as any).applyArtifactDeepLink(); await flushPromises();
    expect((view.vm as any).selectedModel).toBeNull();
    expect(view.find('#selected-model-detail').exists()).toBe(false);
    view.unmount();
  });
  it("shows History loading, empty and failure through the shared state, and Retry reloads", async () => {
    m.runs.runsLoading = true;
    let view = mountView(); await flushPromises();
    const loading = view.get(".workspace-state");
    expect(loading.attributes("aria-busy")).toBe("true");
    expect(loading.text()).toContain("Loading runs…");
    view.unmount();

    m.runs.runsLoading = false;
    view = mountView(); await flushPromises();
    expect(view.get(".workspace-state--page").text()).toContain("No saved runs yet.");
    view.unmount();

    m.runs.loadError = "Could not load run history. Retry to refresh.";
    view = mountView(); await flushPromises();
    const alert = view.get('[role="alert"]');
    expect(alert.text()).toContain("Could not load run history.");
    const calls = m.runs.fetchProjectRuns.mock.calls.length;
    alert.findComponent({ name: "Button" }).vm.$emit("click"); await flushPromises();
    expect(m.runs.fetchProjectRuns.mock.calls.length).toBe(calls + 1);
    view.unmount();
  });
});
