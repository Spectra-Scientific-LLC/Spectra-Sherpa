import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

import api from "@/api/client";
import { useProjectStore } from "@/stores/project";
import type { ProjectDetail } from "@/types";

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

const mockProject = {
  id: 1,
  name: "Test Project",
  description: "desc",
  technique: "FTIR",
  sample_type: null,
  updated_at: new Date().toISOString(),
  experiment_count: 2,
  workflow_count: 1,
  script_count: 0,
  model_count: 0,
  children_count: 0,
};

describe("Project Store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("initializes with empty state", () => {
    const store = useProjectStore();
    expect(store.projects).toEqual([]);
    expect(store.currentProject).toBeNull();
    expect(store.currentProjectId).toBeNull();
    expect(store.isLoading).toBe(false);
    expect(store.error).toBeNull();
  });

  describe("fetchProjects", () => {
    it("fetches and stores projects", async () => {
      vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject] });
      const store = useProjectStore();

      await store.fetchProjects();

      expect(api.get).toHaveBeenCalledWith("/projects");
      expect(store.projects).toEqual([mockProject]);
      expect(store.isLoading).toBe(false);
    });

    it("sets error on failure", async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("Network error"));
      const store = useProjectStore();

      await store.fetchProjects();

      expect(store.error).toBe("Network error");
      expect(store.isLoading).toBe(false);
    });
  });

  describe("fetchProject", () => {
    it("fetches a single project and sets current", async () => {
      const detail = { ...mockProject, experiments: [], workflows: [] };
      vi.mocked(api.get).mockResolvedValueOnce({ data: detail });
      const store = useProjectStore();

      const result = await store.fetchProject(1);

      expect(api.get).toHaveBeenCalledWith("/projects/1");
      expect(store.currentProject).toEqual(detail);
      expect(store.currentProjectId).toBe(1);
      expect(result).toEqual(detail);
    });

    it("returns null on failure", async () => {
      vi.mocked(api.get).mockRejectedValueOnce(new Error("Not found"));
      const store = useProjectStore();

      const result = await store.fetchProject(999);

      expect(result).toBeNull();
      expect(store.error).toBe("Not found");
    });
  });

  describe("createProject", () => {
    it("creates and refreshes list", async () => {
      const created = { ...mockProject, id: 2, name: "New" };
      vi.mocked(api.post).mockResolvedValueOnce({ data: created });
      vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject, created] });
      const store = useProjectStore();

      const result = await store.createProject({ name: "New" });

      expect(api.post).toHaveBeenCalledWith("/projects", { name: "New" });
      expect(result).toEqual(created);
      expect(store.currentProjectId).toBe(2);
    });
  });

  describe("deleteProject", () => {
    it("deletes and clears current if matching", async () => {
      vi.mocked(api.delete).mockResolvedValueOnce({});
      vi.mocked(api.get).mockResolvedValueOnce({ data: [] });
      const store = useProjectStore();
      store.currentProjectId = 1;
      store.currentProject = {
        ...mockProject,
        metadata: {},
        experiments: [],
        workflows: [],
        scripts: [],
        models: [],
        children: [],
      } satisfies ProjectDetail;

      const success = await store.deleteProject(1);

      expect(success).toBe(true);
      expect(store.currentProjectId).toBeNull();
      expect(store.currentProject).toBeNull();
    });

    it("does not clear current if different project deleted", async () => {
      vi.mocked(api.delete).mockResolvedValueOnce({});
      vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject] });
      const store = useProjectStore();
      store.currentProjectId = 1;

      await store.deleteProject(99);

      expect(store.currentProjectId).toBe(1);
    });

    it("returns false on failure", async () => {
      vi.mocked(api.delete).mockRejectedValueOnce(new Error("Forbidden"));
      const store = useProjectStore();

      const success = await store.deleteProject(1);

      expect(success).toBe(false);
      expect(store.error).toBe("Forbidden");
    });
  });

  describe("removeWorkflowFromCurrentProject", () => {
    it("removes the workflow from current project details and decrements project summary count", () => {
      const store = useProjectStore();
      store.projects = [{ ...mockProject, workflow_count: 2 }];
      store.currentProjectId = 1;
      store.currentProject = {
        ...mockProject,
        workflow_count: 2,
        metadata: {},
        experiments: [],
        workflows: [
          { id: 10, name: "Keep", description: null, status: "draft", integrity_hash: null },
          { id: 20, name: "Delete", description: null, status: "draft", integrity_hash: null },
        ],
        scripts: [],
        models: [],
        children: [],
      } satisfies ProjectDetail;

      store.removeWorkflowFromCurrentProject(20);

      expect(store.currentProject?.workflows.map((workflow) => workflow.id)).toEqual([10]);
      expect(store.currentProject?.workflow_count).toBe(1);
      expect(store.projects[0].workflow_count).toBe(1);
    });
  });

  describe("getLastActiveProjectId / fetchProject localStorage", () => {
    it("returns null when nothing is stored", () => {
      const store = useProjectStore();
      expect(store.getLastActiveProjectId()).toBeNull();
    });

    it("fetchProject writes the project id to localStorage keyed by userId", async () => {
      const detail = { ...mockProject, experiments: [], workflows: [] };
      vi.mocked(api.get).mockResolvedValueOnce({ data: detail });
      const store = useProjectStore();

      await store.fetchProject(1);

      // Key format: spectra_sherpa_last_project_<userId>
      expect(localStorage.getItem("spectra_sherpa_last_project_7")).toBe("1");
    });

    it("getLastActiveProjectId reads back what fetchProject stored", async () => {
      const detail = { ...mockProject, experiments: [], workflows: [] };
      vi.mocked(api.get).mockResolvedValueOnce({ data: detail });
      const store = useProjectStore();

      await store.fetchProject(1);
      const remembered = store.getLastActiveProjectId();

      expect(remembered).toBe(1);
    });

    it("ignores stale entries written by a different user", () => {
      // Simulate a value written under a different user key
      localStorage.setItem("spectra_sherpa_last_project_99", "42");
      const store = useProjectStore();

      // Auth mock returns userId=7, so key spectra_sherpa_last_project_7 is absent
      expect(store.getLastActiveProjectId()).toBeNull();
    });
  });

  describe("computed properties", () => {
    it("projectList maps with formatted date", async () => {
      vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject] });
      const store = useProjectStore();
      await store.fetchProjects();

      expect(store.projectList.length).toBe(1);
      expect(store.projectList[0].name).toBe("Test Project");
      expect(store.projectList[0].modified).toBe("Today");
    });

    it("recentProjects sorts by updated_at descending", async () => {
      const older = { ...mockProject, id: 2, name: "Old", updated_at: "2020-01-01T00:00:00Z" };
      vi.mocked(api.get).mockResolvedValueOnce({ data: [older, mockProject] });
      const store = useProjectStore();
      await store.fetchProjects();

      expect(store.recentProjects[0].name).toBe("Test Project");
      expect(store.recentProjects[1].name).toBe("Old");
    });
  });
});
