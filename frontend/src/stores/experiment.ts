/* eslint-disable @typescript-eslint/no-explicit-any -- experiment store normalizes backend/axios failures with varying payload shapes. */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { isCancel } from "axios";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
import { activeProjectScope } from "@/stores/projectScopeRegistry";
import { useAuthStore } from "@/stores/auth";
import { useDataStore } from "@/stores/data";
import { useProjectStore } from "@/stores/project";
import { useScopedRequest, type ScopedRequestTicket } from "@/composables/useScopedRequest";
import type {
  ExperimentDetail,
  ExperimentFile,
  ExperimentSummary,
  VersionInfo,
} from "@/types";

interface ExperimentCreatePayload {
  name: string;
  description?: string | null;
  metadata: Record<string, unknown>;
}

export const useExperimentStore = defineStore("experiment", () => {
  const experiments = ref<ExperimentSummary[]>([]);
  const currentExperiment = ref<ExperimentDetail | null>(null);
  const files = ref<ExperimentFile[]>([]);
  const versions = ref<VersionInfo[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const selectedExperimentId = ref<number | null>(null);
  const accountIdentity = () => [useAuthStore().user?.id, useAuthStore().token];
  const identity = () => [...accountIdentity(), activeProjectScope.value, selectedExperimentId.value];
  const listScope = useScopedRequest(
    () => [...accountIdentity(), activeProjectScope.value],
    () => { loading.value = false; },
  );
  const selectionScope = useScopedRequest(identity, () => { loading.value = false; });
  const detailScope = useScopedRequest(identity);
  const filesScope = useScopedRequest(identity);
  const versionsScope = useScopedRequest(identity);
  const mutationScope = useScopedRequest(identity);
  const accountMutationScope = useScopedRequest(accountIdentity);
  function captureMutationScope(): ScopedRequestTicket {
    return mutationScope.capture();
  }

  async function refreshWrittenInventories(account: ScopedRequestTicket): Promise<void> {
    if (!account.isCurrent()) return;
    // A write must not reuse a GET started before that write was accepted.
    listScope.invalidate();
    await Promise.allSettled([
      fetchExperiments(activeProjectScope.value),
      useDataStore().fetchExperiments(),
      useDataStore().fetchCatalog(),
      useProjectStore().fetchProjects(),
    ]);
  }

  const currentExperimentId = computed(() => currentExperiment.value?.id ?? null);

  function resetProjectScope(): void {
    for (const scope of [listScope, selectionScope, detailScope, filesScope, versionsScope, mutationScope]) scope.invalidate();
    selectedExperimentId.value = null;
    experiments.value = [];
    currentExperiment.value = null;
    files.value = [];
    versions.value = [];
    loading.value = false;
    error.value = null;
  }
  registerProjectScopeReset(resetProjectScope);

  let pendingList: { projectId: number | null; ticket: ScopedRequestTicket; promise: Promise<void> } | null = null;
  const fetchExperiments = (projectId: number | null = activeProjectScope.value): Promise<void> => {
    if (pendingList?.projectId === projectId && pendingList.ticket.isCurrent()) return pendingList.promise;
    const request = listScope.begin();
    loading.value = true;
    const promise = (async () => { try {
      const response = await api.get<ExperimentSummary[]>("/experiments", {
        params: projectId == null ? undefined : { project_id: projectId },
        signal: request.signal,
      });
      if (request.isCurrent()) experiments.value = response.data;
    } catch (err: any) {
      if (!request.isCurrent() || isCancel(err)) return;
      if (request.isCurrent()) error.value = err?.message || "Failed to load experiments";
      throw err;
    } finally {
      if (request.isCurrent()) loading.value = false;
      if (pendingList?.ticket === request) pendingList = null;
    } })();
    pendingList = { projectId, ticket: request, promise };
    return promise;
  };

  const fetchExperiment = async (experimentId: number) => {
    const request = detailScope.begin();
    const response = await api.get<ExperimentDetail>(`/experiments/${experimentId}`, { signal: request.signal });
    if (request.isCurrent()) currentExperiment.value = response.data;
    return response.data;
  };

  const fetchFiles = async (experimentId: number) => {
    const request = filesScope.begin();
    const response = await api.get<ExperimentFile[]>(
      `/experiments/${experimentId}/files`, { signal: request.signal }
    );
    if (request.isCurrent()) files.value = response.data;
    return response.data;
  };

  const fetchVersions = async (experimentId: number) => {
    const request = versionsScope.begin();
    const response = await api.get<VersionInfo[]>(
      `/experiments/${experimentId}/versions`, { signal: request.signal }
    );
    if (request.isCurrent()) versions.value = response.data;
    return response.data;
  };

  const selectExperiment = async (experimentId: number) => {
    selectedExperimentId.value = experimentId;
    const request = selectionScope.begin();
    currentExperiment.value = null;
    files.value = [];
    versions.value = [];
    loading.value = true;
    try {
      await Promise.all([
        fetchExperiment(experimentId),
        fetchFiles(experimentId),
        fetchVersions(experimentId),
      ]);
    } catch (err: any) {
      if (request.isCurrent()) error.value = err?.message || "Failed to load experiment details";
      throw err;
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  };

  const createExperiment = async (payload: ExperimentCreatePayload) => {
    const request = captureMutationScope();
    const account = accountMutationScope.capture();
    loading.value = true;
    try {
      const response = await api.post<ExperimentDetail>("/experiments", payload);
      await refreshWrittenInventories(account);
      return response.data;
    } catch (err: any) {
      if (request.isCurrent()) error.value = err?.message || "Failed to create experiment";
      throw err;
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  };

  const updateExperiment = async (
    experimentId: number,
    payload: Partial<ExperimentCreatePayload>
  ) => {
    const request = captureMutationScope();
    const account = accountMutationScope.capture();
    loading.value = true;
    try {
      const response = await api.put<ExperimentDetail>(
        `/experiments/${experimentId}`,
        payload
      );
      if (request.isCurrent() && currentExperimentId.value === experimentId) currentExperiment.value = response.data;
      await refreshWrittenInventories(account);
      return response.data;
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  };

  const deleteExperiment = async (experimentId: number) => {
    const request = captureMutationScope();
    const account = accountMutationScope.capture();
    loading.value = true;
    try {
      await api.delete(`/experiments/${experimentId}`);
      await refreshWrittenInventories(account);
      if (!request.isCurrent()) return;
      if (currentExperiment.value?.id === experimentId) {
        currentExperiment.value = null;
        files.value = [];
        versions.value = [];
      }
    } finally {
      if (request.isCurrent()) loading.value = false;
    }
  };

  const uploadFile = async (
    experimentId: number,
    file: File,
    stage: string
  ) => {
    const request = captureMutationScope();
    const account = accountMutationScope.capture();
    const form = new FormData();
    form.append("file", file);
    form.append("stage", stage);
    await api.post(`/experiments/${experimentId}/files`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await fetchFiles(experimentId);
  };

  const createVersion = async (
    experimentId: number,
    versionName: string,
    description?: string,
    stages?: string[]
  ) => {
    const request = captureMutationScope();
    await api.post(`/experiments/${experimentId}/versions`, {
      version_name: versionName,
      description: description || null,
      stages: stages?.length ? stages : null,
    });
    if (request.isCurrent()) await fetchVersions(experimentId);
  };

  const restoreVersion = async (experimentId: number, versionName: string) => {
    const request = captureMutationScope();
    const account = accountMutationScope.capture();
    await api.post(`/experiments/${experimentId}/versions/${versionName}/restore`, null, {
      params: { overwrite: true },
    });
    await refreshWrittenInventories(account);
    if (request.isCurrent()) await fetchFiles(experimentId);
  };

  return {
    experiments,
    currentExperiment,
    files,
    versions,
    loading,
    error,
    currentExperimentId,
    fetchExperiments,
    selectExperiment,
    createExperiment,
    updateExperiment,
    deleteExperiment,
    uploadFile,
    createVersion,
    restoreVersion,
    fetchFiles,
    fetchVersions,
    resetProjectScope,
  };
});
