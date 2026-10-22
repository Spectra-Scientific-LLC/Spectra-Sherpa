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
  it("shares admission for concurrent callers of the same project", async () => {
    const project = useProjectStore();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(held.promise);
    const first = project.fetchProject(2);
    const second = project.fetchProject(2);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.get).mock.calls[0][1]?.signal?.aborted).toBe(false);
    held.resolve({ data: { id: 2, name: "Shared" } });
    expect((await Promise.all([first, second])).map(item => item?.id)).toEqual([2, 2]);
    expect(project.currentProjectId).toBe(2);
  });

  it("does not discard an update refusal during a same-project refresh", async () => {
    const project = useProjectStore();
    const write = deferred<never>();
    vi.mocked(api.put).mockReturnValueOnce(write.promise);
    vi.mocked(api.get).mockResolvedValueOnce({ data: { id: 1, name: "Original" } });
    const updating = project.updateProject(1, { name: "Rejected" });
    await project.fetchProject(1);
    write.reject(new Error("Name refused"));
    await updating;
    expect(project.error).toBe("Name refused");
  });

  it("retains a valid workspace when the requested project cannot be opened", async () => {
    const project = useProjectStore();
    const workflow = useWorkflowStore();
    project.currentProject = { id: 1, name: "Still here" } as never;
    workflow.workflowId = 9;
    const held = deferred<never>();
    vi.mocked(api.get).mockReturnValueOnce(held.promise);
    const pending = project.selectProject(404);
    expect(project.currentProjectId).toBe(1);
    expect(workflow.workflowId).toBe(9);
    held.reject(new Error("Not found"));
    await pending;
    expect(project.currentProjectId).toBe(1);
    expect(project.currentProject?.name).toBe("Still here");
    expect(workflow.workflowId).toBe(9);
    expect(project.error).toBe("Not found");
    expect(project.isLoading).toBe(false);
  });

  it("commits only the latest successful project selection", async () => {
    const project = useProjectStore();
    const workflow = useWorkflowStore();
    workflow.workflowId = 9;
    const first = deferred<{ data: unknown }>();
    const second = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const selecting = [project.selectProject(2), project.selectProject(3)];
    second.resolve({ data: { id: 3, name: "Third" } });
    await selecting[1];
    first.resolve({ data: { id: 2, name: "Second" } });
    await selecting[0];
    expect(project.currentProjectId).toBe(3);
    expect(project.currentProject?.name).toBe("Third");
    expect(workflow.workflowId).toBeNull();
  });

  it.each(["create", "import", "delete", "archive"] as const)(
    "keeps newer navigation after an earlier %s acknowledgement",
    async (operation) => {
      const project = useProjectStore();
      project.currentProject = { id: 1, name: "First" } as never;
      const write = deferred<{ data: unknown }>();
      const destination = deferred<{ data: unknown }>();
      vi.mocked(api.post).mockReturnValueOnce(write.promise);
      vi.mocked(api.delete).mockReturnValueOnce(write.promise);
      vi.mocked(api.get).mockImplementation(async url => {
        if (url === "/projects/2") return destination.promise;
        if (url === "/projects") return { data: [{ id: 2, name: "Second" }, { id: 3, name: "Created" }] };
        throw new Error(`Unexpected selection: ${url}`);
      });
      const mutation = operation === "create" ? project.createProject({ name: "Created" })
        : operation === "import" ? project.importProject(new File(["archive"], "project.sherpa"))
          : operation === "delete" ? project.deleteProject(1, "First")
            : project.archiveProject(1);
      const selecting = project.selectProject(2);
      const signal = vi.mocked(api.get).mock.calls[0][1]?.signal;
      write.resolve({ data: { id: 3, name: "Created" } });
      await mutation;
      expect(signal?.aborted).toBe(false);
      expect(project.currentProjectId).toBe(operation === "delete" || operation === "archive" ? null : 1);
      destination.resolve({ data: { id: 2, name: "Second" } });
      await selecting;
      expect(project.currentProjectId).toBe(2);
      expect(project.currentProject?.name).toBe("Second");
      expect(project.error).toBeNull();
      expect(project.isImporting).toBe(false);
    },
  );

  it("does not restore a deleted workspace when newer navigation fails", async () => {
    const project = useProjectStore();
    project.currentProject = { id: 1, name: "First" } as never;
    const deletion = deferred<{ data: unknown }>();
    const destination = deferred<{ data: unknown }>();
    vi.mocked(api.delete).mockReturnValueOnce(deletion.promise);
    vi.mocked(api.get).mockImplementation(async url =>
      url === "/projects/2" ? destination.promise : { data: [] });
    const deleting = project.deleteProject(1, "First");
    const selecting = project.selectProject(2);
    deletion.resolve({ data: {} });
    await deleting;
    destination.reject(new Error("Destination unavailable"));
    await selecting;
    expect(project.currentProjectId).toBeNull();
    expect(project.currentProject).toBeNull();
    expect(project.error).toBe("Destination unavailable");
  });

  it.each([
    ["delete", 1], ["archive", 1], ["delete", 2], ["archive", 2],
  ] as const)("does not reopen project %s/%s from a read preceding its removal", async (operation, removedId) => {
    const project = useProjectStore();
    project.currentProject = { id: 1, name: "First" } as never;
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockImplementation(async url =>
      url === `/projects/${removedId}` ? held.promise : { data: [] });
    vi.mocked(api.delete).mockResolvedValue({ data: {} });
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    const selecting = project.selectProject(removedId);
    const signal = vi.mocked(api.get).mock.calls[0][1]?.signal;
    if (operation === "delete") await project.deleteProject(removedId, "Removed");
    else await project.archiveProject(removedId);
    expect(signal?.aborted).toBe(true);
    held.resolve({ data: { id: removedId, name: "Removed" } });
    await selecting;
    expect(project.currentProjectId).toBe(removedId === 1 ? null : 1);
    expect(project.currentProject?.name).not.toBe("Removed");
    expect(project.isLoading).toBe(false);
  });

  it("refreshes the project selector after rename then switch without restoring the old detail", async () => {
    const project = useProjectStore();
    const held = deferred<{ data: unknown }>();
    vi.mocked(api.put).mockReturnValueOnce(held.promise);
    vi.mocked(api.get).mockResolvedValue({ data: [{ id: 1, name: "Renamed" }, { id: 2, name: "Second" }] });
    const pending = project.updateProject(1, { name: "Renamed" });
    project.currentProjectId = 2;
    project.currentProject = { id: 2, name: "Second" } as never;
    held.resolve({ data: { id: 1, name: "Renamed" } });
    await pending;
    expect(project.projects[0].name).toBe("Renamed");
    expect(project.currentProject?.id).toBe(2);
  });

  it("refreshes inventories after upload then switch without selecting the uploaded dataset", async () => {
    const data = useDataStore();
    data.activeExperimentId = 44;
    const upload = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(upload.promise);
    vi.mocked(api.get).mockImplementation(async url => {
      if (url === "/experiments") return { data: [{ id: 45, name: "Current" }] };
      if (url === "/datasets/available") return { data: { experiments: [{ id: 44, name: "Uploaded" }], library: [], builder: [] } };
      if (url === "/projects") return { data: [{ id: 1, name: "Updated inventory" }] };
      throw new Error(`Unexpected selection: ${url}`);
    });
    const pending = data.uploadFile(44, new File(["1,2"], "sample.csv"), "raw");
    data.activeExperimentId = 45;
    upload.resolve({ data: { id: 11, file_path: "sample.csv", experiment_id: 44 } });
    await pending;
    expect(data.activeExperimentId).toBe(45);
    expect(data.availableDatasets?.experiments[0].name).toBe("Uploaded");
    expect(useProjectStore().projects[0].name).toBe("Updated inventory");
    expect(api.get).not.toHaveBeenCalledWith("/experiments/44/files", expect.anything());
  });

  it("does not refresh another actor's inventories for an old accepted write", async () => {
    const data = useDataStore();
    const upload = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(upload.promise);
    const pending = data.uploadFile(44, new File(["1,2"], "sample.csv"), "raw");
    useAuthStore().token = "new-session";
    upload.resolve({ data: { id: 11, file_path: "sample.csv", experiment_id: 44 } });
    await pending;
    expect(api.get).not.toHaveBeenCalled();
  });

  it.each(["create", "rename", "upload", "delete"] as const)(
    "refreshes experiment inventories after %s then project/selection switch",
    async (operation) => {
      const experiments = useExperimentStore();
      const held = deferred<{ data: unknown }>();
      vi.mocked(api.post).mockReturnValue(held.promise);
      vi.mocked(api.put).mockReturnValue(held.promise);
      vi.mocked(api.delete).mockReturnValue(held.promise);
      vi.mocked(api.get).mockImplementation(async url => {
        if (url === "/experiments") return { data: [{ id: 45, name: "Current inventory" }] };
        if (url === "/datasets/available") return { data: { experiments: [], library: [], builder: [] } };
        if (url === "/projects") return { data: [{ id: 2, name: "Current project" }] };
        if (url === "/experiments/45") return { data: { id: 45, name: "Selected" } };
        if (url === "/experiments/45/files" || url === "/experiments/45/versions") return { data: [] };
        throw new Error(`Unexpected old selection restored: ${url}`);
      });
      const pending = operation === "create"
        ? experiments.createExperiment({ name: "Created", metadata: {} })
        : operation === "rename"
          ? experiments.updateExperiment(44, { name: "Renamed" })
          : operation === "upload"
            ? experiments.uploadFile(44, new File(["1,2"], "file.csv"), "raw")
            : experiments.deleteExperiment(44);
      useProjectStore().currentProjectId = 2;
      await experiments.selectExperiment(45);
      held.resolve({ data: { id: 44, name: "Acknowledged write" } });
      await pending;
      expect(experiments.currentExperimentId).toBe(45);
      expect(experiments.currentExperiment?.name).toBe("Selected");
      expect(experiments.experiments[0].name).toBe("Current inventory");
      expect(useProjectStore().projects[0].id).toBe(2);
      expect(api.get).not.toHaveBeenCalledWith("/experiments/44/files", expect.anything());
    },
  );

  it("keeps account-wide project inventories while a project is selected", async () => {
    const project = useProjectStore();
    const active = deferred<{ data: unknown[] }>();
    const archived = deferred<{ data: unknown[] }>();
    vi.mocked(api.get).mockReturnValueOnce(active.promise).mockReturnValueOnce(archived.promise);
    const pending = Promise.all([project.fetchProjects(), project.fetchArchivedProjects()]);
    project.currentProjectId = 2;
    expect(vi.mocked(api.get).mock.calls.every(([, config]) => !config?.signal?.aborted)).toBe(true);
    active.resolve({ data: [{ id: 1, name: "First" }, { id: 2, name: "Second" }] });
    archived.resolve({ data: [{ id: 3, name: "Archived" }] });
    await pending;
    expect(project.projects.map(item => item.id)).toEqual([1, 2]);
    expect(project.archivedProjects.map(item => item.id)).toEqual([3]);
  });

  it("does not let a completed account inventory clear the newer project detail loading state", async () => {
    const project = useProjectStore();
    const list = deferred<{ data: unknown[] }>();
    const detail = deferred<{ data: { id: number; name: string } }>();
    vi.mocked(api.get).mockReturnValueOnce(list.promise).mockReturnValueOnce(detail.promise);
    const listing = project.fetchProjects();
    const loading = project.fetchProject(2);
    list.resolve({ data: [{ id: 2, name: "Second" }] });
    await listing;
    expect(project.isLoading).toBe(true);
    detail.resolve({ data: { id: 2, name: "Second" } });
    await loading;
    expect(project.isLoading).toBe(false);
  });

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

  it("keeps account-wide starter catalogs across a project switch, including late replies", async () => {
    const workflow = useWorkflowStore();
    const templates = deferred<{ data: unknown }>();
    const matrix = deferred<{ data: unknown }>();
    vi.mocked(api.get).mockReturnValueOnce(templates.promise).mockReturnValueOnce(matrix.promise);
    const pendingTemplates = workflow.fetchTemplates(undefined, true);
    const pendingMatrix = workflow.fetchCompatibilityMatrix();
    useProjectStore().currentProjectId = 2;
    templates.resolve({ data: { templates: [{ id: 1, slug: "pca" }] } });
    matrix.resolve({ data: { datasets: [{ dataset_id: "sklearn:iris" }], matrix: [] } });
    await Promise.all([pendingTemplates, pendingMatrix]);
    expect(workflow.templates.map(item => item.slug)).toEqual(["pca"]);
    expect(workflow.templatesLoading).toBe(false);
    expect(workflow.compatibilityMatrix?.datasets[0].dataset_id).toBe("sklearn:iris");

    useProjectStore().currentProjectId = 3;
    expect(workflow.templates).toHaveLength(1);
    expect(workflow.compatibilityMatrix).not.toBeNull();

    useAuthStore().token = "session-two";
    expect(workflow.templates).toEqual([]);
    expect(workflow.compatibilityMatrix).toBeNull();
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

  it.each([true, false])("refreshes inventories without reselecting after accepted upload (detail refresh=%s)", async (refresh) => {
    const data = useDataStore();
    data.activeExperimentId = 44;
    const late = deferred<{ data: unknown }>();
    vi.mocked(api.post).mockReturnValueOnce(late.promise);
    vi.mocked(api.get).mockImplementation(async url => ({
      data: url === "/datasets/available" ? { experiments: [], library: [], builder: [] } : [],
    }));
    const pending = data.uploadFile(44, new File(["x"], "x.csv"), "raw", { refresh });
    useProjectStore().currentProjectId = 2;
    late.resolve({ data: { id: 9, file_path: "raw/x.csv", stage: "raw", created_at: "" } });
    expect((await pending).id).toBe(9); // Accepted write is not reported as rolled back.
    expect(data.activeExperimentId).toBeNull();
    expect(vi.mocked(api.get).mock.calls.map(([url]) => url)).toEqual([
      "/experiments", "/datasets/available", "/projects",
    ]);
    expect(vi.mocked(api.get).mock.calls[0][1]?.params).toEqual({ project_id: 2 });
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

  it("keeps an admitted execution alive when its sheet is left, without painting another sheet", async () => {
    const workflow = useWorkflowStore();
    const workbook = useWorkbookStore();
    workbook.sheets = [{ workflowId: 1, kind: "analysis", executionStatus: "idle" }] as never;
    workflow.workflowId = 1;
    const run = deferred<{ data: unknown }>();
    let executionSignal: AbortSignal | undefined;
    vi.mocked(api.post).mockImplementation(async (url, _payload, config) => {
      if (url.endsWith("/preflight")) return { data: { is_valid: true, issues: [], semantic_edges: [] } };
      executionSignal = config?.signal as AbortSignal | undefined;
      executionSignal?.addEventListener("abort", () => run.reject({ name: "CanceledError", code: "ERR_CANCELED" }));
      return run.promise;
    });
    const pending = workflow.executeWorkflow().catch(error => error);
    await vi.waitFor(() => expect(workbook.sheets[0].executionStatus).toBe("running"));
    workflow.clearWorkflow();
    workflow.workflowId = 2;
    await flushPromises();
    expect(executionSignal?.aborted).toBe(false);
    expect(workbook.sheets[0].executionStatus).toBe("running");
    workflow.workflowId = 1;
    expect(workflow.isExecuting).toBe(true);
    await expect(workflow.executeWorkflow()).rejects.toThrow("already in progress");
    workflow.workflowId = 2;
    run.resolve({ data: { status: "completed", run_id: 44, results: { old: "retained" } } });
    expect((await pending).name).toBe("AbortError");
    expect(workbook.sheets[0].executionStatus).toBe("success");
    expect(workflow.lastExecutionResults).toBeNull();
    expect(workflow.restoredRunId).toBeNull();
    expect(workflow.isExecuting).toBe(false);
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
