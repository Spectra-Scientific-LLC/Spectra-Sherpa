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
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
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
});
