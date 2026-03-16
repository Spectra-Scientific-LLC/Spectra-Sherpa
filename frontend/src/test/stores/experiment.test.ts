import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useExperimentStore } from "@/stores/experiment";
import type { ExperimentDetail, ExperimentFile, ExperimentSummary, VersionInfo } from "@/types";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("Experiment Store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it("initializes with empty state", () => {
    const store = useExperimentStore();
    expect(store.experiments).toEqual([]);
    expect(store.currentExperiment).toBeNull();
    expect(store.currentExperimentId).toBeNull();
    expect(store.files).toEqual([]);
    expect(store.versions).toEqual([]);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it("fetches experiments successfully", async () => {
    const mockExperiments = [
      { id: 1, name: "Experiment 1", description: "Test 1" },
      { id: 2, name: "Experiment 2", description: "Test 2" },
    ];
    vi.mocked(api.get).mockResolvedValueOnce({ data: mockExperiments });

    const store = useExperimentStore();
    await store.fetchExperiments();

    expect(api.get).toHaveBeenCalledWith("/experiments");
    expect(store.experiments).toEqual(mockExperiments);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it("captures and rethrows fetchExperiments errors", async () => {
    const err = new Error("Network error");
    vi.mocked(api.get).mockRejectedValueOnce(err);

    const store = useExperimentStore();
    await expect(store.fetchExperiments()).rejects.toThrow("Network error");

    expect(store.experiments).toEqual([]);
    expect(store.loading).toBe(false);
    expect(store.error).toBe("Network error");
  });

  it("selectExperiment loads experiment, files, and versions", async () => {
    const mockExperiment = { id: 1, name: "Demo Experiment", description: "Demo" };
    const mockFiles = [{ id: 11, file_path: "a.csv" }];
    const mockVersions = [{ id: 21, version_name: "v1" }];

    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: mockExperiment })
      .mockResolvedValueOnce({ data: mockFiles })
      .mockResolvedValueOnce({ data: mockVersions });

    const store = useExperimentStore();
    await store.selectExperiment(1);

    expect(api.get).toHaveBeenNthCalledWith(1, "/experiments/1");
    expect(api.get).toHaveBeenNthCalledWith(2, "/experiments/1/files");
    expect(api.get).toHaveBeenNthCalledWith(3, "/experiments/1/versions");
    expect(store.currentExperiment).toEqual(mockExperiment);
    expect(store.currentExperimentId).toBe(1);
    expect(store.files).toEqual(mockFiles);
    expect(store.versions).toEqual(mockVersions);
  });

  it("creates an experiment and prepends it to the list", async () => {
    const payload = {
      name: "New Experiment",
      description: "Test description",
      metadata: {},
    };
    const created = { id: 1, ...payload };
    vi.mocked(api.post).mockResolvedValueOnce({ data: created });

    const store = useExperimentStore();
    const result = await store.createExperiment(payload);

    expect(api.post).toHaveBeenCalledWith("/experiments", payload);
    expect(result).toEqual(created);
    expect(store.experiments[0]).toEqual(created);
    expect(store.loading).toBe(false);
  });

  it("deleteExperiment clears selected experiment state", async () => {
    const store = useExperimentStore();
    store.experiments = [{
      id: 7,
      name: "Delete Me",
      description: "",
      created_at: "2026-01-01T00:00:00Z",
      file_count: 1,
    }] satisfies ExperimentSummary[];
    store.currentExperiment = {
      id: 7,
      name: "Delete Me",
      description: "",
      created_at: "2026-01-01T00:00:00Z",
      file_count: 1,
      metadata: {},
    } satisfies ExperimentDetail;
    store.files = [{
      id: 1,
      file_path: "x.csv",
      stage: "raw",
      created_at: "2026-01-01T00:00:00Z",
    }] satisfies ExperimentFile[];
    store.versions = [{
      id: 1,
      version_name: "v1",
      created_at: "2026-01-01T00:00:00Z",
      file_count: 1,
    }] satisfies VersionInfo[];

    vi.mocked(api.delete).mockResolvedValueOnce({ data: null });
    await store.deleteExperiment(7);

    expect(api.delete).toHaveBeenCalledWith("/experiments/7");
    expect(store.experiments).toEqual([]);
    expect(store.currentExperiment).toBeNull();
    expect(store.files).toEqual([]);
    expect(store.versions).toEqual([]);
  });

  it("uploadFile posts multipart and refreshes files", async () => {
    const store = useExperimentStore();
    const file = new File(["a,b\n1,2"], "sample.csv", { type: "text/csv" });
    const refreshed = [{ id: 100, file_path: "sample.csv" }];

    vi.mocked(api.post).mockResolvedValueOnce({ data: null });
    vi.mocked(api.get).mockResolvedValueOnce({ data: refreshed });

    await store.uploadFile(42, file, "raw");

    expect(api.post).toHaveBeenNthCalledWith(
      1,
      "/experiments/42/files",
      expect.any(FormData),
      { headers: { "Content-Type": "multipart/form-data" } },
    );
    expect(api.get).toHaveBeenCalledWith("/experiments/42/files");
    expect(store.files).toEqual(refreshed);
  });
});
