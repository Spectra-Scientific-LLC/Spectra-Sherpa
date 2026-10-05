import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { useDataStore } from "@/stores/data";
import { useProjectStore } from "@/stores/project";
import type { ExperimentSummary } from "@/types";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

function setScope(userId: number, projectId: number) {
  const authStore = useAuthStore();
  authStore.user = { id: userId, username: `user-${userId}` };
  const projectStore = useProjectStore();
  projectStore.currentProjectId = projectId;
}

describe("data store state retention", () => {
  it.each(["raw", "synthetic", "preprocessed"] as const)("retains the sole imported %s source for all-files inspection", async (stage) => {
    setActivePinia(createPinia());
    const store = useDataStore();
    store.activeExperimentId = 44;
    store.experimentFiles = [{ id: 103, file_path: `${stage}/example.npz`, stage, created_at: "" }];
    vi.mocked(api.post).mockResolvedValueOnce({ data: { n_samples: 569, n_features: 30, metadata: { contents_stage: stage } } });
    await store.inspectExperimentRawFiles(44);
    expect(store.activeFileId).toBe(103);
    expect(store.activeFilePath).toBe(`${stage}/example.npz`);
  });

  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("captures Advisor state lazily, freezes it on exit, and isolates account/project scopes", () => {
    setScope(7, 12);
    const store = useDataStore();
    let mask = [true, false];
    const provider = vi.fn(() => ({ row_mask: mask }));
    const release = store.registerAdvisorDatasetContext(provider);
    expect(provider).not.toHaveBeenCalled();
    const first = store.captureAdvisorDatasetContext();
    mask = [false, true];
    expect(store.captureAdvisorDatasetContext()).toEqual({ row_mask: [false, true] });
    expect(first).toEqual({ row_mask: [true, false] });
    release();
    mask = [true, true];
    expect(store.captureAdvisorDatasetContext()).toEqual({ row_mask: [false, true] });
    setScope(7, 13);
    expect(store.captureAdvisorDatasetContext()).toBeNull();
    setScope(8, 12);
    expect(store.captureAdvisorDatasetContext()).toBeNull();
  });

  it("remembers the selected dataset by user and project", async () => {
    setScope(7, 12);
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });
    const store = useDataStore();

    await store.selectExperiment(44);

    expect(localStorage.getItem("spectra_sherpa_last_experiment_7_12")).toBe("44");
    expect(api.get).toHaveBeenCalledWith("/experiments/44/files");
  });

  it("restores the selected dataset after a browser refresh", async () => {
    setScope(7, 12);
    localStorage.setItem("spectra_sherpa_last_experiment_7_12", "44");
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [
        {
          id: 1,
          file_path: "raw/example.csv",
          stage: "raw",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    const store = useDataStore();
    store.experiments = [
      {
        id: 44,
        name: "Retained Dataset",
        created_at: "2026-01-01T00:00:00Z",
        file_count: 1,
      } satisfies ExperimentSummary,
    ];

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBe(44);
    expect(store.experimentFiles).toHaveLength(1);
    expect(api.get).toHaveBeenCalledWith("/experiments/44/files");
  });

  it.each([null, "999"])("selects the sole server dataset with no valid browser memory (%s)", async (remembered) => {
    setScope(7, 12);
    if (remembered) localStorage.setItem("spectra_sherpa_last_experiment_7_12", remembered);
    const store = useDataStore();
    vi.mocked(api.get).mockResolvedValueOnce({ data: [
      { id: 44, name: "Corn", file_count: 3, created_at: "2026-01-01T00:00:00Z" },
    ] }).mockResolvedValueOnce({ data: [
      { id: 92, file_path: "raw/corn-m5.mat", stage: "raw" },
    ] });

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBe(44);
    expect(store.experimentFiles[0].id).toBe(92);
    expect(api.get).toHaveBeenCalledWith("/experiments/44/files");
    expect(localStorage.getItem("spectra_sherpa_last_experiment_7_12")).toBe("44");
  });

  it("does not infer a selection in a fresh project with multiple datasets", async () => {
    setScope(7, 12);
    // Neither another user's nor another project's remembered focus is authority.
    localStorage.setItem("spectra_sherpa_last_experiment_8_12", "44");
    localStorage.setItem("spectra_sherpa_last_experiment_7_13", "45");
    const store = useDataStore();
    vi.mocked(api.get).mockResolvedValueOnce({ data: [
      { id: 44, name: "Spectra", file_count: 1 },
      { id: 45, name: "Tabular", file_count: 1 },
    ] });

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBeNull();
    expect(store.experimentFiles).toEqual([]);
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it("does not infer focus from the previous project's retained list after a fetch failure", async () => {
    setScope(7, 12);
    const store = useDataStore();
    vi.mocked(api.get).mockResolvedValueOnce({ data: [
      { id: 44, name: "Previous project dataset", file_count: 1 },
    ] });
    await store.fetchExperiments();
    setScope(7, 13);
    store.clearActiveExperimentSelection();
    vi.mocked(api.get).mockRejectedValueOnce(new Error("Project list unavailable"));
    await store.fetchExperiments();
    vi.mocked(api.get).mockClear();

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
    expect(localStorage.getItem("spectra_sherpa_last_experiment_7_13")).toBeNull();
  });

  it("keeps an explicit remembered choice when several datasets exist", async () => {
    setScope(7, 12);
    localStorage.setItem("spectra_sherpa_last_experiment_7_12", "45");
    const store = useDataStore();
    store.experiments = [44, 45].map((id) => ({ id, name: `Dataset ${id}`, file_count: 1,
      created_at: "2026-01-01T00:00:00Z" }));
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBe(45);
    expect(api.get).toHaveBeenCalledWith("/experiments/45/files");
  });

  it("clears an active dataset that belongs to the previous project", async () => {
    setScope(7, 12);
    const store = useDataStore();
    store.activeExperimentId = 44;
    store.experimentFiles = [
      {
        id: 1,
        file_path: "raw/previous-project.spa",
        stage: "raw",
        created_at: "2026-01-01T00:00:00Z",
      },
    ];
    store.fileInfo = { dataset_id: "previous-project" } as never;
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });

    await store.restoreActiveExperimentForCurrentProject();

    expect(store.activeExperimentId).toBeNull();
    expect(store.experimentFiles).toEqual([]);
    expect(store.fileInfo).toBeNull();
    expect(localStorage.getItem("spectra_sherpa_last_experiment_7_12")).toBeNull();
  });

  it("surfaces a persisted scientific-asset inventory refusal", async () => {
    setScope(7, 12);
    vi.mocked(api.get).mockRejectedValueOnce({
      isAxiosError: true,
      response: { data: { detail: "OPUS derivative order 1 is not independently qualified" } },
    });
    const store = useDataStore();

    await expect(store.fetchFileAssets(44, 9)).rejects.toBeTruthy();

    expect(store.fileInfoError).toContain("OPUS derivative order 1");
    expect(store.fileInfo).toBeNull();
  });

  it("clears the preceding scientific inspection before changing datasets", async () => {
    setScope(7, 12);
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { dataset_id: "old", data: [[1, 2]], n_samples: 1, n_features: 2 },
    });
    vi.mocked(api.get).mockResolvedValueOnce({
      data: [{ id: 92, file_path: "raw/new.mat", stage: "raw" }],
    });
    const store = useDataStore();
    await store.inspectExperimentRawFiles(44);

    expect(store.fileInfo?.dataset_id).toBe("old");
    await store.selectExperiment(45);

    expect(store.activeExperimentId).toBe(45);
    expect(store.fileInfo).toBeNull();
    expect(store.activeFileId).toBeNull();
    expect(store.experimentFiles).toEqual([{ id: 92, file_path: "raw/new.mat", stage: "raw" }]);
  });

  it("inspects only the exact selected dataset views", async () => {
    setScope(7, 12);
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { dataset_id: "selected-views", n_samples: 12, n_features: 700 },
    } as never);
    const store = useDataStore();

    await store.inspectExperimentRawFiles(44, null, [101, 103]);

    expect(api.post).toHaveBeenCalledWith(
      "/builder/file-info",
      {
        experiment_id: 44,
        file_ids: [101, 103],
      },
      { signal: expect.any(AbortSignal) },
    );
    expect(store.fileInfo?.dataset_id).toBe("selected-views");
    expect(store.activeFileId).toBeNull();
  });

  it("keeps a one-file inspection addressable for matrix retrieval", async () => {
    setScope(7, 12);
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { dataset_id: "selected-file", n_samples: 12, n_features: 700 },
    } as never);
    const store = useDataStore();

    await store.inspectExperimentRawFiles(44, null, [103]);

    expect(store.activeFileId).toBe(103);
  });

  it("does not let a late file-list response overwrite a newer dataset selection", async () => {
    setScope(7, 12);
    let resolveFirst: (value: { data: unknown[] }) => void = () => undefined;
    const first = new Promise<{ data: unknown[] }>((resolve) => {
      resolveFirst = resolve;
    });
    vi.mocked(api.get)
      .mockReturnValueOnce(first as never)
      .mockResolvedValueOnce({
        data: [{ id: 202, file_path: "raw/current.mat", stage: "raw" }],
      });
    const store = useDataStore();

    const oldSelection = store.selectExperiment(44);
    await store.selectExperiment(45);
    resolveFirst({ data: [{ id: 101, file_path: "raw/stale.spa", stage: "raw" }] });
    await oldSelection;

    expect(store.activeExperimentId).toBe(45);
    expect(store.experimentFiles).toEqual([
      { id: 202, file_path: "raw/current.mat", stage: "raw" },
    ]);
  });

  it("selects the authoritative dataset returned by a repeated reference import", async () => {
    setScope(7, 12);
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        imported: 0,
        files: [],
        experiment_id: 19,
        reused_existing: true,
      },
    });
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    const store = useDataStore();

    const result = await store.importReferenceDatasets(44, [
      { source: "builtin", name: "lavender-essential-oil-v1" },
    ]);

    expect(result.experiment_id).toBe(19);
    expect(store.activeExperimentId).toBe(19);
    expect(api.get).toHaveBeenCalledWith("/experiments/19/files");
    expect(api.get).not.toHaveBeenCalledWith("/experiments/44/files");
  });

  it("stops the contents spinner immediately when a pending inspection is cleared", async () => {
    setScope(7, 12);
    let finish!: (value: unknown) => void;
    vi.mocked(api.post).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }) as never,
    );
    const store = useDataStore();
    const pending = store.inspectExperimentRawFiles(44);
    const signal = vi.mocked(api.post).mock.calls[0][2]?.signal;
    expect(store.fileInfoLoading).toBe(true);
    store.clearInspection();
    expect(signal?.aborted).toBe(true);
    expect(store.fileInfoLoading).toBe(false);
    finish({ data: { dataset_id: "obsolete" } });
    await pending;
    expect(store.fileInfo).toBeNull();
    expect(store.fileInfoLoading).toBe(false);
  });

  it("cancels superseded contents requests and keeps only the latest selection", async () => {
    setScope(7, 12);
    let finish!: (value: unknown) => void;
    vi.mocked(api.post)
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }) as never,
      )
      .mockResolvedValueOnce({ data: { dataset_id: "current" } });
    const store = useDataStore();
    const previous = store.inspectFile(101, "raw/first.spa", 44);
    const signal = vi.mocked(api.post).mock.calls[0][2]?.signal;
    await store.inspectExperimentRawFiles(44, null, [103]);
    expect(signal?.aborted).toBe(true);
    finish({ data: { dataset_id: "obsolete" } });
    await previous;
    expect(store.fileInfo?.dataset_id).toBe("current");
    expect(store.fileInfoLoading).toBe(false);
    expect(store.fileInfoError).toBeNull();
  });
  it.each([
    ["fetchExperiments", "experimentsError", []],
    ["fetchCatalog", "catalogError", { experiments: [], library: [], builder: [] }],
  ] as const)("%s exposes a recoverable read error and ignores obsolete failures", async (method, errorField, data) => {
    setScope(7, 12);
    const store = useDataStore();
    vi.mocked(api.get).mockRejectedValueOnce(new Error("offline"));
    await store[method]();
    expect(store[errorField]).toContain("could not be loaded");
    vi.mocked(api.get).mockResolvedValueOnce({ data });
    await store[method]();
    expect(store[errorField]).toBeNull();
    expect(api.post).not.toHaveBeenCalled();

    let rejectOld!: (error: Error) => void;
    vi.mocked(api.get).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
    const old = store[method]();
    setScope(7, 13);
    vi.mocked(api.get).mockResolvedValueOnce({ data });
    await store[method]();
    rejectOld(new Error("old project offline"));
    await old;
    expect(store[errorField]).toBeNull();
  });

});
