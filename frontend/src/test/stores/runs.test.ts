import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import api from "@/api/client";
import { useRunsStore } from "@/stores/runs";

vi.mock("@/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe("run navigation request ownership", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("requests a bounded server-filtered page and clears hidden selections", async () => {
    const store = useRunsStore();
    store.selectedRunIds = new Set([1]);
    vi.mocked(api.get).mockResolvedValue({ data: { runs: [{ id: 2 }], total: 90 } });
    await store.fetchProjectRuns(3, 50, "data");
    expect(api.get).toHaveBeenCalledWith("/runs", {
      params: {
        project_id: 3,
        limit: 50,
        offset: 50,
        kind: "data",
        artifact_uid: undefined,
        sort_by: "executed_at",
        sort_order: "desc",
      },
    });
    expect(store.total).toBe(90);
    expect(store.selectedCount).toBe(0);
  });

  it("passes a reviewed server sort through the bounded page request", async () => {
    const store = useRunsStore();
    vi.mocked(api.get).mockResolvedValue({ data: { runs: [], total: 0 } });
    await store.fetchProjectRuns(3, 0, "all", undefined, "name", "asc");
    expect(api.get).toHaveBeenCalledWith("/runs", {
      params: {
        project_id: 3,
        limit: 50,
        offset: 0,
        kind: undefined,
        artifact_uid: undefined,
        sort_by: "name",
        sort_order: "asc",
      },
    });
  });

  it("ignores an old project's response arriving after the new project", async () => {
    let resolveOld!: (value: unknown) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }));
    const store = useRunsStore();
    const old = store.fetchProjectRuns(1);
    store.resetProjectScope();
    vi.mocked(api.get).mockResolvedValueOnce({ data: { runs: [{ id: 22 }], total: 1 } });
    await store.fetchProjectRuns(2);
    resolveOld({ data: { runs: [{ id: 11 }], total: 200 } });
    await old;
    expect(store.runs.map(run => run.id)).toEqual([22]);
    expect(store.total).toBe(1);
  });

  it("cannot resurrect a comparison after its selection scope is cleared", async () => {
    let resolve!: (value: unknown) => void;
    vi.mocked(api.post).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const store = useRunsStore();
    const pending = store.compareProjectRuns(1, [2, 3]);
    store.clearSelection();
    resolve({ data: { runs: [{ id: 2 }, { id: 3 }], diff: {}, metric_keys: [] } });
    await pending;
    expect(store.comparison).toBeNull();
    expect(store.comparisonLoading).toBe(false);
  });

  it("removes the previous ranking while checking a new evaluation pairing, including on failure", async () => {
    const store = useRunsStore();
    vi.mocked(api.post).mockResolvedValueOnce({ data: { runs: [], diff: {}, metric_keys: ["rmse"] } });
    await store.compareProjectRuns(1, [2, 3]);
    expect(store.comparison).not.toBeNull();
    let reject!: (reason: Error) => void;
    vi.mocked(api.post).mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }));
    const selections = { 2: { node_id: "cv", presentation_id: "oof_evidence" } };
    const pending = store.compareProjectRuns(1, [2, 3], selections);
    expect(store.comparison).toBeNull();
    expect(store.comparisonLoading).toBe(true);
    expect(api.post).toHaveBeenLastCalledWith("/runs/compare", {
      run_ids: [2, 3], evaluation_selections: selections,
    }, { params: { project_id: 1 } });
    reject(new Error("Pairing is unavailable"));
    await expect(pending).rejects.toThrow("Pairing is unavailable");
    expect(store.comparison).toBeNull();
    expect(store.comparisonLoading).toBe(false);
  });
  it("names the displayed run explicitly and refuses a missing identity", async () => {
    const store = useRunsStore();
    const payload = {name:"Reviewed run",status:"completed",results_summary:{},executed_at:"2026-09-21T00:00:00Z"};
    await expect(store.saveRun(4,payload)).rejects.toThrow("identity");
    expect(api.post).not.toHaveBeenCalled();
    vi.mocked(api.post).mockResolvedValue({data:{id:10,name:payload.name}});
    await store.saveRun(4,{...payload,run_id:10});
    expect(api.post).toHaveBeenCalledWith("/workflows/4/runs",{...payload,run_id:10});
    expect(store.runs[0].id).toBe(10);
  });

});

describe("retained output storage recovery", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); });
  it("uses owner-scoped reclamation and returns the server quota and grace", async () => {
    const report = { removed_files: 2, used_bytes: 120, quota_bytes: 512, grace_seconds: 86400 };
    vi.mocked(api.post).mockResolvedValue({ data: report });
    expect(await useRunsStore().reclaimStorage()).toEqual(report);
    expect(api.post).toHaveBeenCalledWith("/runs/storage/reclaim");
  });
  it("propagates refusal instead of claiming space was reclaimed", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("invalid evidence inventory"));
    await expect(useRunsStore().reclaimStorage()).rejects.toThrow("invalid evidence inventory");
  });
});
