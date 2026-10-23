import { formatRelativeTime } from "@/utils/format";
import { defineStore } from "pinia";
import { ref, computed, watch } from "vue";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import { projectDetail, projectSummary } from "@/api/adapters/projects";
import { useAuthStore } from "@/stores/auth";
import { activeProjectScope, runProjectScopeResets } from "@/stores/projectScopeRegistry";
import { downloadBlob, filenameFromContentDisposition } from "@/utils/download";
import { getErrorMessage } from "@/utils/errors";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";

const LAST_ACTIVE_PROJECT_PREFIX = "spectra_sherpa_last_project_";
const DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab_v3";
const PREVIOUS_DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab_v2";
const LEGACY_DATA_ACTIVE_TAB_PREFIX = "spectra_sherpa_data_active_tab";
const DATA_DRAFT_PREFIX = "spectra_sherpa_data_draft_v1";
const LAST_ACTIVE_EXPERIMENT_PREFIX = "spectra_sherpa_last_experiment";
const SYNTHESIS_STATE_PREFIX = "spectra_sherpa_synthesis_state_v1";

export interface CanonicalProjectSourceBinding {
  workflow_id: number;
  source_node_id: string;
  integrity_hash: string;
  status: "ready_for_application" | "dependency_blocked";
}

export interface ProjectReferenceArtifactRequirement {
  artifact_id: string;
  artifact_size_bytes: number;
  artifact_sha256: string;
  provider: string;
  provider_page: string;
  download_url: string;
}

interface ProjectReferenceRebindDetail {
  code: "project_reference_rebind_required";
  message: string;
  required_artifacts: ProjectReferenceArtifactRequirement[];
}

function projectReferenceRebindDetail(error: unknown): ProjectReferenceRebindDetail | null {
  if (typeof error !== "object" || error === null || !("response" in error)) return null;
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } }).response;
  if (response?.status !== 409) return null;
  const detail = response.data?.detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return null;
  const candidate = detail as Record<string, unknown>;
  if (
    candidate.code !== "project_reference_rebind_required" ||
    typeof candidate.message !== "string" ||
    !Array.isArray(candidate.required_artifacts)
  ) {
    return null;
  }
  const requirements = candidate.required_artifacts.filter(
    (item): item is ProjectReferenceArtifactRequirement =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as Record<string, unknown>).artifact_id === "string" &&
      typeof (item as Record<string, unknown>).artifact_size_bytes === "number" &&
      typeof (item as Record<string, unknown>).artifact_sha256 === "string" &&
      typeof (item as Record<string, unknown>).provider === "string" &&
      typeof (item as Record<string, unknown>).provider_page === "string" &&
      typeof (item as Record<string, unknown>).download_url === "string",
  );
  if (requirements.length !== candidate.required_artifacts.length || requirements.length === 0) {
    return null;
  }
  return {
    code: "project_reference_rebind_required",
    message: candidate.message,
    required_artifacts: requirements,
  };
}

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
    localStorage.removeItem(`${PREVIOUS_DATA_ACTIVE_TAB_PREFIX}_${scopeUserId}_${projectId}`);
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
  ImportedApplicationIdentity,
} from "@/types";

// Format date for display
export const useProjectStore = defineStore("project", () => {
  // State
  const projects = ref<ProjectSummary[]>([]);
  const archivedProjects = ref<ProjectSummary[]>([]);
  const currentProjectId = ref<number | null>(null);
  watch(currentProjectId, (id) => { activeProjectScope.value = id; }, { immediate: true, flush: "sync" });
  const currentProject = ref<ProjectDetail | null>(null);
  const versions = ref<ProjectVersionSummary[]>([]);
  const isLoading = ref(false);
  let loadingOwner: ScopedRequestTicket | null = null;
  function beginLoading(request: ScopedRequestTicket): void {
    loadingOwner = request;
    isLoading.value = true;
  }
  function finishLoading(request: ScopedRequestTicket): void {
    if (loadingOwner !== request) return;
    loadingOwner = null;
    isLoading.value = false;
  }
  const error = ref<string | null>(null);
  const exportingProjectIds = ref<number[]>([]);
  const lastExportOmittedModels = ref(0);
  const isImporting = ref(false);
  // Kept separately from ProjectDetail because the follow-up fetch used to
  // hydrate the project is intentionally a normal project response. This
  // preserves the one-time import hand-off until ProjectContent navigates to
  // Deploy with the selected application.
  const lastImportedApplication = ref<ImportedApplicationIdentity | null>(null);
  const referenceRebindRequirements = ref<ProjectReferenceArtifactRequirement[]>([]);

  // Identity changes invalidate the entire in-memory scientific workspace.
  // Keep per-user saved preferences, but never carry one user's active project
  // into another session or allow its pending reads to restore that context.
  watch([() => useAuthStore().user?.id ?? null, () => useAuthStore().sessionRevision], () => {
    currentProjectId.value = null;
    currentProject.value = null;
    projects.value = [];
    archivedProjects.value = [];
    versions.value = [];
    error.value = null;
    isLoading.value = false;
    isImporting.value = false;
    loadingOwner = null;
    lastImportedApplication.value = null;
    referenceRebindRequirements.value = [];
    runProjectScopeResets();
  }, { flush: "sync" });
  let requestedProjectId: number | null = null;
  const projectRead = useScopedRequest(
    () => [useAuthStore().user?.id, useAuthStore().sessionRevision],
    () => {
      requestedProjectId = null;
      if (loadingOwner && !loadingOwner.isCurrent()) finishLoading(loadingOwner);
    },
  );
  // Navigation owns its pending destination, not the last admitted project.
  // Removing that old project must not cancel a newer destination's admission.
  let committingSelection = false;
  watch(currentProjectId, () => {
    if (!committingSelection) projectRead.invalidate();
  }, { flush: "sync" });
  function commitSelection(project: ProjectDetail | null): void {
    committingSelection = true;
    try {
      if (currentProjectId.value !== (project?.id ?? null)) runProjectScopeResets();
      currentProjectId.value = project?.id ?? null;
      currentProject.value = project;
      writeLastActiveProjectId(useAuthStore().user?.id ?? null, project?.id ?? null);
    } finally {
      committingSelection = false;
    }
  }
  const workspaceMutation = useScopedRequest(
    () => [useAuthStore().user?.id, useAuthStore().sessionRevision, currentProjectId.value],
    () => {
      if (loadingOwner && !loadingOwner.isCurrent()) finishLoading(loadingOwner);
    },
  );
  const captureMutationScope = workspaceMutation.capture;
  const accountMutation = useScopedRequest(() => [useAuthStore().user?.id, useAuthStore().sessionRevision]);
  const versionsRead = useScopedRequest(() => [useAuthStore().user?.id, useAuthStore().sessionRevision, currentProjectId.value]);
  // These are account-wide inventories, not children of the active project.
  // Selecting a deep-linked project must not cancel the selector's own list.
  const projectListRead = useScopedRequest(() => [useAuthStore().user?.id, useAuthStore().sessionRevision]);
  const archiveListRead = useScopedRequest(() => [useAuthStore().user?.id, useAuthStore().sessionRevision]);
  watch(currentProjectId, (id) => {
    if (currentProject.value?.id !== id) currentProject.value = null;
    versions.value = [];
    exportingProjectIds.value = [];
    lastExportOmittedModels.value = 0;
  }, { flush: "sync" });

  // Getters
  const projectList = computed(() =>
    projects.value.map((p) => ({
      id: p.id,
      name: p.name,
      modified: formatRelativeTime(p.updated_at),
      description: p.description,
      technique: p.technique,
      sample_type: p.sample_type,
      experiment_count: p.experiment_count,
      workflow_count: p.workflow_count,
      script_count: p.script_count,
      model_count: p.model_count,
      children_count: p.children_count,
    })),
  );

  const recentProjects = computed(() =>
    [...projects.value]
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 5),
  );

  const activeProjectTitle = computed(() => currentProject.value?.name ?? "No Project");

  // ── CRUD ───────────────────────────────────────────────────────

  async function fetchProjects(): Promise<void> {
    const request = projectListRead.begin();
    beginLoading(request);
    error.value = null;
    try {
      const { data } = await api.get<components["schemas"]["ProjectSummary"][]>("/projects", { signal: request.signal });
      if (!request.isCurrent()) return;
      projects.value = data.map(projectSummary);
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    } finally {
      if (request.isCurrent()) finishLoading(request);
    }
  }

  async function fetchArchivedProjects(): Promise<void> {
    const request = archiveListRead.begin();
    error.value = null;
    try {
      const { data } = await api.get<components["schemas"]["ProjectSummary"][]>("/projects", { params: { archived: true }, signal: request.signal });
      if (!request.isCurrent()) return;
      archivedProjects.value = data.map(projectSummary);
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    }
  }

  let pendingProject: { id: number; ticket: ScopedRequestTicket; promise: Promise<ProjectDetail | null> } | null = null;
  function fetchProject(id: number): Promise<ProjectDetail | null> {
    if (pendingProject?.id === id && pendingProject.ticket.isCurrent()) return pendingProject.promise;
    // An earlier accepted write may still refresh inventories, but cannot
    // select its result after the user has requested another project.
    // A same-project refresh is not navigation and must not retire write errors.
    if (id !== currentProjectId.value) workspaceMutation.invalidate();
    const request = projectRead.begin();
    requestedProjectId = id;
    beginLoading(request);
    error.value = null;
    const promise = loadProject(id, request);
    pendingProject = { id, ticket: request, promise };
    return promise;
  }

  async function loadProject(id: number, request: ScopedRequestTicket): Promise<ProjectDetail | null> {
    try {
      const { data: wire } = await api.get<components["schemas"]["ProjectDetail"]>(`/projects/${id}`, { signal: request.signal });
      if (!request.isCurrent()) return null;
      const data = projectDetail(wire);
      // Commit selection only after admission succeeds. A 404 must not destroy
      // the still-valid workspace or persist an unloadable selection.
      finishLoading(request);
      commitSelection(data);
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    } finally {
      if (pendingProject?.ticket === request) pendingProject = null;
      if (request.isCurrent()) {
        requestedProjectId = null;
        finishLoading(request);
      }
    }
  }

  function getLastActiveProjectId(): number | null {
    return readLastActiveProjectId(useAuthStore().user?.id ?? null);
  }

  async function createProject(payload: ProjectCreate): Promise<ProjectDetail | null> {
    projectRead.invalidate();
    const request = workspaceMutation.begin();
    const account = accountMutation.capture();
    beginLoading(request);
    error.value = null;
    try {
      const { data: wire } = await api.post<components["schemas"]["ProjectDetail"]>("/projects", payload);
      const data = projectDetail(wire);
      if (request.isCurrent()) {
        finishLoading(request);
        commitSelection(data);
      }
      if (account.isCurrent()) await fetchProjects();
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    } finally {
      if (request.isCurrent()) finishLoading(request);
    }
  }

  async function updateProject(id: number, payload: ProjectUpdate): Promise<ProjectDetail | null> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      const { data: wire } = await api.put<components["schemas"]["ProjectDetail"]>(`/projects/${id}`, payload);
      const data = projectDetail(wire);
      if (request.isCurrent() && currentProjectId.value === id) currentProject.value = data;
      if (account.isCurrent()) await fetchProjects();
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  async function archiveProject(id: number): Promise<boolean> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      await api.post(`/projects/${id}/archive`);
      if (!account.isCurrent()) return true;
      if (requestedProjectId === id) projectRead.invalidate();
      if (currentProjectId.value === id) {
        commitSelection(null);
      }
      await Promise.all([fetchProjects(), fetchArchivedProjects()]);
      return true;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return false;
    }
  }

  async function restoreProject(id: number): Promise<boolean> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      await api.post(`/projects/${id}/restore`);
      if (!account.isCurrent()) return true;
      await Promise.all([fetchProjects(), fetchArchivedProjects()]);
      return true;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return false;
    }
  }

  async function deleteProject(id: number, confirmName: string): Promise<boolean> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      await api.delete(`/projects/${id}`, { params: { confirm_name: confirmName } });
      if (!account.isCurrent()) return true;
      if (requestedProjectId === id) projectRead.invalidate();
      const wasActive = currentProjectId.value === id;
      if (wasActive) {
        // Drop every project-scoped store's in-memory state so a deleted
        // active project doesn't leave a stale runs list / advisor channel /
        // experiment selection in the UI. Pending navigation remains owned
        // by its destination even while the deleted workspace is cleared.
        commitSelection(null);
      }
      clearProjectScopedBrowserState(useAuthStore().user?.id ?? null, id);
      await Promise.all([fetchProjects(), fetchArchivedProjects()]);
      return true;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return false;
    }
  }

  async function selectProject(id: number): Promise<void> {
    await fetchProject(id);
  }

  async function loadProjectContext(id: number): Promise<ProjectDetail | null> {
    return fetchProject(id);
  }

  async function ensureProjectForBrowserTab(): Promise<ProjectDetail | null> {
    const request = captureMutationScope();
    if (currentProject.value) {
      return currentProject.value;
    }

    if (projects.value.length === 0) {
      await fetchProjects();
    }
    if (!request.isCurrent()) return null;

    const lastActiveId = getLastActiveProjectId();
    if (lastActiveId && projects.value.some((project) => project.id === lastActiveId)) {
      return fetchProject(lastActiveId);
    }

    const recent = recentProjects.value[0];
    return recent ? fetchProject(recent.id) : null;
  }

  // ── Link / Unlink ─────────────────────────────────────────────

  async function linkExperiment(projectId: number, experimentId: number): Promise<void> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      const { data: wire } = await api.post<components["schemas"]["ProjectDetail"]>(
        `/projects/${projectId}/experiments/${experimentId}`,
      );
      const data = projectDetail(wire);
      if (request.isCurrent() && currentProjectId.value === projectId) currentProject.value = data;
      if (account.isCurrent()) await fetchProjects();
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    }
  }

  async function unlinkExperiment(projectId: number, experimentId: number, destinationProjectId?: number): Promise<void> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      const { data: wire } = await api.delete<components["schemas"]["ProjectDetail"]>(
        `/projects/${projectId}/experiments/${experimentId}`,
        { params: { destination_project_id: destinationProjectId } },
      );
      const data = projectDetail(wire);
      if (request.isCurrent() && currentProjectId.value === projectId) currentProject.value = data;
      if (account.isCurrent()) await fetchProjects();
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    }
  }

  async function linkWorkflow(projectId: number, workflowId: number): Promise<void> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      const { data: wire } = await api.post<components["schemas"]["ProjectDetail"]>(
        `/projects/${projectId}/workflows/${workflowId}`,
      );
      const data = projectDetail(wire);
      if (request.isCurrent() && currentProjectId.value === projectId) currentProject.value = data;
      if (account.isCurrent()) await fetchProjects();
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    }
  }

  async function unlinkWorkflow(projectId: number, workflowId: number, destinationProjectId?: number): Promise<void> {
    const request = captureMutationScope();
    const account = accountMutation.capture();
    error.value = null;
    try {
      const { data: wire } = await api.delete<components["schemas"]["ProjectDetail"]>(
        `/projects/${projectId}/workflows/${workflowId}`,
        { params: { destination_project_id: destinationProjectId } },
      );
      const data = projectDetail(wire);
      if (request.isCurrent() && currentProjectId.value === projectId) currentProject.value = data;
      if (account.isCurrent()) await fetchProjects();
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
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
        : summary,
    );
  }

  // ── Versioning ────────────────────────────────────────────────

  async function fetchVersions(id: number): Promise<void> {
    const request = versionsRead.begin();
    error.value = null;
    try {
      const { data } = await api.get<{ versions: ProjectVersionSummary[]; total: number }>(
        `/projects/${id}/versions`,
        { signal: request.signal },
      );
      if (request.isCurrent()) versions.value = data.versions;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    }
  }

  // ── Scripts ──────────────────────────────────────────────────

  async function fetchScripts(projectId: number): Promise<ProjectScriptSummary[]> {
    const request = captureMutationScope();
    try {
      const { data } = await api.get<ProjectScriptSummary[]>(`/projects/${projectId}/scripts`, { signal: request.signal });
      return request.isCurrent() ? data : [];
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return [];
    }
  }

  async function createScript(
    projectId: number,
    payload: {
      name: string;
      description?: string;
      code: string;
      language?: string;
      priority?: number;
    },
  ): Promise<ProjectScriptDetail | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.post<ProjectScriptDetail>(
        `/projects/${projectId}/scripts`,
        payload,
      );
      if (request.isCurrent() && currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  async function generateScript(
    projectId: number,
    payload: { workflow_id: number; name: string; description?: string; priority?: number },
  ): Promise<ProjectScriptDetail | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.post<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/generate`,
        payload,
      );
      if (request.isCurrent() && currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  async function fetchScript(
    projectId: number,
    scriptId: number,
  ): Promise<ProjectScriptDetail | null> {
    const request = captureMutationScope();
    try {
      const { data } = await api.get<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/${scriptId}`,
        { signal: request.signal },
      );
      return request.isCurrent() ? data : null;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  async function updateScript(
    projectId: number,
    scriptId: number,
    payload: { name?: string; description?: string; code?: string; priority?: number },
  ): Promise<ProjectScriptDetail | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.put<ProjectScriptDetail>(
        `/projects/${projectId}/scripts/${scriptId}`,
        payload,
      );
      if (request.isCurrent() && currentProjectId.value === projectId) await fetchProject(projectId);
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  async function deleteScript(projectId: number, scriptId: number): Promise<boolean> {
    const request = captureMutationScope();
    error.value = null;
    try {
      await api.delete(`/projects/${projectId}/scripts/${scriptId}`);
      if (request.isCurrent() && currentProjectId.value === projectId) await fetchProject(projectId);
      return true;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return false;
    }
  }

  // ── Export / Import ───────────────────────────────────────────

  async function exportProject(id: number): Promise<void> {
    if (exportingProjectIds.value.includes(id)) return;
    const request = captureMutationScope();
    error.value = null;
    lastExportOmittedModels.value = 0;
    exportingProjectIds.value = [...exportingProjectIds.value, id];
    try {
      const response = await api.get(`/projects/${id}/export/sherpa`, {
        responseType: "blob",
        signal: request.signal,
      });
      if (!request.isCurrent()) return;
      // Extract filename from content-disposition or use project name
      const disposition = response.headers["content-disposition"];
      const omitted = Number(response.headers["x-spectra-project-model-omissions"] ?? 0);
      lastExportOmittedModels.value = Number.isSafeInteger(omitted) && omitted > 0 ? omitted : 0;
      downloadBlob(response.data, filenameFromContentDisposition(disposition, "project.sherpa"));
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
    } finally {
      if (request.isCurrent()) exportingProjectIds.value = exportingProjectIds.value.filter((projectId) => projectId !== id);
    }
  }

  async function refreshImportedProjectSlices(projectId: number): Promise<void> {
    const request = captureMutationScope();
    const [{ useDataStore }, { useDataSourceStore }, { useExperimentStore }, { useRunsStore }] =
      await Promise.all([
        import("@/stores/data"),
        import("@/stores/dataSources"),
        import("@/stores/experiment"),
        import("@/stores/runs"),
      ]);
    if (!request.isCurrent()) return;

    const dataStore = useDataStore();
    await Promise.allSettled([
      dataStore.fetchExperiments(projectId),
      dataStore.fetchCatalog(projectId),
      useDataSourceStore().loadProjectDataSources(projectId),
      useExperimentStore().fetchExperiments(projectId),
      useRunsStore().fetchProjectRuns(projectId),
    ]);
  }

  const campaignTrustRequired = ref(false);

  async function importProject(
    file: File,
    referenceFiles: File[] = [],
    destination?: { subscription_id: number; workspace_id: number | null },
    publisherTrust?: { file: File; confirmed: boolean },
  ): Promise<ProjectDetail | null> {
    if (isImporting.value) return null;
    projectRead.invalidate();
    let request = workspaceMutation.begin();
    const account = accountMutation.capture();
    error.value = null;
    campaignTrustRequired.value = false;
    referenceRebindRequirements.value = [];
    lastImportedApplication.value = null;
    isImporting.value = true;
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (publisherTrust) {
        formData.append("publisher_trust_anchors", publisherTrust.file);
        formData.append("publisher_trust_confirmed", String(publisherTrust.confirmed));
      }
      if (destination) {
        formData.append("commercial_subscription_id", String(destination.subscription_id));
        if (destination.workspace_id !== null) formData.append("commercial_workspace_id", String(destination.workspace_id));
      }
      for (const referenceFile of referenceFiles) {
        formData.append("reference_files", referenceFile);
      }
      const { data: wire } = await api.post<components["schemas"]["ProjectDetail"]>("/projects/import", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const data = projectDetail(wire);
      // The import may already be durable even if the user left this project.
      // Refresh the account catalogue without selecting its new project.
      if (account.isCurrent()) await fetchProjects();
      if (!request.isCurrent()) return data;
      lastImportedApplication.value = data.application ?? (data.application_handle
        ? {
            handle: data.application_handle,
            origin: "portable",
            project_id: data.id,
            workflow_id: Number((data.metadata?.canonical_project as Record<string, unknown> | undefined)?.application_workflow_id || 0),
          }
        : null);
      commitSelection(data);
      isImporting.value = true;
      const hydrated = await fetchProject(data.id);
      if (!hydrated || currentProjectId.value !== data.id) return data;
      request = captureMutationScope();
      await refreshImportedProjectSlices(data.id);
      return data;
    } catch (e) {
      if (!request.isCurrent()) return null;
      campaignTrustRequired.value = (e as any)?.response?.data?.detail?.code === "campaign_publisher_trust_required";
      const rebind = projectReferenceRebindDetail(e);
      if (rebind) {
        referenceRebindRequirements.value = rebind.required_artifacts;
        error.value = rebind.message;
      } else {
        error.value = getErrorMessage(e);
      }
      return null;
    } finally {
      if (account.isCurrent()) isImporting.value = false;
    }
  }

  async function bindCanonicalProjectSource(
    workflowId: number,
    source: { experimentId: number; fileId: number; stage: string; assetId?: string | null },
  ): Promise<CanonicalProjectSourceBinding | null> {
    const request = captureMutationScope();
    error.value = null;
    try {
      const { data } = await api.put<CanonicalProjectSourceBinding>(
        `/workflows/${workflowId}/canonical-source`,
        {
          experiment_id: source.experimentId,
          file_id: source.fileId,
          stage: source.stage,
          ...(source.assetId ? { asset_id: source.assetId } : {}),
        },
      );
      if (request.isCurrent() && currentProjectId.value !== null) {
        await Promise.all([
          fetchProject(currentProjectId.value),
          refreshImportedProjectSlices(currentProjectId.value),
        ]);
      }
      return data;
    } catch (e) {
      if (request.isCurrent()) error.value = getErrorMessage(e);
      return null;
    }
  }

  return {
    // State
    projects,
    archivedProjects,
    currentProjectId,
    currentProject,
    versions,
    isLoading,
    error,
    exportingProjectIds,
    lastExportOmittedModels,
    isImporting,
    lastImportedApplication,
    referenceRebindRequirements,

    // Getters
    projectList,
    recentProjects,
    activeProjectTitle,

    // CRUD
    fetchProjects,
    fetchArchivedProjects,
    fetchProject,
    createProject,
    updateProject,
    archiveProject,
    restoreProject,
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
    campaignTrustRequired,
    bindCanonicalProjectSource,
  };
});
