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

vi.mock("@/utils/download", () => ({
  downloadBlob: vi.fn(),
  filenameFromContentDisposition: vi.fn(() => "project.sherpa"),
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

  it.each(["Experiment", "Workflow"] as const)("passes an explicit destination when unlinking %s", async (kind) => {
    vi.mocked(api.delete).mockResolvedValueOnce({ data: { ...mockProject, experiments: [], workflows: [] } });
    vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject] });
    const store = useProjectStore();
    await store[`unlink${kind}`](1, 7, 2);
    expect(api.delete).toHaveBeenCalledWith(`/projects/1/${kind.toLowerCase()}s/7`, {
      params: { destination_project_id: 2 },
    });
  });

  it("initializes with empty state", () => {
    const store = useProjectStore();
    expect(store.projects).toEqual([]);
    expect(store.currentProject).toBeNull();
    expect(store.currentProjectId).toBeNull();
    expect(store.isLoading).toBe(false);
    expect(store.error).toBeNull();
  });

  it("reports omitted unportable models from a partial project archive", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({
      data: new Blob(["archive"]),
      headers: { "x-spectra-project-model-omissions": "2" },
    });
    const store = useProjectStore();
    await store.exportProject(1);
    expect(store.error).toBeNull();
    expect(store.lastExportOmittedModels).toBe(2);
  });

  it.each(["campaign-review.sherpa", "managed-result.sherpa", "arbitrarily-renamed.sherpa"])(
    "uses the content-authoritative backend importer for %s",
    async (filename) => {
    const imported = {
      ...mockProject,
      id: 42,
      name: "Managed canonical result",
      metadata: {},
      experiments: [],
      data_sources: [],
      workflows: [],
      advisor_channels: [],
      scripts: [],
      models: [],
      children: [],
      application: {
        handle: "application:plan-abc",
        origin: "campaign_solution",
        project_id: 42,
        workflow_id: 19,
        application_plan_digest: "plan-abc",
        status: "awaiting_local_data_binding",
      },
    } satisfies ProjectDetail;
    vi.mocked(api.post).mockResolvedValueOnce({ data: imported });
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: [imported] })
      .mockResolvedValueOnce({ data: imported });
    const store = useProjectStore();

    const result = await store.importProject(new File(["project"], filename));

    expect(api.post).toHaveBeenCalledWith("/projects/import", expect.any(FormData), {
      headers: { "Content-Type": "multipart/form-data" },
    });
    expect(result?.id).toBe(42);
    expect(store.currentProjectId).toBe(42);
    expect(store.lastImportedApplication?.handle).toBe("application:plan-abc");
    },
  );

  it("preserves ordinary project import while attaching explicitly selected reference files", async () => {
    const imported = {
      ...mockProject,
      id: 43,
      metadata: {},
      experiments: [],
      data_sources: [],
      workflows: [],
      advisor_channels: [],
      scripts: [],
      models: [],
      children: [],
    } satisfies ProjectDetail;
    vi.mocked(api.post).mockResolvedValueOnce({ data: imported });
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: [imported] })
      .mockResolvedValueOnce({ data: imported });
    const store = useProjectStore();
    const projectFile = new File(["project"], "portable.sherpa");
    const renamedReference = new File(["provider bytes"], "renamed-download.zip");

    const result = await store.importProject(projectFile, [renamedReference], { subscription_id: 42, workspace_id: 8 });

    expect(result?.id).toBe(43);
    const formData = vi.mocked(api.post).mock.calls[0][1] as FormData;
    expect(formData.get("commercial_subscription_id")).toBe("42");
    expect(formData.get("commercial_workspace_id")).toBe("8");
    expect(formData.get("file")).toBe(projectFile);
    expect(formData.getAll("reference_files")).toEqual([renamedReference]);
  });

  it("exposes exact provider requirements when an external reference must be rebound", async () => {
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: "project_reference_rebind_required",
            message: "Download the required provider file and import again.",
            required_artifacts: [
              {
                artifact_id: "eigenvector.corn.archive",
                artifact_size_bytes: 1234,
                artifact_sha256: "a".repeat(64),
                provider: "Eigenvector Research",
                provider_page: "https://example.test/corn",
                download_url: "https://example.test/corn.zip",
              },
            ],
          },
        },
      },
    });
    const store = useProjectStore();

    const result = await store.importProject(new File(["project"], "portable.sherpa"));

    expect(result).toBeNull();
    expect(store.referenceRebindRequirements).toHaveLength(1);
    expect(store.referenceRebindRequirements[0].artifact_id).toBe("eigenvector.corn.archive");
    expect(store.error).toContain("provider file");
  });

  it("binds one exact local file through the canonical application boundary", async () => {
    vi.mocked(api.put).mockResolvedValueOnce({
      data: {
        workflow_id: 51,
        source_node_id: "canonical-local-source",
        integrity_hash: "a".repeat(64),
        status: "ready_for_application",
      },
    });
    const store = useProjectStore();

    const result = await store.bindCanonicalProjectSource(51, {
      experimentId: 8,
      fileId: 13,
      stage: "raw",
      assetId: "a",
    });

    expect(api.put).toHaveBeenCalledWith("/workflows/51/canonical-source", {
      experiment_id: 8,
      file_id: 13,
      stage: "raw",
      asset_id: "a",
    });
    expect(result?.status).toBe("ready_for_application");
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
      expect(localStorage.getItem("spectra_sherpa_last_project_7")).toBe("2");
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
      localStorage.setItem("spectra_sherpa_data_active_tab_v3_7_1", "5");
      localStorage.setItem("spectra_sherpa_data_active_tab_v2_7_1", "3");
      localStorage.setItem("spectra_sherpa_data_active_tab_7_1", "2");
      localStorage.setItem("spectra_sherpa_data_draft_v1:7:1", "{}");
      localStorage.setItem("spectra_sherpa_last_experiment_7_1", "44");
      localStorage.setItem("spectra_sherpa_synthesis_state_v1:7:1", "{}");

      const success = await store.deleteProject(1, "Test Project");

      expect(success).toBe(true);
      expect(api.delete).toHaveBeenCalledWith("/projects/1", { params: { confirm_name: "Test Project" } });
      expect(store.currentProjectId).toBeNull();
      expect(store.currentProject).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_last_project_7")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_data_active_tab_v3_7_1")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_data_active_tab_v2_7_1")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_data_active_tab_7_1")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_data_draft_v1:7:1")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_last_experiment_7_1")).toBeNull();
      expect(localStorage.getItem("spectra_sherpa_synthesis_state_v1:7:1")).toBeNull();
    });

    it("does not clear current if different project deleted", async () => {
      vi.mocked(api.delete).mockResolvedValueOnce({});
      vi.mocked(api.get).mockResolvedValueOnce({ data: [mockProject] });
      const store = useProjectStore();
      store.currentProjectId = 1;

      await store.deleteProject(99, "Other Project");

      expect(store.currentProjectId).toBe(1);
    });

    it("returns false on failure", async () => {
      vi.mocked(api.delete).mockRejectedValueOnce(new Error("Forbidden"));
      const store = useProjectStore();

      const success = await store.deleteProject(1, "Test Project");

      expect(success).toBe(false);
      expect(store.error).toBe("Forbidden");
    });
  });

  describe("archive lifecycle", () => {
    it("moves the active project to the archived catalog and clears selection", async () => {
      vi.mocked(api.post).mockResolvedValueOnce({});
      vi.mocked(api.get)
        .mockResolvedValueOnce({ data: [] })
        .mockResolvedValueOnce({ data: [{ ...mockProject, archived_at: new Date().toISOString() }] });
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

      expect(await store.archiveProject(1)).toBe(true);
      expect(api.post).toHaveBeenCalledWith("/projects/1/archive");
      expect(store.currentProjectId).toBeNull();
      expect(store.projects).toEqual([]);
      expect(store.archivedProjects.map((project) => project.id)).toEqual([1]);
    });

    it("restores an archived project to the active catalog", async () => {
      vi.mocked(api.post).mockResolvedValueOnce({});
      vi.mocked(api.get)
        .mockResolvedValueOnce({ data: [mockProject] })
        .mockResolvedValueOnce({ data: [] });
      const store = useProjectStore();

      expect(await store.restoreProject(1)).toBe(true);
      expect(api.post).toHaveBeenCalledWith("/projects/1/restore");
      expect(store.projects.map((project) => project.id)).toEqual([1]);
      expect(store.archivedProjects).toEqual([]);
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

describe("Explicit local campaign publisher trust", () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); });
  it("exposes the trust requirement and sends only an explicitly chosen verification document on retry", async () => {
    const store = useProjectStore();
    vi.mocked(api.post).mockRejectedValueOnce({ response: { data: { detail: {
      code: "campaign_publisher_trust_required", message: "Select publisher verification keys",
    } } } });
    const archive = new File(["signed"], "campaign.sherpa");
    expect(await store.importProject(archive)).toBeNull();
    expect(store.campaignTrustRequired).toBe(true);
    vi.mocked(api.post).mockRejectedValueOnce(new Error("Wrong issuer"));
    const keys = new File(["public"], "publisher.json");
    await store.importProject(archive, [], undefined, { file: keys, confirmed: true });
    const form = vi.mocked(api.post).mock.calls[1][1] as FormData;
    expect(form.get("publisher_trust_anchors")).toBe(keys);
    expect(form.get("publisher_trust_confirmed")).toBe("true");
    expect(store.campaignTrustRequired).toBe(false);
  });
});
