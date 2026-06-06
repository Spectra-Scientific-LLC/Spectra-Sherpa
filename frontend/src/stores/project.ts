import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "@/api/client";
import { useAuthStore } from "@/stores/auth";
import { runProjectScopeResets } from "@/stores/projectScopeRegistry";
import { getErrorMessage } from "@/utils/errors";

const LAST_ACTIVE_PROJECT_PREFIX = "spectra_sherpa_last_project_";
const DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab_v2";
const LEGACY_DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab";
const DATA_DRAFT_PREFIX = "spectra_sherpa_data_draft_v1";
const LAST_ACTIVE_EXPERIMENT_PREFIX = "spectra_sherpa_last_experiment";
const SYNTHESIS_STATE_PREFIX = "spectra_sherpa_synthesis_state_v1";

// "local" is the canonical sentinel for "no signed-in user" across every
// project-scoped localStorage key in the SPA (see also workbook.ts,
// data.ts, synthesis.ts). Earlier code paths wrote some keys under "anon"
// and others under "local" for the same logged-out state, splitting a
// single user's saved preferences between two key spaces.
const lastActiveProjectKey = (userId: number | string | null): string =>
  `${LAST_ACTIVE_PROJECT_PREFIX}${userId ?? "local"}`;

const readLastActiveProjectId = (userId: number | string | null): number | null => {
  try {
    const raw = localStorage.getItem(lastActiveProjectKey(userId));
    const parsed = raw === null ? NaN : Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  } catch {
    return null;
  }
};

const writeLastActiveProjectId = (userId: number | string | null, id: number | null): void => {
  try {
    if (id === null) localStorage.removeItem(lastActiveProjectKey(userId));
    else localStorage.setItem(lastActiveProjectKey(userId), String(id));
  } catch {
    /* localStorage may be unavailable in some sandboxes */
  }
};

const clearProjectScopedBrowserState = (
  userId: number | string | null,
  projectId: number,
): void => {
  const scopeUserId = userId ?? "local";
  try {
    localStorage.removeItem(`${DATA_ACTIVE_TAB_PREFIX}_${scopeUserId}_${projectId}`);
    localStorage.removeItem(`${LEGACY_DATA_ACTIVE_TAB_PREFIX}_${scopeUserId}_${projectId}`);
    localStorage.removeItem(`${DATA_DRAFT_PREFIX}:${scopeUserId}:${projectId}`);
    localStorage.removeItem(`${LAST_ACTIVE_EXPERIMENT_PREFIX}_${scopeUserId}_${projectId}`);
    localStorage.removeItem(`${SYNTHESIS_STATE_PREFIX}:${scopeUserId}:${projectId}`);
  } catch {
    /* localStorage may be unavailable in hardened browsers/tests. */
  }
};
import type {
  ProjectSummary,
  ProjectDetail,
  ProjectCreate,
  ProjectUpdate,
  ProjectVersionSummary,
  ProjectScriptSummary,
  ProjectScriptDetail,
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

  const activeProjectTitle = computed(() => currentProject.value?.name ?? "No Project");

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
      writeLastActiveProjectId(useAuthStore().user?.id ?? null, id);
      return data;
    } catch (e) {
      error.value = getErrorMessage(e);
      return null;
    } finally {
      isLoading.value = false;
    }
  }

  function getLastActiveProjectId(): number | null {
    return readLastActiveProjectId(useAuthStore().user?.id ?? null);
  }

  async function createProject(payload: ProjectCreate): Promise<ProjectDetail | null> {
    isLoading.value = true;
    error.value = null;
    try {
      const { data } = await api.post<ProjectDetail>("/projects", payload);
      currentProject.value = data;
      currentProjectId.value = data.id;
      writeLastActiveProjectId(useAuthStore().user?.id ?? null, data.id);
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
      const wasActive = currentProjectId.value === id;
      if (wasActive) {
        currentProjectId.value = null;
        currentProject.value = null;
        writeLastActiveProjectId(useAuthStore().user?.id ?? null, null);
        // Drop every project-scoped store's in-memory state so a deleted
        // active project doesn't leave a stale runs list / advisor channel /
        // experiment selection in the UI.
        runProjectScopeResets();
      }
      clearProjectScopedBrowserState(useAuthStore().user?.id ?? null, id);
      await fetchProjects();
      return true;
    } catch (e) {
      error.value = getErrorMessage(e);
      return false;
    }
  }

  async function selectProject(id: number): Promise<void> {
    // Avoid a no-op reset on the current project — the user hasn't switched
    // away, and resetting would wipe legitimately-loaded state.
    const switching = currentProjectId.value !== id;
    if (switching) {
      // Atomic project-scope swap: clear every store's project-scoped state
      // BEFORE the new project loads, so the UI never briefly renders a
      // mixture of the previous and the next project's data.
      runProjectScopeResets();
    }
    currentProjectId.value = id;
    await fetchProject(id);
  }

  async function loadProjectContext(id: number): Promise<ProjectDetail | null> {
    return fetchProject(id);
  }

  async function ensureProjectForBrowserTab(): Promise<ProjectDetail | null> {
    if (currentProject.value) {
      return currentProject.value;
    }

    if (projects.value.length === 0) {
      await fetchProjects();
    }

    const lastActiveId = getLastActiveProjectId();
    if (lastActiveId && projects.value.some((project) => project.id === lastActiveId)) {
      return fetchProject(lastActiveId);
    }

    const recent = recentProjects.value[0];
    return recent ? fetchProject(recent.id) : null;
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

  function removeWorkflowFromCurrentProject(workflowId: number): void {
    const project = currentProject.value;
    if (!project?.workflows.some((workflow) => workflow.id === workflowId)) {
      return;
    }

    currentProject.value = {
      ...project,
      workflow_count: Math.max(0, project.workflow_count - 1),
      workflows: project.workflows.filter((workflow) => workflow.id !== workflowId),
    };

    projects.value = projects.value.map((summary) =>
      summary.id === project.id
        ? { ...summary, workflow_count: Math.max(0, summary.workflow_count - 1) }
        : summary
    );
  }

  // ── Versioning ────────────────────────────────────────────────

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
      writeLastActiveProjectId(useAuthStore().user?.id ?? null, data.id);
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
    activeProjectTitle,

    // CRUD
    fetchProjects,
    fetchProject,
    createProject,
    updateProject,
    deleteProject,
    selectProject,
    loadProjectContext,
    ensureProjectForBrowserTab,
    getLastActiveProjectId,

    // Link / Unlink
    linkExperiment,
    unlinkExperiment,
    linkWorkflow,
    unlinkWorkflow,
    removeWorkflowFromCurrentProject,

    // Versioning
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
