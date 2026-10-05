import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import type { FolderWatch, ExecutionRunSummary, DeployApplication } from "@/types";

interface CreateWatchPayload {
  application_handle?: string | null;
  artifact_uid?: string | null;
  canonical_artifact_id?: number | null;
  uncertainty_record?: Record<string, unknown> | null;
  uncertainty_population?: string | null;
  workflow_id: number;
  name: string;
  folder_path: string;
  file_pattern?: string;
  poll_interval_sec?: number;
  asset_id?: string | null;
}

interface UpdateWatchPayload {
  application_handle?: string | null;
  artifact_uid?: string | null;
  canonical_artifact_id?: number | null;
  uncertainty_record?: Record<string, unknown> | null;
  uncertainty_population?: string | null;
  name?: string;
  folder_path?: string;
  file_pattern?: string;
  poll_interval_sec?: number;
  is_enabled?: boolean;
  asset_id?: string | null;
}

export const useDeployStore = defineStore("deploy", () => {
  const watches = ref<FolderWatch[]>([]);
  const deployRuns = ref<ExecutionRunSummary[]>([]);
  const applications = ref<DeployApplication[]>([]);
  const loading = ref(false);
  const runsLoading = ref(false);
  const applicationsLoading = ref(false);
  const watchesError = ref("");
  const runsError = ref("");
  let applicationRequest = 0;
  let watchesRequest = 0;
  let runsRequest = 0;
  let scopeGeneration = 0;

  function resetProjectScope(): void {
    scopeGeneration++;
    applicationRequest++;
    watchesRequest++;
    runsRequest++;
    watchesError.value = "";
    runsError.value = "";
    watches.value = [];
    deployRuns.value = [];
    applications.value = [];
    loading.value = false;
    runsLoading.value = false;
    applicationsLoading.value = false;
  }

  /** Load the one releaseable-application projection used by Deploy. */
  async function fetchApplications(projectId: number): Promise<void> {
    const request = ++applicationRequest;
    applicationsLoading.value = true;
    try {
      // Newer OSS servers expose a durable release handle.  Keep the paired
      // model/portable reads below as a compatibility path for older local
      // Workbenches during rolling upgrades.
      try {
        const response = await api.get<Array<Record<string, unknown>>>("/deploy/applications", {
          params: { project_id: projectId },
        });
        if (request !== applicationRequest) return;
        if (Array.isArray(response.data) && response.data.length > 0) {
          applications.value = response.data
            .filter((item) => item.state === undefined || item.state === "released")
            .map((item) => ({
              application_id: String(item.handle || item.application_id),
              application_handle: item.handle == null ? null : String(item.handle),
              origin: (item.origin === "saved_run"
                ? "saved_run"
                : "portable") as DeployApplication["origin"],
              name: String(item.label || item.name || item.handle || "Application"),
              workflow_id: Number(item.workflow_id),
              workflow_version_id:
                item.workflow_version_id == null ? null : Number(item.workflow_version_id),
              artifact_uid:
                item.model_artifact_uid == null ? null : String(item.model_artifact_uid),
              canonical_artifact_id:
                item.canonical_artifact_id == null ? null : Number(item.canonical_artifact_id),
              artifact_digest: item.artifact_digest == null ? null : String(item.artifact_digest),
              source_run_id: item.source_run_id == null ? null : Number(item.source_run_id),
              campaign_validation_recorded:
                (item.campaign_validation as { recorded?: boolean } | undefined)?.recorded === true,
              deploy_ready: true,
              refusal: null,
            }))
            .filter((item) => Number.isSafeInteger(item.workflow_id));
          return;
        }
      } catch (error: unknown) {
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status !== 404) throw error;
      }
      const [models, portable] = await Promise.all([
        api.get<Array<Record<string, unknown>>>("/models", {
          params: { project_id: projectId, deploy_ready: true, limit: 1000 },
        }),
        api.get<Array<Record<string, unknown>>>("/deploy/canonical-targets", {
          params: { project_id: projectId },
        }),
      ]);
      if (request !== applicationRequest) return;
      const savedRuns: DeployApplication[] = models.data
        .filter((model) => typeof model.artifact_uid === "string" && model.workflow_id != null)
        .map((model) => ({
          application_id: `artifact:${String(model.artifact_uid)}`,
          application_handle: null,
          origin: "saved_run",
          name: String(model.display_name || model.name || model.artifact_uid),
          workflow_id: Number(model.workflow_id),
          workflow_version_id:
            model.workflow_version_id == null ? null : Number(model.workflow_version_id),
          artifact_uid: String(model.artifact_uid),
          canonical_artifact_id: null,
          artifact_digest: null,
          source_run_id: model.source_run_id == null ? null : Number(model.source_run_id),
          deploy_ready: model.is_deploy_ready !== false,
          refusal: null,
        }));
      const portableApplications: DeployApplication[] = portable.data
        .filter((target) => target.canonical_artifact_id != null && target.workflow_id != null)
        .map((target) => ({
          application_id: `canonical:${String(target.canonical_artifact_id)}`,
          application_handle:
            target.application_handle == null ? null : String(target.application_handle),
          origin: "portable",
          name: String(target.name || "Imported application"),
          workflow_id: Number(target.workflow_id),
          workflow_version_id: null,
          artifact_uid: null,
          canonical_artifact_id: Number(target.canonical_artifact_id),
          artifact_digest:
            typeof target.artifact_digest === "string" ? target.artifact_digest : null,
          deploy_ready: target.deploy_ready !== false,
          refusal: typeof target.refusal === "string" ? target.refusal : null,
        }));
      applications.value = [...savedRuns, ...portableApplications].filter(
        (application) => application.deploy_ready,
      );
    } catch (error) {
      if (request === applicationRequest) {
        applications.value = [];
        throw error;
      }
    } finally {
      if (request === applicationRequest) applicationsLoading.value = false;
    }
  }
  registerProjectScopeReset(resetProjectScope);

  async function fetchWatches(projectId?: number): Promise<void> {
    const request = ++watchesRequest;
    loading.value = true;
    try {
      const response = await api.get<FolderWatch[]>("/deploy/watches", {
        params: projectId == null ? {} : { project_id: projectId },
      });
      if (request !== watchesRequest) return;
      watches.value = response.data;
      watchesError.value = "";
    } catch (error) {
      if (request === watchesRequest) watchesError.value = "Folder watches could not be loaded.";
    } finally {
      if (request === watchesRequest) loading.value = false;
    }
  }

  async function createWatch(payload: CreateWatchPayload): Promise<FolderWatch> {
    const scope = scopeGeneration;
    const response = await api.post<FolderWatch>("/deploy/watches", payload);
    if (scope !== scopeGeneration) return response.data;
    watches.value = [response.data, ...watches.value];
    return response.data;
  }

  async function updateWatch(watchId: number, payload: UpdateWatchPayload): Promise<FolderWatch> {
    const scope = scopeGeneration;
    const response = await api.patch<FolderWatch>(`/deploy/watches/${watchId}`, payload);
    if (scope !== scopeGeneration) return response.data;
    const idx = watches.value.findIndex((w) => w.id === watchId);
    if (idx !== -1) {
      watches.value[idx] = response.data;
    }
    return response.data;
  }

  async function deleteWatch(watchId: number): Promise<void> {
    await api.delete(`/deploy/watches/${watchId}`);
    watches.value = watches.value.filter((w) => w.id !== watchId);
  }

  async function toggleWatch(watchId: number, enable: boolean): Promise<FolderWatch> {
    const scope = scopeGeneration;
    const endpoint = enable ? "enable" : "disable";
    const response = await api.post<FolderWatch>(`/deploy/watches/${watchId}/${endpoint}`);
    if (scope !== scopeGeneration) return response.data;
    const idx = watches.value.findIndex((w) => w.id === watchId);
    if (idx !== -1) {
      watches.value[idx] = response.data;
    }
    return response.data;
  }

  async function fetchDeployRuns(
    sourceType?: string,
    label?: string,
    projectId?: number,
  ): Promise<void> {
    const request = ++runsRequest;
    runsLoading.value = true;
    try {
      const params: Record<string, string | number> = {};
      if (projectId != null) params.project_id = projectId;
      if (sourceType) params.source_type = sourceType;
      if (label) params.label = label;
      const response = await api.get<{
        runs: ExecutionRunSummary[];
        total: number;
      }>("/deploy/runs", { params });
      if (request !== runsRequest) return;
      deployRuns.value = response.data.runs;
      runsError.value = "";
    } catch (error) {
      if (request === runsRequest) runsError.value = "Prediction history could not be loaded.";
    } finally {
      if (request === runsRequest) runsLoading.value = false;
    }
  }

  return {
    watches,
    deployRuns,
    applications,
    loading,
    runsLoading,
    applicationsLoading,
    watchesError,
    runsError,
    fetchWatches,
    createWatch,
    updateWatch,
    deleteWatch,
    toggleWatch,
    fetchDeployRuns,
    fetchApplications,
    resetProjectScope,
  };
});
