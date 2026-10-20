import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, disposePinia, setActivePinia, type Pinia } from "pinia";
import { effectScope } from "vue";
import { flushPromises } from "@vue/test-utils";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useDataStore } from "@/stores/data";
import { useDataSourceStore } from "@/stores/dataSources";
import { useExperimentStore } from "@/stores/experiment";
import { useProjectStore } from "@/stores/project";
import { useProjectProvenanceStore } from "@/stores/projectProvenance";
import { useRunsStore } from "@/stores/runs";
import { useWorkbookStore } from "@/stores/workbook";
import { useWorkflowStore } from "@/stores/workflow";
import {
  _clearProjectScopeRegistryForTests,
  registerProjectScopeReset,
  runProjectScopeResets,
} from "@/stores/projectScopeRegistry";

vi.mock("@/api/client", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

// Deliberately ignores AbortSignal. Cancellation alone cannot establish safety.
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

let pinia: Pinia;
beforeEach(() => {
  _clearProjectScopeRegistryForTests();
  pinia = createPinia();
  setActivePinia(pinia);
  localStorage.clear();
  vi.resetAllMocks();
  useAuthStore().user = { id: 7, username: "first" };
  useAuthStore().token = "session-one";
  useProjectStore().currentProjectId = 1;
});
afterEach(() => { disposePinia(pinia); _clearProjectScopeRegistryForTests(); });

describe("store-owned scope, independent of mounted pages", () => {
  it("keeps concurrent file inventories alive until their shared selection changes", async () => {
    const data = useDataStore();
    data.activeExperimentId = 44;
    const responses = [deferred<{ data: { assets: never[] } }>(), deferred<{ data: { assets: never[] } }>()];
    let index = 0;
    vi.mocked(api.get).mockImplementation((_url, config) => {
      const response = responses[index++];
      config?.signal?.addEventListener?.("abort", () => response.reject(new DOMException("Aborted", "AbortError")));
      return response.promise;
    });
    const first = data.fetchFileAssets(44, 1);
    const second = data.fetchFileAssets(44, 2);
    expect(vi.mocked(api.get).mock.calls.every(([, config]) => !config?.signal?.aborted)).toBe(true);
    responses.forEach(response => response.resolve({ data: { assets: [] } }));
    expect(await Promise.all([first, second])).toEqual([{ assets: [] }, { assets: [] }]);
    const signals = vi.mocked(api.get).mock.calls.map(([, config]) => config?.signal);
    data.activeExperimentId = 45;
    expect(signals.every(signal => signal?.aborted)).toBe(true);
  });

  it("keeps the initial graph load when its already-active sheet is clicked", async () => {
    const workbook = useWorkbookStore();
    const workflow = useWorkflowStore();
    const held = deferred<void>();
    vi.mocked(api.get).mockResolvedValue({ data: [{ id: 9, name: "Initial", purpose: "analysis", sheet_order: 0 }] });
    vi.spyOn(workflow, "loadWorkflow").mockImplementation(async (id, _intent, current) => {
      await held.promise;
      if (current?.()) workflow.workflowId = id;
    });
    const loading = workbook.loadSheets(1);
    await flushPromises();
    expect(workbook.activeSheet?.workflowId).toBe(9);
    expect(workbook.isLoading).toBe(true);
    await workbook.switchSheet(0);
    expect(workbook.isLoading).toBe(true);
    held.resolve();
    await loading;
    expect(workflow.workflowId).toBe(9);
    expect(workbook.isLoading).toBe(false);
  });

  it.each(["logout", "token", "user"] as const)("does not restore a late actor after %s", async (change) => {
    const auth = useAuthStore();
    const late = deferred<{ data: { id: number; username: string } }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = auth.initializeActor();
    const signal = vi.mocked(api.get).mock.calls[0][1]?.signal;
    if (change === "logout") auth.clearCredentials();
    if (change === "token") auth.token = "session-two";
    if (change === "user") auth.user = { id: 8, username: "second" };
    expect(signal?.aborted).toBe(true);
    late.resolve({ data: { id: 7, username: "late profile" } });
    await pending;
    expect(auth.user?.username).not.toBe("late profile");
    if (change === "logout") expect(auth.user).toBeNull();
  });

  it("ignores a project A → B → A reply and keeps the newer loading owner", async () => {
    const project = useProjectStore();
    const old = deferred<{ data: { id: number; name: string } }>();
    const latest = deferred<{ data: { id: number; name: string } }>();
    vi.mocked(api.get).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
    const first = project.fetchProject(1);
    project.currentProjectId = 2;
    project.currentProjectId = 1;
    const second = project.fetchProject(1);
    old.reject(new Error("old failure"));
    await first;
    expect(project.error).toBeNull();
    expect(project.isLoading).toBe(true);
    latest.resolve({ data: { id: 1, name: "current" } });
    await second;
    expect(project.currentProject?.name).toBe("current");
    expect(project.isLoading).toBe(false);
  });

  it("resets Data on token rotation without mounting DataContent, preserving saved selection", async () => {
    const data = useDataStore();
    const late = deferred<{ data: unknown[] }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = data.selectExperiment(44);
    useAuthStore().token = "session-two";
    late.resolve({ data: [{ id: 1, file_path: "old.csv" }] });
    await pending;
    expect(data.activeExperimentId).toBeNull();
    expect(data.experimentFiles).toEqual([]);
    expect(data.experimentFilesLoading).toBe(false);
    expect(localStorage.getItem("spectra_sherpa_last_experiment_7_1")).toBe("44");
  });

  it("rejects late catalog success after project A → B → A", async () => {
    const data = useDataStore();
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = data.fetchCatalog();
    useProjectStore().currentProjectId = 2;
    useProjectStore().currentProjectId = 1;
    late.resolve({ data: { experiments: [{ id: 99 }], library: [], builder: [] } });
    await pending;
    expect(data.availableDatasets).toBeNull();
    expect(data.catalogLoading).toBe(false);
  });

  it("notifies registered views on same-user token rotation", () => {
    const reset = vi.fn();
    registerProjectScopeReset(reset);
    useAuthStore().token = "session-two";
    expect(reset).toHaveBeenCalledOnce();
    expect(useProjectStore().currentProjectId).toBeNull();
  });

  it("does not restore a stale project data-source list after reset", async () => {
    const sources = useDataSourceStore();
    const late = deferred<{ data: unknown[] }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = sources.loadProjectDataSources(1);
    runProjectScopeResets();
    late.resolve({ data: [{ id: 5, display_name: "old" }] });
    expect(await pending).toEqual([]);
    expect(sources.projectId).toBeNull();
    expect(sources.dataSources).toEqual([]);
  });

  it("rejects every stale experiment slice after A → B → A", async () => {
    const experiments = useExperimentStore();
    const oldDetail = deferred<{ data: unknown }>();
    const oldFiles = deferred<{ data: unknown[] }>();
    const oldVersions = deferred<{ data: unknown[] }>();
    vi.mocked(api.get).mockReturnValueOnce(oldDetail.promise)
      .mockReturnValueOnce(oldFiles.promise).mockReturnValueOnce(oldVersions.promise);
    const first = experiments.selectExperiment(44).catch(error => error);
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    await experiments.selectExperiment(45);
    vi.mocked(api.get).mockResolvedValueOnce({ data: { id: 44, name: "current" } })
      .mockResolvedValueOnce({ data: [{ id: 2 }] }).mockResolvedValueOnce({ data: [{ id: 3 }] });
    await experiments.selectExperiment(44);
    oldDetail.resolve({ data: { id: 44, name: "stale" } });
    oldFiles.resolve({ data: [{ id: 99 }] });
    oldVersions.reject(new Error("old versions unavailable"));
    await first;
    expect(experiments.currentExperiment?.name).toBe("current");
    expect(experiments.files).toEqual([{ id: 2 }]);
    expect(experiments.versions).toEqual([{ id: 3 }]);
    expect(experiments.error).toBeNull();
    expect(experiments.loading).toBe(false);
  });

  it("invalidates cached and pending provenance on a session change", async () => {
    const provenance = useProjectProvenanceStore();
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = provenance.refresh(1);
    useAuthStore().token = "session-two";
    late.resolve({ data: { project_id: 1, records: [{ name: "previous session" }] } });
    await pending;
    expect(provenance.summary).toBeNull();
    expect(provenance.loading).toBe(false);
    expect(provenance.projectId).toBeNull();
  });

  it("keeps current inspection/loading when an old file request fails after A → B → A", async () => {
    const data = useDataStore();
    data.activeExperimentId = 44;
    const old = deferred<{ data: unknown }>();
    const latest = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
    const first = data.inspectFile(1, "a.csv");
    const firstFailure = first.catch(error => error);
    data.activateFile(2, "b.csv");
    const second = data.inspectFile(1, "a.csv");
    old.reject(new Error("stale inspection"));
    await firstFailure;
    expect(data.fileInfoError).toBeNull();
    expect(data.fileInfoLoading).toBe(true);
    latest.resolve({ data: { dataset_id: "current", data: [[3]] } });
    await second;
    expect(data.fileInfo?.dataset_id).toBe("current");
    expect(data.fileInfoLoading).toBe(false);
  });

  it("keeps a pending inspection when only same-identity profile fields refresh", async () => {
    const data = useDataStore();
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(late.promise);
    const pending = data.inspectFile(1, "a.csv");
    const signal = vi.mocked(api.post).mock.calls[0][2]?.signal;
    useAuthStore().user = { id: 7, username: "updated display name" };
    expect(useProjectStore().currentProjectId).toBe(1);
    expect(signal?.aborted).toBe(false);
    late.resolve({ data: { dataset_id: "current" } });
    await pending;
    expect(data.fileInfo?.dataset_id).toBe("current");
  });

  it("aborts a disposed store's pending inspection without applying its late result", async () => {
    const data = useDataStore();
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(late.promise);
    const pending = data.inspectFile(1, "a.csv");
    const signal = vi.mocked(api.post).mock.calls[0][2]?.signal;
    data.$dispose();
    expect(signal?.aborted).toBe(true);
    late.resolve({ data: { dataset_id: "too late" } });
    await pending;
    expect(data.fileInfo).toBeNull();
    expect(data.fileInfoLoading).toBe(false);
  });

  it("does not reselect an old dataset after a server-accepted upload", async () => {
    const data = useDataStore();
    data.activeExperimentId = 44;
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(late.promise);
    const pending = data.uploadFile(44, new File(["x"], "x.csv"), "raw");
    useProjectStore().currentProjectId = 2;
    late.resolve({ data: { id: 9, file_path: "raw/x.csv", stage: "raw", created_at: "" } });
    expect((await pending).id).toBe(9); // Accepted write is not reported as rolled back.
    expect(data.activeExperimentId).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("guards legacy comparisons and their finally against a newer selection", async () => {
    const runs = useRunsStore();
    const old = deferred<{ data: unknown }>();
    const latest = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
    const first = runs.compareRuns(1, [1, 2]);
    runs.toggleRunSelection(3);
    const second = runs.compareRuns(1, [2, 3]);
    old.resolve({ data: { marker: "old" } });
    await first;
    expect(runs.comparison).toBeNull();
    expect(runs.comparisonLoading).toBe(true);
    latest.resolve({ data: { marker: "current" } });
    await second;
    expect(runs.comparison).toEqual({ marker: "current" });
    expect(runs.comparisonLoading).toBe(false);
  });

  it("does not let an accepted run deletion mutate the replacement list", async () => {
    const runs = useRunsStore();
    const late = deferred<unknown>();
    runs.runs = [{ id: 9, name: "old" }] as never;
    vi.mocked(api.delete).mockReturnValueOnce(late.promise);
    const pending = runs.deleteProjectRun(1, 9);
    useProjectStore().currentProjectId = 2;
    useProjectStore().currentProjectId = 1;
    runs.runs = [{ id: 9, name: "reopened" }] as never;
    runs.selectedRunIds = new Set([9]);
    late.resolve({});
    await pending;
    expect(runs.runs).toEqual([{ id: 9, name: "reopened" }]);
    expect(runs.selectedRunIds.has(9)).toBe(true);
  });

  it("does not prepend a saved run after switching workflow lists", async () => {
    const runs = useRunsStore();
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockResolvedValue({ data: { runs: [], total: 0 } });
    await runs.fetchRuns(1);
    vi.mocked(api.post).mockReturnValueOnce(late.promise);
    const pending = runs.saveRun(1, { run_id: 9 });
    await runs.fetchRuns(2);
    late.resolve({ data: { id: 9, workflow_id: 1 } });
    expect((await pending).id).toBe(9);
    expect(runs.runs).toEqual([]);
  });

  it("does not apply a workbook refresh after project A → B → A", async () => {
    const workbook = useWorkbookStore();
    workbook.projectId = 1;
    const late = deferred<{ data: unknown[] }>();
    vi.mocked(api.get).mockReturnValueOnce(late.promise);
    const pending = workbook.refreshSheets();
    useProjectStore().currentProjectId = 2;
    useProjectStore().currentProjectId = 1;
    late.resolve({ data: [{ id: 9, name: "stale sheet" }] });
    await pending;
    expect(workbook.sheets).toEqual([]);
    expect(workbook.projectId).toBeNull();
  });

  it("cancels a sheet switch awaiting autosave when the active sheet is clicked again", async () => {
    const workbook = useWorkbookStore();
    workbook.projectId = 1;
    workbook.sheets = [1, 2].map(workflowId => ({
      workflowId, name: `Sheet ${workflowId}`, purpose: "analysis", tabColor: null, sheetOrder: workflowId,
    }));
    const workflow = useWorkflowStore();
    workflow.workflowId = 1;
    workflow.hasUnsavedChanges = true;
    const saved = deferred<number>();
    vi.spyOn(workflow, "saveWorkflow").mockReturnValueOnce(saved.promise);
    const load = vi.spyOn(workflow, "loadWorkflow").mockResolvedValue();
    const pending = workbook.switchSheet(1);
    await workbook.switchSheet(0);
    saved.resolve(1);
    await pending;
    expect(workbook.activeIndex).toBe(0);
    expect(load).not.toHaveBeenCalled();
  });

  it("does not mark the new sheet clean after an accepted save of the old sheet", async () => {
    const workflow = useWorkflowStore();
    workflow.workflowId = 1;
    workflow.workflowName = "old";
    workflow.hasUnsavedChanges = true;
    const saved = deferred<{ data: unknown }>();
    vi.mocked(api.put).mockReturnValueOnce(saved.promise);
    const pending = workflow.saveWorkflow();
    workflow.clearWorkflow();
    workflow.workflowId = 2;
    workflow.workflowName = "new local edits";
    workflow.hasUnsavedChanges = true;
    saved.resolve({ data: { id: 1, name: "old", integrity_hash: "old-hash" } });
    expect(await pending).toBe(1);
    expect(workflow.workflowId).toBe(2);
    expect(workflow.hasUnsavedChanges).toBe(true);
    expect(workflow.workflowHash).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("does not clear a newer retained snapshot after old preflight completes", async () => {
    const workflow = useWorkflowStore();
    workflow.lastExecutionResults = { previousSheet: "must not appear under the new graph" };
    vi.spyOn(workflow, "fetchNodeLibrary");
    workflow.nodeLibrary.set("unused", {} as never);
    workflow.typeRegistry = { types: {} } as never;
    const oldPreflight = deferred<{ data: unknown }>();
    let calls = 0;
    vi.mocked(api.post).mockImplementation(async () => {
      if (++calls === 1) return oldPreflight.promise;
      return { data: { is_valid: true, issues: [], semantic_edges: [] } };
    });
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === "/workflows/1") return { data: { id: 1, name: "sheet", nodes: [], edges: [] } };
      if (url === "/workflows/1/runs/22") return {
        data: { id: 22, results_summary: { result: "new run" }, matches_current_definition: true },
      };
      throw new Error(`Unexpected request ${url}`);
    });
    const old = workflow.loadWorkflow(1, 11);
    await vi.waitFor(() => expect(calls).toBe(1));
    expect(workflow.lastExecutionResults).toBeNull();
    await workflow.loadWorkflow(1, 22);
    oldPreflight.resolve({ data: { is_valid: true, issues: [], semantic_edges: [] } });
    await old;
    expect(workflow.restoredRunId).toBe(22);
    expect(workflow.lastExecutionResults).toEqual({ result: "new run" });
    expect(api.get).not.toHaveBeenCalledWith("/workflows/1/runs/11", expect.anything());
  });

  it("does not replace current evidence notice with an old retained-run failure", async () => {
    const workflow = useWorkflowStore();
    workflow.nodeLibrary.set("unused", {} as never);
    workflow.typeRegistry = { types: {} } as never;
    const oldRun = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockResolvedValue({ data: { is_valid: true, issues: [], semantic_edges: [] } });
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === "/workflows/1") return { data: { id: 1, name: "sheet", nodes: [], edges: [] } };
      if (url === "/workflows/1/runs/11") return oldRun.promise;
      if (url === "/workflows/1/runs/22") return {
        data: { id: 22, results_summary: { result: "new run" }, matches_current_definition: true },
      };
      throw new Error(`Unexpected request ${url}`);
    });
    const old = workflow.loadWorkflow(1, 11);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalledWith("/workflows/1/runs/11", expect.anything()));
    await workflow.loadWorkflow(1, 22);
    const notice = workflow.restoredEvidenceNotice;
    oldRun.reject(new Error("old unavailable"));
    await old;
    expect(workflow.restoredRunId).toBe(22);
    expect(workflow.restoredEvidenceNotice).toBe(notice);
  });

  it("keeps the new execution's busy state after a previous sheet's execution fails", async () => {
    const workflow = useWorkflowStore();
    workflow.workflowId = 1;
    const oldRun = deferred<{ data: unknown }>();
    const newRun = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockImplementation(async (url) => {
      if (url.endsWith("/preflight")) return { data: { is_valid: true, issues: [], semantic_edges: [] } };
      if (url === "/workflows/1/execute") return oldRun.promise;
      if (url === "/workflows/2/execute") return newRun.promise;
      throw new Error(`Unexpected request ${url}`);
    });
    const first = workflow.executeWorkflow().catch(error => error);
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith("/workflows/1/execute", expect.anything(), expect.anything()));
    workflow.clearWorkflow();
    workflow.workflowId = 2;
    const second = workflow.executeWorkflow();
    await vi.waitFor(() => expect(api.post).toHaveBeenCalledWith("/workflows/2/execute", expect.anything(), expect.anything()));
    oldRun.reject(new Error("old execution failed"));
    expect((await first).name).toBe("AbortError");
    expect(workflow.isExecuting).toBe(true);
    expect(workflow.isLoading).toBe(true);
    newRun.resolve({ data: { status: "completed", run_id: 22, results: { model: "current" } } });
    await second;
    expect(workflow.isExecuting).toBe(false);
    expect(workflow.restoredRunId).toBe(22);
    expect(workflow.lastExecutionResults).toEqual({ model: "current" });
  });

  it("unregisters reset callbacks with their effect lifetime", () => {
    const scope = effectScope();
    const reset = vi.fn();
    scope.run(() => registerProjectScopeReset(reset));
    scope.stop();
    runProjectScopeResets();
    expect(reset).not.toHaveBeenCalled();
  });
});
