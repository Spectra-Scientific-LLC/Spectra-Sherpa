/* eslint-disable @typescript-eslint/no-explicit-any -- experiment store normalizes backend/axios failures with varying payload shapes. */
import { defineStore } from "pinia";
import { computed, ref } from "vue";
import api from "@/api/client";
import { registerProjectScopeReset } from "@/stores/projectScopeRegistry";
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

  const currentExperimentId = computed(() => currentExperiment.value?.id ?? null);

  function resetProjectScope(): void {
    experiments.value = [];
    currentExperiment.value = null;
    files.value = [];
    versions.value = [];
    loading.value = false;
    error.value = null;
  }
  registerProjectScopeReset(resetProjectScope);

  const fetchExperiments = async (projectId?: number | null) => {
    loading.value = true;
    try {
      const response = await api.get<ExperimentSummary[]>("/experiments", {
        params: projectId == null ? undefined : { project_id: projectId },
      });
      experiments.value = response.data;
    } catch (err: any) {
      error.value = err?.message || "Failed to load experiments";
      throw err;
    } finally {
      loading.value = false;
    }
  };

  const fetchExperiment = async (experimentId: number) => {
    const response = await api.get<ExperimentDetail>(`/experiments/${experimentId}`);
    currentExperiment.value = response.data;
    return response.data;
  };

  const fetchFiles = async (experimentId: number) => {
    const response = await api.get<ExperimentFile[]>(
      `/experiments/${experimentId}/files`
    );
    files.value = response.data;
    return response.data;
  };

  const fetchVersions = async (experimentId: number) => {
    const response = await api.get<VersionInfo[]>(
      `/experiments/${experimentId}/versions`
    );
    versions.value = response.data;
    return response.data;
  };

  const selectExperiment = async (experimentId: number) => {
    loading.value = true;
    try {
      await Promise.all([
        fetchExperiment(experimentId),
        fetchFiles(experimentId),
        fetchVersions(experimentId),
      ]);
    } catch (err: any) {
      error.value = err?.message || "Failed to load experiment details";
      throw err;
    } finally {
      loading.value = false;
    }
  };

  const createExperiment = async (payload: ExperimentCreatePayload) => {
    loading.value = true;
    try {
      const response = await api.post<ExperimentDetail>("/experiments", payload);
      experiments.value = [response.data, ...experiments.value];
      return response.data;
    } catch (err: any) {
      error.value = err?.message || "Failed to create experiment";
      throw err;
    } finally {
      loading.value = false;
    }
  };

  const updateExperiment = async (
    experimentId: number,
    payload: Partial<ExperimentCreatePayload>
  ) => {
    loading.value = true;
    try {
      const response = await api.put<ExperimentDetail>(
        `/experiments/${experimentId}`,
        payload
      );
      currentExperiment.value = response.data;
      experiments.value = experiments.value.map((item) =>
        item.id === experimentId ? response.data : item
      );
      return response.data;
    } finally {
      loading.value = false;
    }
  };

  const deleteExperiment = async (experimentId: number) => {
    loading.value = true;
    try {
      await api.delete(`/experiments/${experimentId}`);
      experiments.value = experiments.value.filter((exp) => exp.id !== experimentId);
      if (currentExperiment.value?.id === experimentId) {
        currentExperiment.value = null;
        files.value = [];
        versions.value = [];
      }
    } finally {
      loading.value = false;
    }
  };

  const uploadFile = async (
    experimentId: number,
    file: File,
    stage: string
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("stage", stage);
    await api.post(`/experiments/${experimentId}/files`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    await fetchFiles(experimentId);
  };

  const createVersion = async (
    experimentId: number,
    versionName: string,
    description?: string,
    stages?: string[]
  ) => {
    await api.post(`/experiments/${experimentId}/versions`, {
      version_name: versionName,
      description: description || null,
      stages: stages?.length ? stages : null,
    });
    await fetchVersions(experimentId);
  };

  const restoreVersion = async (experimentId: number, versionName: string) => {
    await api.post(`/experiments/${experimentId}/versions/${versionName}/restore`, null, {
      params: { overwrite: true },
    });
    await fetchFiles(experimentId);
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
