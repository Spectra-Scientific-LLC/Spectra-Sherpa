import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import { useRunsStore } from "@/stores/runs";
import { useDataSourceStore } from "@/stores/dataSources";
import { useExperimentStore } from "@/stores/experiment";
import { useDeployStore } from "@/stores/deploy";
import {
  registerProjectScopeReset,
  runProjectScopeResets,
  _clearProjectScopeRegistryForTests,
} from "@/stores/projectScopeRegistry";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({ user: { id: 7 } }),
}));

const mockProject = (id: number) => ({
  id,
  name: `Project ${id}`,
  description: "",
  technique: "FTIR",
  sample_type: null,
  updated_at: new Date().toISOString(),
  experiment_count: 0,
  workflow_count: 0,
  script_count: 0,
  model_count: 0,
  children_count: 0,
});

describe("projectScopeRegistry", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
    _clearProjectScopeRegistryForTests();
  });

  it("runs every registered callback exactly once", () => {
    const a = vi.fn();
    const b = vi.fn();
    registerProjectScopeReset(a);
    registerProjectScopeReset(b);

    runProjectScopeResets();

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("isolates failures — one throwing callback does not abort the rest", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const a = vi.fn(() => {
      throw new Error("boom");
    });
    const b = vi.fn();
    registerProjectScopeReset(a);
    registerProjectScopeReset(b);

    runProjectScopeResets();

    expect(a).toHaveBeenCalled();
    expect(b).toHaveBeenCalled();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("unregister callback returned by registerProjectScopeReset removes it", () => {
    const a = vi.fn();
    const unregister = registerProjectScopeReset(a);
    unregister();
    runProjectScopeResets();
    expect(a).not.toHaveBeenCalled();
  });
});

describe("project store coordinates project-scoped resets", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
    _clearProjectScopeRegistryForTests();
  });

  it("selectProject(newId) clears every project-scoped store before loading the new project", async () => {
    // Instantiate the stores so their reset callbacks self-register
    const runs = useRunsStore();
    const dataSources = useDataSourceStore();
    const experiments = useExperimentStore();
    const deploy = useDeployStore();
    const project = useProjectStore();

    // Seed each store with stale state belonging to "project A"
    runs.runs = [{ id: 1, name: "stale-run" } as never];
    runs.selectedRunIds = new Set([1]);
    dataSources.dataSources = [{ id: 11, display_name: "stale-ds" } as never];
    dataSources.projectId = 1;
    experiments.experiments = [{ id: 21, name: "stale-exp" } as never];
    experiments.currentExperiment = { id: 21, name: "stale-exp" } as never;
    deploy.watches = [{ id: 31, name: "stale-watch" } as never];

    project.currentProjectId = 1;
    vi.mocked(api.get).mockResolvedValueOnce({ data: mockProject(2) });

    await project.selectProject(2);

    expect(runs.runs).toEqual([]);
    expect(runs.selectedRunIds.size).toBe(0);
    expect(dataSources.dataSources).toEqual([]);
    expect(dataSources.projectId).toBeNull();
    expect(experiments.experiments).toEqual([]);
    expect(experiments.currentExperiment).toBeNull();
    expect(deploy.watches).toEqual([]);
    expect(project.currentProjectId).toBe(2);
  });

  it("selectProject(sameId) does NOT reset — that would wipe legitimately-loaded state", async () => {
    const runs = useRunsStore();
    const project = useProjectStore();

    project.currentProjectId = 5;
    runs.runs = [{ id: 99, name: "legit-run" } as never];
    vi.mocked(api.get).mockResolvedValueOnce({ data: mockProject(5) });

    await project.selectProject(5);

    expect(runs.runs).toHaveLength(1);
  });

  it("deleteProject(activeId) clears project-scoped stores; deleteProject(otherId) does not", async () => {
    const runs = useRunsStore();
    const project = useProjectStore();

    runs.runs = [{ id: 1, name: "stale" } as never];
    project.currentProjectId = 9;
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] }); // fetchProjects after delete

    await project.deleteProject(9);
    expect(runs.runs).toEqual([]);

    // Now seed again and delete a non-active project
    runs.runs = [{ id: 2, name: "still-here" } as never];
    project.currentProjectId = 10;
    vi.mocked(api.delete).mockResolvedValueOnce({ data: null });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });

    await project.deleteProject(11);
    expect(runs.runs).toHaveLength(1);
  });
});
