import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import { getErrorMessage } from "@/utils/errors";
import type {
  ProjectSummary,
  ProjectDetail,
  ProjectCreate,
  ProjectUpdate,
  ProjectVersionSummary,
  ProjectScriptSummary,
  ProjectScriptDetail,
  SaveProjectRequest,
} from "@/types";

// Format date for display
const formatDate = (iso: string): string => {
  const date = new Date(iso);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
};

export const useProjectStore = defineStore("project", () => {
  // State
  const projects = ref<ProjectSummary[]>([]);
  const currentProjectId = ref<number | null>(null);
  const currentProject = ref<ProjectDetail | null>(null);
  const versions = ref<ProjectVersionSummary[]>([]);
  const isLoading = ref(false);
  const error = ref<string | null>(null);

  // Getters
  const projectList = computed(() =>
    projects.value.map((p) => ({
      id: p.id,
      name: p.name,
      modified: formatDate(p.updated_at),
      description: p.description,
      technique: p.technique,
      sample_type: p.sample_type,
      experiment_count: p.experiment_count,
      workflow_count: p.workflow_count,
      script_count: p.script_count,
      model_count: p.model_count,
      children_count: p.children_count,
    }))
  );

  const recentProjects = computed(() =>
    [...projects.value]
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      )
      .slice(0, 5)
  );

  // ── CRUD ───────────────────────────────────────────────────────

  async function fetchProjects(): Promise<void> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<ProjectSummary[]>("/projects");
      projects.value = data;
    } catch (e) {
      error.value = getErrorMessage(e);
    } finally {
      isLoading.value = false;
    }
  }

  async function fetchProject(id: number): Promise<ProjectDetail | null> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.get<ProjectDetail>(`/projects/${id}`);
      currentProject.value = data;
      currentProjectId.value = id;
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    } finally {
      isLoading.value = false;
    }
  }

  async function createProject(payload: ProjectCreate): Promise<ProjectDetail | null> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.post<ProjectDetail>("/projects", payload);
      currentProject.value = data;
      currentProjectId.value = data.id;
      await fetchProjects();
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    } finally {
      isLoading.value = false;
    }
  }

  async function updateProject(id: number, payload: ProjectUpdate): Promise<ProjectDetail | null> {
    error.value = null;
    try {
      const { data } = await api.put<ProjectDetail>(`/projects/${id}`, payload);
      currentProject.value = data;
      await fetchProjects();
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function deleteProject(id: number): Promise<boolean> {
    error.value = null;
    try {
      await api.delete(`/projects/${id}`);
      if (currentProjectId.value === id) {
        currentProjectId.value = null;
        currentProject.value = null;
      }
      await fetchProjects();
      return true;
    } catch (e) {
      error.value = getErrorMessage(e);
      return false;
    }
  }

  async function selectProject(id: number): Promise<void> {
    currentProjectId.value = id;
    await fetchProject(id);
  }

  // ── Link / Unlink ─────────────────────────────────────────────

  async function linkExperiment(projectId: number, experimentId: number): Promise<void> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectDetail>(
        `/projects/${projectId}/experiments/${experimentId}`
      );
      if (currentProjectId.value === projectId) currentProject.value = data;
      await fetchProjects();
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  async function unlinkExperiment(projectId: number, experimentId: number): Promise<void> {
    error.value = null;
    try {
      const { data } = await api.delete<ProjectDetail>(
        `/projects/${projectId}/experiments/${experimentId}`
      );
      if (currentProjectId.value === projectId) currentProject.value = data;
      await fetchProjects();
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  async function linkWorkflow(projectId: number, workflowId: number): Promise<void> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectDetail>(
        `/projects/${projectId}/workflows/${workflowId}`
      );
      if (currentProjectId.value === projectId) currentProject.value = data;
      await fetchProjects();
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  async function unlinkWorkflow(projectId: number, workflowId: number): Promise<void> {
    error.value = null;
    try {
      const { data } = await api.delete<ProjectDetail>(
        `/projects/${projectId}/workflows/${workflowId}`
      );
      if (currentProjectId.value === projectId) currentProject.value = data;
      await fetchProjects();
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  // ── Save All + Versioning ─────────────────────────────────────

  async function saveProject(
    id: number,
    payload: SaveProjectRequest
  ): Promise<ProjectVersionSummary | null> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectVersionSummary>(
        `/projects/${id}/save`,
        payload
      );
      await fetchVersions(id);
      await fetchProjects();
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function fetchVersions(id: number): Promise<void> {
    error.value = null;
    try {
      const { data } = await api.get<{ versions: ProjectVersionSummary[]; total: number }>(
        `/projects/${id}/versions`
      );
      versions.value = data.versions;
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  // ── Scripts ──────────────────────────────────────────────────

  async function fetchScripts(
    projectId: number
  ): Promise<ProjectScriptSummary[]> {
    try {
      const { data } = await api.get<ProjectScriptSummary[]>(
        `/projects/${projectId}/scripts`
      );
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return [];
    }
  }

  async function createScript(
    projectId: number,
    payload: { name: string; description?: string; code: string; language?: string; priority?: number }
  ): Promise<ProjectScriptDetail | null> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectScriptDetail>(
        `/projects/${projectId}/scripts`,
        payload
      );
      if (currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function generateScript(
    projectId: number,
    payload: { workflow_id: number; name: string; description?: string; priority?: number }
  ): Promise<ProjectScriptDetail | null> {
    error.value = null;
    try {
      const { data } = await api.post<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/generate`,
        payload
      );
      if (currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function fetchScript(
    projectId: number,
    scriptId: number
  ): Promise<ProjectScriptDetail | null> {
    try {
      const { data } = await api.get<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/${scriptId}`
      );
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function updateScript(
    projectId: number,
    scriptId: number,
    payload: { name?: string; description?: string; code?: string; priority?: number }
  ): Promise<ProjectScriptDetail | null> {
    error.value = null;
    try {
      const { data } = await api.put<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/${scriptId}`,
        payload
      );
      if (currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  async function deleteScript(
    projectId: number,
    scriptId: number
  ): Promise<boolean> {
    error.value = null;
    try {
      await api.delete(`/projects/${projectId}/scripts/${scriptId}`);
      if (currentProjectId.value === projectId) await fetchProject(projectId);
      return true;
    } catch (e) {
      error.value = getErrorMessage(e);
      return false;
    }
  }

  // ── Export / Import ───────────────────────────────────────────

  async function exportProject(id: number): Promise<void> {
    error.value = null;
    try {
      const response = await api.get(`/projects/${id}/export`, {
        responseType: "blob",
      });
      const url = URL.createObjectURL(response.data);
      const a = document.createElement("a");
      a.href = url;
      // Extract filename from content-disposition or use project name
      const disposition = response.headers["content-disposition"];
      const match = disposition?.match(/filename="?(.+)"?/);
      a.download = match?.[1] || "project.spectrapy";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      error.value = getErrorMessage(e);
    }
  }

  async function importProject(file: File): Promise<ProjectDetail | null> {
    error.value = null;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const { data } = await api.post<ProjectDetail>(
        "/projects/import",
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      currentProject.value = data;
      currentProjectId.value = data.id;
      await fetchProjects();
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    }
  }

  return {
    // State
    projects,
    currentProjectId,
    currentProject,
    versions,
    isLoading,
    error,

    // Getters
    projectList,
    recentProjects,

    // CRUD
    fetchProjects,
    fetchProject,
    createProject,
    updateProject,
    deleteProject,
    selectProject,

    // Link / Unlink
    linkExperiment,
    unlinkExperiment,
    linkWorkflow,
    unlinkWorkflow,

    // Save All + Versioning
    saveProject,
    fetchVersions,

    // Scripts
    fetchScripts,
    createScript,
    generateScript,
    fetchScript,
    updateScript,
    deleteScript,

    // Export / Import
    exportProject,
    importProject,
  };
});
