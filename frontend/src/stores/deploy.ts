import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/api/client";
import type { components } from "@/types/api/v1";
import { folderWatch } from "@/api/adapters/deploy";
import { runSummary } from "@/api/adapters/runs";
import { activeProjectScope, registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { useAuthStore } from "@/stores/auth";
import { useScopedRequest } from "@/composables/useScopedRequest";
import type { FolderWatch, ExecutionRunSummary, DeployApplication } from "@/types";

type CreateWatchPayload = components["schemas"]["FolderWatchCreate"];
type UpdateWatchPayload = components["schemas"]["FolderWatchUpdate"];

export const useDeployStore = defineStore("deploy", () => {
  const watches = ref<FolderWatch[]>([]);
  const deployRuns = ref<ExecutionRunSummary[]>([]);
  const applications = ref<DeployApplication[]>([]);
  const loading = ref(false);
  const runsLoading = ref(false);
  const applicationsLoading = ref(false);
  const watchesError = ref("");
  const runsError = ref("");
  const account = () => [useAuthStore().user?.id, useAuthStore().token] as const;
  const identity = () => [...account(), activeProjectScope.value];
  const applicationRequests = useScopedRequest(identity, () => {
    applications.value = [];
    applicationsLoading.value = false;
  });
  const watchesRequests = useScopedRequest(identity, () => {
    watchesProject = undefined;
    watches.value = [];
    watchesError.value = "";
    loading.value = false;
  });
  const runsRequests = useScopedRequest(identity, () => {
    deployRuns.value = [];
    runsError.value = "";
    runsLoading.value = false;
  });
  const mutations = useScopedRequest(account, undefined, { abortOnInvalidate: false });
  let watchesProject: number | null | undefined;

  function resetProjectScope(): void {
    applicationRequests.invalidate();
    watchesRequests.invalidate();
    runsRequests.invalidate();
    watchesProject = undefined;
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
    const request = applicationRequests.begin();
    applicationsLoading.value = true;
    try {
      // Newer OSS servers expose a durable release handle.  Keep the paired
      // model/portable reads below as a compatibility path for older local
      // Workbenches during rolling upgrades.
      try {
        const response = await api.get<Array<Record<string, unknown>>>("/deploy/applications", {
          params: { project_id: projectId },
          signal: request.signal,
        });
        if (!request.isCurrent()) return;
        if (Array.isArray(response.data)) {
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
        if (!request.isCurrent()) return;
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status !== 404) throw error;
      }
      const [models, portable] = await Promise.all([
        api.get<Array<Record<string, unknown>>>("/models", {
          params: { project_id: projectId, deploy_ready: true, limit: 1000 },
          signal: request.signal,
        }),
        api.get<Array<Record<string, unknown>>>("/deploy/canonical-targets", {
          params: { project_id: projectId },
          signal: request.signal,
        }),
      ]);
      if (!request.isCurrent()) return;
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
      if (request.isCurrent()) {
        applications.value = [];
        throw error;
      }
    } finally {
      if (request.isCurrent()) applicationsLoading.value = false;
    }
  }
  registerProjectScopeReset(resetProjectScope);

  async function fetchWatches(projectId?: number): Promise<void> {
    watchesProject = projectId ?? null;
    const request = watchesRequests.begin();
    loading.value = true;
    try {
      const response = await api.get<components["schemas"]["FolderWatchOut"][]>("/deploy/watches", {
        params: projectId == null ? {} : { project_id: projectId },
        signal: request.signal,
      });
      if (!request.isCurrent()) return;
      watches.value = response.data.map(folderWatch);
      watchesError.value = "";
    } catch (error) {
      if (request.isCurrent()) watchesError.value = "Folder watches could not be loaded.";
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  }

  async function createWatch(payload: CreateWatchPayload): Promise<FolderWatch> {
    const request = mutations.capture();
    const response = await api.post<components["schemas"]["FolderWatchOut"]>("/deploy/watches", payload);
    const watch = folderWatch(response.data);
    if (request.isCurrent() && watchesProject !== undefined) await fetchWatches(watchesProject ?? undefined);
    return watch;
  }

  async function updateWatch(watchId: number, payload: UpdateWatchPayload): Promise<FolderWatch> {
    const request = mutations.capture();
    const response = await api.patch<components["schemas"]["FolderWatchOut"]>(`/deploy/watches/${watchId}`, payload);
    const watch = folderWatch(response.data);
    if (request.isCurrent() && watchesProject !== undefined) await fetchWatches(watchesProject ?? undefined);
    return watch;
  }

  async function deleteWatch(watchId: number): Promise<void> {
    const request = mutations.capture();
    await api.delete(`/deploy/watches/${watchId}`);
    if (request.isCurrent() && watchesProject !== undefined) await fetchWatches(watchesProject ?? undefined);
  }

  async function toggleWatch(watchId: number, enable: boolean): Promise<FolderWatch> {
    const request = mutations.capture();
    const endpoint = enable ? "enable" : "disable";
    const response = await api.post<components["schemas"]["FolderWatchOut"]>(`/deploy/watches/${watchId}/${endpoint}`);
    const watch = folderWatch(response.data);
    if (request.isCurrent() && watchesProject !== undefined) await fetchWatches(watchesProject ?? undefined);
    return watch;
  }

  async function fetchDeployRuns(
    sourceType?: string,
    label?: string,
    projectId?: number,
  ): Promise<void> {
    const request = runsRequests.begin();
    runsLoading.value = true;
    try {
      const params: Record<string, string | number> = {};
      if (projectId != null) params.project_id = projectId;
      if (sourceType) params.source_type = sourceType;
      if (label) params.label = label;
      const response = await api.get<components["schemas"]["ExecutionRunList"]>("/deploy/runs", {
        params, signal: request.signal,
      });
      if (!request.isCurrent()) return;
      deployRuns.value = response.data.runs.map(runSummary);
      runsError.value = "";
    } catch (error) {
      if (request.isCurrent()) runsError.value = "Prediction history could not be loaded.";
    } finally {
      if (request.isCurrent()) runsLoading.value = false;
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
