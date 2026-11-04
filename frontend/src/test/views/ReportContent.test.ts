import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { enableAutoUnmount, flushPromises, shallowMount } from "@vue/test-utils";
import { reactive } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import ReportContent from "@/views/report/ReportContent.vue";
const mocks = vi.hoisted(() => ({ get: vi.fn(), toast: vi.fn(), fetch: vi.fn(), workflows: vi.fn(), runs: vi.fn(), project: vi.fn() }));
const project = reactive({ currentProjectId: 99 as number | null, fetchProject: mocks.project, ensureProjectForBrowserTab: vi.fn() });
const auth = reactive({ user: { id: 1 }, sessionRevision: 1 });
const report = reactive({ selectedWorkflowId: null as number | null, selectedRunIds: [] as number[],
  workflows: [] as { id: number; name: string }[], availableRuns: [] as unknown[],
  reportData: null, isReady: false, sections: {}, fetchReportData: mocks.fetch,
  fetchWorkflows: mocks.workflows, fetchRunsForWorkflow: mocks.runs });
vi.mock("@/api/client", () => ({ default: { get: mocks.get } }));
vi.mock("primevue/usetoast", () => ({ useToast: () => ({ add: mocks.toast }) }));
vi.mock("@/stores/project", () => ({ useProjectStore: () => project }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => auth }));
vi.mock("@/stores/report", () => ({ useReportStore: () => report }));
vi.mock("@/stores/workbook", () => ({ useWorkbookStore: () => ({ projectId: 99 }) }));
vi.mock("@/stores/advisor", () => ({ useAdvisorStore: () => ({ switchScope: vi.fn() }) }));
vi.mock("@/composables/useAppConfig", () => ({ useAppConfig: () => ({ isFeatureEnabled: () => false, appConfig: { value: {} } }) }));
vi.mock("@/lib/sherpaAttention", () => ({ focusSection: vi.fn() }));
enableAutoUnmount(afterEach);
beforeEach(() => {
  vi.clearAllMocks(); project.currentProjectId = 99; auth.sessionRevision = 1;
  report.selectedWorkflowId = null; report.selectedRunIds = [];
  mocks.get.mockResolvedValue({ data: { id: 42, workflow_id: 7, project_id: 3 } });
  mocks.project.mockImplementation(async (id: number) => { project.currentProjectId = id; return { id }; });
});
async function open(query = "workflow=7&run=42") {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/report", component: ReportContent }] });
  await router.push(`/report?${query}`); await router.isReady();
  const wrapper = shallowMount(ReportContent, { global: { plugins: [router], stubs: { WorkspaceTabs: true } } });
  await flushPromises(); return { wrapper, router };
}
describe("retained Report links", () => {
  it.each(["", "&project=3"])("derives project from the authorized run despite stale selection (%s)", async suffix => {
    await open(`workflow=7&run=42${suffix}`);
    expect(mocks.get).toHaveBeenCalledWith("/workflows/7/runs/42", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(mocks.project).toHaveBeenCalledWith(3, expect.any(Object));
    expect(project.currentProjectId).toBe(3); expect(report.selectedWorkflowId).toBe(7);
    expect(report.selectedRunIds).toEqual([42]); expect(mocks.fetch).toHaveBeenCalledOnce();
    expect(mocks.toast).not.toHaveBeenCalled();
  });
  it("refuses a conflicting URL project without selecting it or generating a report", async () => {
    await open("workflow=7&run=42&project=99");
    expect(mocks.project).not.toHaveBeenCalled(); expect(mocks.fetch).not.toHaveBeenCalled();
    expect(mocks.toast).toHaveBeenCalledOnce();
    const notification = mocks.toast.mock.calls[0][0];
    expect(notification).toEqual(expect.objectContaining({ summary: "Report unavailable", life: 5000 }));
    expect(notification.detail).not.toBe(notification.summary);
  });
  it.each(["workflow=0&run=42", "workflow=7&run=no", "run=42"])("refuses malformed link %s without an active-project fallback", async query => {
    await open(query);
    expect(mocks.get).not.toHaveBeenCalled(); expect(mocks.project).not.toHaveBeenCalled();
    expect(mocks.fetch).not.toHaveBeenCalled(); expect(mocks.toast).toHaveBeenCalledOnce();
  });
  it.each([403, 404])("refuses foreign/missing run HTTP %s with one finite notification", async status => {
    mocks.get.mockRejectedValue({ response: { status } }); await open();
    expect(mocks.project).not.toHaveBeenCalled(); expect(mocks.fetch).not.toHaveBeenCalled();
    expect(project.currentProjectId).toBe(99); expect(mocks.toast).toHaveBeenCalledOnce();
  });
  it.each([{ id: 43, workflow_id: 7, project_id: 3 }, { id: 42, workflow_id: 8, project_id: 3 },
    { id: 42, workflow_id: 7, project_id: null }])("refuses inconsistent retained identity %j", async run => {
    mocks.get.mockResolvedValue({ data: run }); await open();
    expect(mocks.fetch).not.toHaveBeenCalled(); expect(mocks.project).not.toHaveBeenCalled();
  });
  it.each(["route", "project", "session", "unmount"])("discards late run reads after %s changes", async change => {
    let resolve!: (value: unknown) => void;
    mocks.get.mockImplementation(() => new Promise(done => { resolve = done; }));
    const { wrapper, router } = await open();
    if (change === "route") { await router.push("/report?workflow=8&run=43"); await router.push("/report?workflow=7&run=42"); }
    if (change === "project") { project.currentProjectId = 5; project.currentProjectId = 99; }
    if (change === "session") auth.sessionRevision++;
    if (change === "unmount") wrapper.unmount();
    resolve({ data: { id: 42, workflow_id: 7, project_id: 3 } }); await flushPromises();
    expect(mocks.project).not.toHaveBeenCalled(); expect(mocks.fetch).not.toHaveBeenCalled();
    expect(mocks.toast).not.toHaveBeenCalled();
  });
  it("does not reselect the already authorized owning project", async () => {
    project.currentProjectId = 3; await open();
    expect(mocks.project).not.toHaveBeenCalled(); expect(mocks.fetch).toHaveBeenCalledOnce();
  });
  it("passes route cancellation into project admission and rejects its late completion", async () => {
    let resolve!: (value: unknown) => void;
    mocks.project.mockImplementation(() => new Promise(done => { resolve = done; }));
    const { router } = await open();
    const owner = mocks.project.mock.calls[0][1];
    await router.push("/report?workflow=8&run=43");
    expect(owner.signal.aborted).toBe(true);
    resolve({ id: 3 }); await flushPromises();
    expect(mocks.fetch).not.toHaveBeenCalled(); expect(mocks.toast).not.toHaveBeenCalled();
  });

});
